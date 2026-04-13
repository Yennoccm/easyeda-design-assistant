#!/usr/bin/env python3
"""
Generate an EasyEDA Standard schematic JSON from a structured netlist.

Takes a netlist JSON (components + nets + LCSC part numbers) and produces
a valid EasyEDA schematic JSON file that can be imported via
File → Open → EasyEDA Source. Components are placed on a grid with net
flags at every pin using the NETNAME:N naming convention.

Complete Pipeline:
  1. Read netlist.json (components + nets + LCSC part numbers)
  2. Fetch symbols from EasyEDA API (uuid, puuid, shapes, pins)
  3. Place components on grid, generate LIB entries
  4. Generate wire stubs + net flags for all connections
  5. Place NC markers on unconnected pins
  6. Output schematic JSON → import via File → Open → EasyEDA Source
  7. **IN EASYEDA**: Design → Update Components from Library
     → Check the box: "Check component latest version when open schematic"
     → Select All → Click "Update" → Click "OK" on the warning dialog
     This step is ESSENTIAL — JSON import loads symbol shapes but does NOT
     fetch footprint geometry. "Update from Library" triggers the server fetch.
  8. Design → Footprints Verification → Check Footprints (should be 0 issues)
  9. Design → Convert Schematic to PCB

CRITICAL LESSONS (hard-won from debugging — DO NOT remove these comments):

  1. LIB Field 7/8 Order:
     Field 7 = puuid (FOOTPRINT UUID, from API head.puuid)
     Field 8 = uuid  (SYMBOL UUID, from API result.uuid)
     Verified empirically: v7 (working) has puuid in field 7, uuid in field 8.
     v8 accidentally swapped them during SPICE refactoring → broke Update from Library.
     v9 restored correct order → works again.

  NOTE: Even with correct field 7/8, JSON-imported schematics need the
  "Update from Library" step (step 7 above) to fetch footprint geometry.
  Without it, Footprint Verification shows empty PAD info for all parts.

  2. gge ID Global Uniqueness:
     Every gge/rep ID must be unique across the ENTIRE schematic.
     API-fetched symbols reuse IDs like gge26, rep2. When the same LCSC
     part is cached for multiple components, ALL copies share IDs.
     Solution: _rename_gge_ids() replaces every ID with a unique one.
     A hand-drawn schematic has 0 duplicates. Without this fix we had 29.

  3. c_para Completeness:
     The backtick c_para string must include uuid, puuid, LcscPart,
     Supplier, Supplier Part for BOM export and Properties dialog.
     Without these, the schematic looks fine but JLCPCB ordering breaks.

NETNAME:N Convention:
  - If a net has exactly 2 endpoints: flag label = NETNAME
  - If a net has 3+ endpoints: flag label = NETNAME:N (where N = total count)

Format Reference: See references/easyeda_json_format.md

Usage:
    python generate_easyeda_schematic.py \\
        --netlist netlist.json \\
        --output schematic.json
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


# ── Configuration ──────────────────────────────────────────────────────

API_URL = "https://easyeda.com/api/products/{lcsc}/components"
API_DELAY = 1.0

GRID_START_X = 200
GRID_START_Y = 300

# Adaptive spacing — ICs get more room, passives get less
GRID_SPACING_IC_X = 400    # spacing for ICs (3+ pins)
GRID_SPACING_IC_Y = 400
GRID_SPACING_PASSIVE_X = 150   # spacing for 2-pin passives
GRID_SPACING_PASSIVE_Y = 120
GRID_COLS_IC = 3
GRID_COLS_PASSIVE = 6

FLAG_OFFSET = 30    # stub wire length from pin to flag

# ── SPICE Simulation Support ─────────────────────────────────────────
# EasyEDA Standard uses two c_para fields for simulation:
#   spicePre  — the SPICE netlist prefix (R, C, L, D, Q, X, etc.)
#   spiceSymbolName — the model name the simulator looks up
#
# For standard passives, EasyEDA has built-in models. For ICs, you need
# to inject a .subckt model as a text block (Path 2, future work).
#
# SPICE prefix reference (from EasyEDA docs):
#   R = Resistor       C = Capacitor      L = Inductor
#   D = Diode          Q = BJT            M = MOSFET
#   J = JFET           V = Voltage src    I = Current src
#   X = Subcircuit (ICs, op-amps, regulators, etc.)

# Map designator prefix → (spicePre, spiceSymbolName)
# NOTE: SPICE fields are currently disabled until a safe integration approach
# is finalized. These fields were causing issues during schematic-to-PCB
# conversion and require further testing and validation.
SPICE_PASSIVE_MAP = {
    # "R":  ("R", "Resistor"),
    # "C":  ("C", "Capacitor"),
    # "L":  ("L", "Inductor"),
    # "D":  ("D", "Diode"),
}

# Default simulation directives embedded in the head field.
# Format: "TRAN`tstep`tstop`tstart`{AC`type`npoints`fstart`fstop`{DC`src``start`stop`{TF`src``"
# NOTE: c_spiceCmd is currently disabled until SPICE integration is safer.
DEFAULT_SPICE_CMD = None  # Was: "TRAN`1u`10m`0`{AC`dec`10`1`1Meg`{DC`0``0`0`{TF```"


def get_spice_info(designator: str) -> tuple:
    """Return (spicePre, spiceSymbolName) for a designator, or (None, None).

    Currently returns (None, None) for all designators — SPICE fields
    are disabled until a safe integration approach is finalized.
    """
    return (None, None)


# Unique ID counter
_gge_counter = 50000


def next_gge():
    global _gge_counter
    _gge_counter += 1
    return f"gge{_gge_counter}"


def next_flag_gge():
    global _gge_counter
    _gge_counter += 1
    return f"flag_gge{_gge_counter}"


def snap10(v):
    """Snap a coordinate to the nearest 10px grid point.
    EasyEDA's grid is 10px — coordinates off-grid cause invisible
    connection failures where wires look connected but aren't."""
    return round(v / 10) * 10


# ── EasyEDA API ────────────────────────────────────────────────────────

def fetch_component(lcsc_part: str) -> dict:
    """Fetch a component's schematic symbol data from EasyEDA's API."""
    url = API_URL.format(lcsc=lcsc_part)
    req = urllib.request.Request(url, headers={
        "User-Agent": "easyeda-schematic-gen/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        return {"error": str(e), "lcsc": lcsc_part}

    if not data.get("success") or not data.get("result"):
        return {"error": "Part not found", "lcsc": lcsc_part}

    result = data["result"]
    if isinstance(result, list):
        comp = None
        for r in result:
            dt = r.get("dataStr", {}).get("head", {}).get("docType")
            if dt in ("1", "2", 1, 2):
                comp = r
                break
        if comp is None:
            comp = result[0]
    else:
        comp = result

    ds = comp.get("dataStr", {})
    head = ds.get("head", {})

    uuid = comp.get("uuid", "") or head.get("uuid", "")
    puuid = head.get("puuid", "")

    c_para = head.get("c_para", {})
    if isinstance(c_para, str):
        c_para = _parse_cpara_str(c_para)
    package = c_para.get("package", "")

    origin_x = float(head.get("x", 400))
    origin_y = float(head.get("y", 300))

    shapes = ds.get("shape", [])
    pins = _extract_pins(shapes)

    # Handle subparts (multi-part ICs)
    subparts_data = comp.get("subparts", [])
    subparts = []
    if subparts_data:
        for sp in subparts_data:
            sp_ds = sp.get("dataStr", {})
            sp_shapes = sp_ds.get("shape", [])
            sp_pins = _extract_pins(sp_shapes)
            sp_head = sp_ds.get("head", {})
            subparts.append({
                "shapes": sp_shapes,
                "pins": sp_pins,
                "origin_x": float(sp_head.get("x", origin_x)),
                "origin_y": float(sp_head.get("y", origin_y)),
            })

    return {
        "uuid": uuid,
        "puuid": puuid,
        "package": package,
        "shapes": shapes,
        "pins": pins,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "subparts": subparts,
        "c_para": c_para,
        "title": comp.get("title", ""),
    }


def _parse_cpara_str(blob: str) -> dict:
    tokens = blob.split("`")
    result = {}
    for i in range(0, len(tokens) - 1, 2):
        if tokens[i]:
            result[tokens[i]] = tokens[i + 1]
    return result


def _extract_pins(shapes: list) -> list:
    """Extract pin data from shape strings."""
    pins = []
    for s in shapes:
        if not isinstance(s, str) or not s.startswith("P~"):
            continue
        sections = s.split("^^")
        header = sections[0].split("~")
        if len(header) < 7:
            continue

        pin_num = header[3]
        pin_x = float(header[4])
        pin_y = float(header[5])
        pin_rot = int(header[6])

        # Extract pin name from label sections
        pin_name = ""
        for part in sections[1:]:
            sub = part.split("~")
            if len(sub) >= 5 and sub[0] == "0":
                name_candidate = sub[4]
                if name_candidate and name_candidate != pin_num:
                    pin_name = name_candidate
                    break

        pins.append({
            "pin_number": pin_num,
            "x": pin_x,
            "y": pin_y,
            "rotation": pin_rot,
            "name": pin_name,
            "raw": s,
        })
    return pins


# ── Coordinate Transformation ─────────────────────────────────────────

def offset_shape(shape_str: str, dx: float, dy: float) -> str:
    """Apply a coordinate offset to a shape string."""
    if not isinstance(shape_str, str):
        return shape_str

    if shape_str.startswith("P~"):
        return _offset_pin(shape_str, dx, dy)
    elif shape_str.startswith("PL~"):
        return _offset_polyline(shape_str, dx, dy)
    elif shape_str.startswith("R~"):
        return _offset_rectangle(shape_str, dx, dy)
    elif shape_str.startswith("T~"):
        return _offset_text(shape_str, dx, dy)
    elif shape_str.startswith("A~"):
        return _offset_arc(shape_str, dx, dy)
    elif shape_str.startswith("E~"):
        return _offset_ellipse(shape_str, dx, dy)
    return shape_str


def _offset_pin(s: str, dx: float, dy: float) -> str:
    """Offset a P~ (pin) shape."""
    sections = s.split("^^")
    header = sections[0].split("~")

    if len(header) >= 6:
        header[4] = str(snap10(float(header[4]) + dx))
        header[5] = str(snap10(float(header[5]) + dy))

    result = "~".join(header)
    for sec in sections[1:]:
        result += "^^" + sec
    return result


def _offset_polyline(s: str, dx: float, dy: float) -> str:
    """Offset a PL~ (polyline) shape."""
    parts = s.split("~")
    if len(parts) < 2:
        return s

    # Extract coordinate portion (part 1) and rest (parts 2+)
    coords = parts[1]
    rest = "~".join(parts[2:])

    # Parse and offset coordinates
    coords_list = coords.split(" ")
    offset_coords = []
    for i, c in enumerate(coords_list):
        try:
            val = float(c)
            if i % 2 == 0:
                offset_coords.append(str(snap10(val + dx)))
            else:
                offset_coords.append(str(snap10(val + dy)))
        except ValueError:
            offset_coords.append(c)

    return "PL~" + " ".join(offset_coords) + "~" + rest


def _offset_rectangle(s: str, dx: float, dy: float) -> str:
    """Offset a R~ (rectangle) shape."""
    parts = s.split("~")
    if len(parts) >= 4:
        parts[1] = str(snap10(float(parts[1]) + dx))
        parts[2] = str(snap10(float(parts[2]) + dy))
    return "~".join(parts)


def _offset_text(s: str, dx: float, dy: float) -> str:
    """Offset a T~ (text) shape."""
    parts = s.split("~")
    if len(parts) >= 3:
        parts[1] = str(snap10(float(parts[1]) + dx))
        parts[2] = str(snap10(float(parts[2]) + dy))
    return "~".join(parts)


def _offset_arc(s: str, dx: float, dy: float) -> str:
    """Offset an A~ (arc) shape."""
    parts = s.split("~")
    if len(parts) >= 3:
        parts[1] = str(snap10(float(parts[1]) + dx))
        parts[2] = str(snap10(float(parts[2]) + dy))
    return "~".join(parts)


def _offset_ellipse(s: str, dx: float, dy: float) -> str:
    """Offset an E~ (ellipse) shape."""
    parts = s.split("~")
    if len(parts) >= 3:
        parts[1] = str(snap10(float(parts[1]) + dx))
        parts[2] = str(snap10(float(parts[2]) + dy))
    return "~".join(parts)


# ── Build gge Renaming Functions ──────────────────────────────────────

def _build_gge_map(shapes: list) -> dict:
    """Build a mapping from old gge IDs to new unique ones."""
    mapping = {}
    pattern = re.compile(r"(gge\d+|rep\d+)")

    for shape in shapes:
        if not isinstance(shape, str):
            continue
        for match in pattern.finditer(shape):
            old_id = match.group(1)
            if old_id not in mapping:
                mapping[old_id] = next_gge()

    return mapping


def _rename_gge_ids(shapes: list, mapping: dict) -> list:
    """Rename all gge IDs in shapes according to the mapping."""
    new_shapes = []
    pattern = re.compile(r"(gge\d+|rep\d+)")

    for shape in shapes:
        if not isinstance(shape, str):
            new_shapes.append(shape)
            continue
        new_shape = pattern.sub(lambda m: mapping.get(m.group(1), m.group(1)), shape)
        new_shapes.append(new_shape)

    return new_shapes


# ── c_para String Building ────────────────────────────────────────────

def build_cpara_string(designator: str, lcsc_part: str, uuid: str, puuid: str,
                       package: str, value: str = "") -> str:
    """Build a backtick-delimited c_para string for a component.

    The c_para string holds component metadata that persists when the
    schematic is exported and re-imported. Essential fields:
      - pre: designator (R1, C5, U2, etc.)
      - uuid: symbol UUID (for Properties dialog round-trip)
      - puuid: footprint UUID (for BOM and linking)
      - LcscPart: LCSC part number (for JLCPCB ordering)
      - package: footprint name (R0805, SOT-223, SSOP-24, etc.)
      - Supplier: supplier name (usually LCSC)
      - SupplierPart: supplier part number
    """
    parts = []

    # Standard order
    parts.append(f"pre`{designator}")

    if package:
        parts.append(f"package`{package}")
    if value:
        parts.append(f"Value`{value}")

    # UUID fields
    if uuid:
        parts.append(f"uuid`{uuid}")
    if puuid:
        parts.append(f"puuid`{puuid}")

    # Supplier info
    if lcsc_part:
        parts.append(f"LcscPart`{lcsc_part}")
        parts.append(f"Supplier`LCSC")
        parts.append(f"SupplierPart`{lcsc_part}")

    return "`".join(parts) + "`"


# ── LIB Entry Building ────────────────────────────────────────────────

def build_lib_entry(designator: str, lcsc_part: str, x: float, y: float,
                    api_data: dict) -> tuple:
    """Build a complete LIB entry for a component placed at (x, y).

    Returns (lib_str, pinout_dict) where pinout_dict maps pin_number → (px, py)
    for later wire generation.

    The LIB format has 16 tilde-delimited fields:
      0: LIB (type prefix)
      1: x (position)
      2: y (position)
      3: c_para (backtick-delimited metadata string)
      4: rotation (0, 90, 180, 270)
      5: 0 (always)
      6: ggeID (element identifier)
      7: puuid (FOOTPRINT UUID) — CRITICAL
      8: uuid (SYMBOL UUID) — CRITICAL
      9: 0 (always)
      10-15: hash and timestamp fields (usually empty)
      #@$: separator
      sub-shapes: pin, line, arc, text, etc.
    """
    if "error" in api_data:
        return "", {}

    x = snap10(x)
    y = snap10(y)

    uuid = api_data.get("uuid", "")
    puuid = api_data.get("puuid", "")
    package = api_data.get("package", "")
    shapes = api_data.get("shapes", [])
    pins = api_data.get("pins", [])
    origin_x = api_data.get("origin_x", 0)
    origin_y = api_data.get("origin_y", 0)
    c_para_dict = api_data.get("c_para", {})

    # Calculate component offset
    dx = x - origin_x
    dy = y - origin_y

    # Build c_para string
    cpara_str = build_cpara_string(designator, lcsc_part, uuid, puuid, package)

    # Offset and rename gge IDs in shapes
    offset_shapes = [offset_shape(s, dx, dy) for s in shapes]
    gge_map = _build_gge_map(offset_shapes)
    renamed_shapes = _rename_gge_ids(offset_shapes, gge_map)

    # Build sub-shapes string
    sub_shapes = "#@$" + "#@$".join(renamed_shapes)

    # Get component gge ID
    comp_gge = next_gge()

    # Calculate pinout (absolute coordinates on canvas)
    pinout = {}
    for pin in pins:
        pin_num = pin["pin_number"]
        px = pin["x"] + dx
        py = pin["y"] + dy
        px = snap10(px)
        py = snap10(py)
        pinout[pin_num] = (px, py)

    # Build LIB header (16 fields)
    lib_header = (
        f"LIB~{int(x)}~{int(y)}~{cpara_str}~0~0~{comp_gge}~{puuid}~{uuid}~0~~yes~yes~~~"
    )

    lib_entry = lib_header + sub_shapes

    return lib_entry, pinout


# ── Wire and Net Flag Building ────────────────────────────────────────

def make_wire(p1: tuple, p2: tuple) -> str:
    """Create a W~ (wire) shape connecting two points.

    Wire format: W~x1 y1 x2 y2~color~width~0~style~ggeID~0
    """
    x1, y1 = int(snap10(p1[0])), int(snap10(p1[1]))
    x2, y2 = int(snap10(p2[0])), int(snap10(p2[1]))
    gge = next_gge()
    return f"W~{x1} {y1} {x2} {y2}~#008800~1~0~none~{gge}~0"


def make_net_flag(net_name: str, x: float, y: float, net_count: int = 0) -> str:
    """Create an F~ (net flag) shape for a net connection point.

    Net flags use the NETNAME:N convention:
      - Exactly 2 endpoints: label = NETNAME
      - 3+ endpoints: label = NETNAME:N (where N = endpoint count)
    """
    x = snap10(x)
    y = snap10(y)

    label = net_name
    if net_count > 2:
        label = f"{net_name}:{net_count}"

    gge = next_gge()
    flag_gge = next_flag_gge()

    flag_type = "part_netLabel_netPort"
    if label.upper() in ["GND", "VSS", "GROUND"]:
        flag_type = "part_netLabel_gnD"
    elif label.upper() in ["VCC", "VDD", "3V3", "5V"]:
        flag_type = "part_netLabel_VCC"

    # Minimal F~ entry with position and label
    return f"F~{flag_type}~{int(x)}~{int(y)}~0~{gge}~~0^^{int(x)}~{int(y)}^^{label}~#0000FF~{int(x-30)}~{int(y)}~0~~1~Times New Roman~8pt~{flag_gge}"


def make_nc_marker(x: float, y: float) -> str:
    """Create an NC (no connect) marker for an unconnected pin.

    Format: O~x~y~ggeID~path~color~0
    The path draws an X: diagonals from (x-4,y-4) to (x+4,y+4) and vice versa
    """
    x = snap10(x)
    y = snap10(y)
    gge = next_gge()

    x_i = int(x)
    y_i = int(y)
    path = f"M {x_i-4} {y_i-4} L {x_i+4} {y_i+4} M {x_i+4} {y_i-4} L {x_i-4} {y_i+4}"
    return f"O~{x_i}~{y_i}~{gge}~{path}~#33cc33~0"


# ── Main Schematic Assembly ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate an EasyEDA Standard schematic JSON from a netlist"
    )
    parser.add_argument(
        "--netlist", "-n", required=True,
        help="Input netlist JSON file (components + nets + LCSC parts)"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Output schematic JSON file"
    )
    args = parser.parse_args()

    # Load netlist
    netlist = json.loads(Path(args.netlist).read_text(encoding="utf-8"))

    components = netlist.get("components", {})
    nets = netlist.get("nets", {})

    print(f"Loaded {len(components)} components, {len(nets)} nets")

    # Fetch API data for unique LCSC parts (with caching)
    api_cache = {}
    unique_parts = set(c.get("lcsc") for c in components.values() if c.get("lcsc"))
    print(f"Fetching {len(unique_parts)} unique LCSC parts from EasyEDA API...")

    for i, lcsc_part in enumerate(sorted(unique_parts)):
        if not lcsc_part:
            continue
        print(f"  {i+1}/{len(unique_parts)}: {lcsc_part}", end="", flush=True)
        api_cache[lcsc_part] = fetch_component(lcsc_part)
        if "error" in api_cache[lcsc_part]:
            print(f" ERROR: {api_cache[lcsc_part]['error']}")
        else:
            print(" OK")
        time.sleep(API_DELAY)

    # Layout components on grid
    print("\nPlacing components on grid...")
    component_order = sorted(components.keys())
    all_pinouts = {}  # designator → {pin_num → (x, y)}

    row = 0
    col = 0
    for idx, designator in enumerate(component_order):
        comp = components[designator]
        lcsc = comp.get("lcsc", "")
        api_data = api_cache.get(lcsc, {})

        # Determine spacing based on component type
        pin_count = len(api_data.get("pins", []))
        is_ic = pin_count >= 3

        if is_ic:
            spacing_x = GRID_SPACING_IC_X
            spacing_y = GRID_SPACING_IC_Y
            cols = GRID_COLS_IC
        else:
            spacing_x = GRID_SPACING_PASSIVE_X
            spacing_y = GRID_SPACING_PASSIVE_Y
            cols = GRID_COLS_PASSIVE

        # Compute grid position
        if col >= cols:
            row += 1
            col = 0

        x = GRID_START_X + col * spacing_x
        y = GRID_START_Y + row * spacing_y

        # Build LIB entry
        lib_entry, pinout = build_lib_entry(designator, lcsc, x, y, api_data)
        if lib_entry:
            all_pinouts[designator] = pinout
            print(f"  {designator} at ({x}, {y}): {len(pinout)} pins")
        else:
            print(f"  {designator}: SKIPPED (API error or missing data)")

        col += 1

    # Build net wires and flags
    print(f"\nGenerating {len(nets)} net flags...")
    net_shapes = []

    for net_name, endpoints in nets.items():
        if not endpoints:
            continue

        # For each endpoint, draw a wire stub and flag
        for designator, pin_num in endpoints:
            if designator not in all_pinouts or pin_num not in all_pinouts[designator]:
                print(f"  {net_name} pin {designator}.{pin_num}: NOT FOUND (skipped)")
                continue

            px, py = all_pinouts[designator][pin_num]

            # Determine flag offset direction based on pin
            # (simplified: just offset to the right for now)
            fx = px + FLAG_OFFSET
            fy = py

            # Add wire from pin to flag
            wire = make_wire((px, py), (fx, fy))
            net_shapes.append(wire)

        # Add net flag (once per net)
        if endpoints:
            first_des, first_pin = endpoints[0]
            if first_des in all_pinouts and first_pin in all_pinouts[first_des]:
                px, py = all_pinouts[first_des][first_pin]
                fx = px + FLAG_OFFSET
                fy = py
                flag = make_net_flag(net_name, fx, fy, len(endpoints))
                net_shapes.append(flag)
                print(f"  {net_name} ({len(endpoints)} endpoints)")

    # Mark unconnected pins with NC markers
    print("\nMarking unconnected pins...")
    nc_count = 0
    for designator, pinout in all_pinouts.items():
        for pin_num, (px, py) in pinout.items():
            connected = False
            for endpoints in nets.values():
                if (designator, pin_num) in endpoints:
                    connected = True
                    break
            if not connected:
                nc_marker = make_nc_marker(px, py)
                net_shapes.append(nc_marker)
                nc_count += 1

    print(f"  Marked {nc_count} unconnected pins")

    # Assemble complete component shapes
    all_shapes = []

    # Re-fetch and place all component LIB entries
    row = 0
    col = 0
    for designator in component_order:
        comp = components[designator]
        lcsc = comp.get("lcsc", "")
        api_data = api_cache.get(lcsc, {})

        pin_count = len(api_data.get("pins", []))
        is_ic = pin_count >= 3
        spacing_x = GRID_SPACING_IC_X if is_ic else GRID_SPACING_PASSIVE_X
        spacing_y = GRID_SPACING_IC_Y if is_ic else GRID_SPACING_PASSIVE_Y
        cols = GRID_COLS_IC if is_ic else GRID_COLS_PASSIVE

        if col >= cols:
            row += 1
            col = 0

        x = GRID_START_X + col * spacing_x
        y = GRID_START_Y + row * spacing_y

        lib_entry, _ = build_lib_entry(designator, lcsc, x, y, api_data)
        if lib_entry:
            all_shapes.append(lib_entry)

        col += 1

    # Append net shapes
    all_shapes.extend(net_shapes)

    # Build the complete schematic JSON
    schematic = {
        "editorVersion": "6.5.54",
        "docType": "5",
        "title": "Generated Schematic",
        "description": "Auto-generated from netlist",
        "colors": {},
        "schematics": [
            {
                "docType": "1",
                "title": "Sheet 1",
                "description": "",
                "dataStr": {
                    "head": {
                        "docType": "1",
                        "editorVersion": "6.5.54",
                        "newgId": True,
                        "c_para": {"Prefix Start": "1"},
                        "c_spiceCmd": None,
                        "hasIdFlag": True,
                        "x": "0",
                        "y": "0",
                        "importFlag": 0,
                        "transformList": ""
                    },
                    "canvas": "CA~1000~1000~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0",
                    "shape": all_shapes,
                    "BBox": {"x": 0, "y": 0, "width": 2000, "height": 1600},
                    "colors": {}
                }
            }
        ]
    }

    # Write output
    Path(args.output).write_text(
        json.dumps(schematic, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"\nSchematic written to {args.output}")
    print("\nNEXT STEPS:")
    print("1. In EasyEDA: File → Open → EasyEDA Source → select the JSON file")
    print("2. ESSENTIAL: Design → Update Components from Library")
    print("   → Check the box: 'Check component latest version when open schematic'")
    print("   → Select All → Check ONLY 'Footprint/Package' column")
    print("   → Do NOT check 'Symbol' (overwrites schematic symbols!)")
    print("   → Click 'Update' → Click 'OK' on the warning")
    print("3. Design → Footprints Verification → Check Footprints (should show 0 issues)")
    print("4. Design → Convert Schematic to PCB")


if __name__ == "__main__":
    main()
