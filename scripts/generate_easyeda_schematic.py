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
     Field 7 = uuid  (SYMBOL UUID, from API result.uuid)
     Field 8 = puuid (FOOTPRINT UUID, from API head.puuid)
     This matches real EasyEDA-exported schematics. The DOM attribute names
     are MISLEADING (field 7 → DOM "puuid", field 8 → DOM "uuid").
     Swapping based on DOM names (v5) caused 41/43 pin-to-pad failures.

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
    return shape_str


def _offset_pin(s: str, dx: float, dy: float) -> str:
    """Offset all coordinates in a pin shape."""
    sections = s.split("^^")
    new_sections = []

    for i, section in enumerate(sections):
        if i == 0:
            # Header: P~show~type~num~X~Y~rot~id~0
            fields = section.split("~")
            if len(fields) >= 6:
                fields[4] = str(int(float(fields[4]) + dx))
                fields[5] = str(int(float(fields[5]) + dy))
            new_sections.append("~".join(fields))
        elif i == 1:
            # Pin endpoint: X~Y
            fields = section.split("~")
            if len(fields) >= 2:
                fields[0] = str(int(float(fields[0]) + dx))
                fields[1] = str(int(float(fields[1]) + dy))
            new_sections.append("~".join(fields))
        elif i == 2:
            # SVG path
            new_sections.append(_offset_svg_path(section, dx, dy))
        else:
            # Label/marker sections
            fields = section.split("~")
            if len(fields) >= 3 and fields[0] in ("0", "1"):
                try:
                    fields[1] = str(int(float(fields[1]) + dx))
                    fields[2] = str(int(float(fields[2]) + dy))
                    new_sections.append("~".join(fields))
                except ValueError:
                    new_sections.append(_offset_svg_path(section, dx, dy))
            else:
                new_sections.append(_offset_svg_path(section, dx, dy))

    return "^^".join(new_sections)


def _offset_svg_path(s: str, dx: float, dy: float) -> str:
    def replace_coords(match):
        cmd = match.group(1)
        x = int(float(match.group(2)) + dx)
        y = int(float(match.group(3)) + dy)
        sep = "," if "," in match.group(0) else " "
        return f"{cmd}{sep}{x}{sep}{y}" if sep == "," else f"{cmd} {x} {y}"

    result = re.sub(r'([ML])\s*(\-?\d+(?:\.\d+)?)[,\s]+(\-?\d+(?:\.\d+)?)', replace_coords, s)
    return result


def _offset_polyline(s: str, dx: float, dy: float) -> str:
    fields = s.split("~")
    if len(fields) >= 2:
        coords = fields[1].split(" ")
        new_coords = []
        for i in range(0, len(coords) - 1, 2):
            try:
                new_coords.append(str(int(float(coords[i]) + dx)))
                new_coords.append(str(int(float(coords[i + 1]) + dy)))
            except (ValueError, IndexError):
                new_coords.extend(coords[i:i+2])
        fields[1] = " ".join(new_coords)
    return "~".join(fields)


def _offset_rectangle(s: str, dx: float, dy: float) -> str:
    fields = s.split("~")
    if len(fields) >= 3:
        try:
            fields[1] = str(int(float(fields[1]) + dx))
            fields[2] = str(int(float(fields[2]) + dy))
        except ValueError:
            pass
    return "~".join(fields)


def _offset_text(s: str, dx: float, dy: float) -> str:
    fields = s.split("~")
    if len(fields) >= 3:
        try:
            fields[1] = str(int(float(fields[1]) + dx))
            fields[2] = str(int(float(fields[2]) + dy))
        except ValueError:
            pass
    return "~".join(fields)


def _offset_arc(s: str, dx: float, dy: float) -> str:
    fields = s.split("~")
    if len(fields) >= 3:
        try:
            fields[1] = str(int(float(fields[1]) + dx))
            fields[2] = str(int(float(fields[2]) + dy))
        except ValueError:
            pass
    return "~".join(fields)


def _rename_gge_ids(s: str) -> str:
    """Replace all gge/rep IDs in a shape string with globally unique ones.

    EasyEDA requires every element to have a unique gge ID across the entire
    schematic. API-fetched symbols reuse IDs like gge26, rep2, rep3 — when
    the same LCSC part is used for multiple components (e.g. 19 resistors
    sharing C17414), those IDs collide and break footprint verification.

    This function finds all occurrences of gge{N}, rep{N}, and flag_gge{N}
    patterns and replaces each unique one with a fresh global ID.
    """
    import re as _re
    id_map = {}

    def replacer(match):
        old_id = match.group(0)
        if old_id not in id_map:
            id_map[old_id] = next_gge()
        return id_map[old_id]

    return _re.sub(r'(?:flag_)?(?:gge|rep)\d+[a-f0-9]*', replacer, s)


# ── Net Flag Generation (F~ format) ───────────────────────────────────
# Real EasyEDA format learned from exported schematics:
#
# F~part_netLabel_netPort~X~Y~ROTATION~ggeID~~0
#   ^^X~Y
#   ^^NET_NAME~#0000FF~labelX~labelY~labelRot~~1~Times New Roman~8pt~flag_ggeID
#   ^^PL~polyline_coords~#0000FF~1~0~transparent~ggeID~0
#
# The polyline draws an arrow/pentagon shape pointing toward the connection.
# Shape varies by rotation.

def make_flag_label(net_name: str, endpoint_count: int) -> str:
    if endpoint_count <= 2:
        return net_name
    return f"{net_name}:{endpoint_count}"


def _flag_polyline(x, y, rotation, size=15):
    """
    Generate the polyline coordinates for a netPort flag arrow shape.
    Based on real EasyEDA flag shapes at different rotations.
    Size controls the flag length (default 15 units).
    """
    s = size
    hs = s // 3  # half-width of the arrow head

    if rotation == 0:
        # Arrow pointing right → flag body extends left
        # PL~X Y X-hs Y+hs X-s Y+hs X-s Y-hs X-hs Y-hs X Y
        return f"{x} {y} {x-hs} {y+hs} {x-s} {y+hs} {x-s} {y-hs} {x-hs} {y-hs} {x} {y}"
    elif rotation == 180:
        # Arrow pointing left → flag body extends right
        return f"{x} {y} {x+hs} {y-hs} {x+s} {y-hs} {x+s} {y+hs} {x+hs} {y+hs} {x} {y}"
    elif rotation == 90:
        # Arrow pointing up → flag body extends down
        return f"{x} {y} {x+hs} {y+hs} {x+hs} {y+s} {x-hs} {y+s} {x-hs} {y+hs} {x} {y}"
    elif rotation == 270:
        # Arrow pointing down → flag body extends up
        return f"{x} {y} {x-hs} {y-hs} {x-hs} {y-s} {x+hs} {y-s} {x+hs} {y-hs} {x} {y}"
    else:
        # Default: right-pointing
        return f"{x} {y} {x-hs} {y+hs} {x-s} {y+hs} {x-s} {y-hs} {x-hs} {y-hs} {x} {y}"


def _flag_label_position(x, y, rotation, size=15):
    """Calculate label text position based on flag rotation.

    The label sits on the BODY side of the flag (opposite the arrow tip).
    After the rotation fix, flag rotation 180 means arrow points left
    (body extends right), so label goes to the right.
    """
    s = size
    if rotation == 0:    # arrow right, body left → label left of body
        return x - s - 8, y + 4, 0
    elif rotation == 180: # arrow left, body right → label right of body
        return x + s + 8, y + 4, 0
    elif rotation == 90:  # arrow up, body down → label below body
        return x + 8, y + s + 8, 0
    elif rotation == 270: # arrow down, body up → label above body
        return x + 8, y - s - 8, 0
    return x - s - 8, y + 4, 0


def make_net_flag(x: float, y: float, rotation: int, label: str) -> str:
    """
    Generate an EasyEDA net flag (F~ shape) at the given position.
    Uses part_netLabel_netPort for custom signal nets.
    """
    x, y = int(x), int(y)
    gge_main = next_gge()
    gge_flag = next_flag_gge()
    gge_pl = next_gge()

    pl_coords = _flag_polyline(x, y, rotation)
    lx, ly, lrot = _flag_label_position(x, y, rotation)

    flag_str = (
        f"F~part_netLabel_netPort~{x}~{y}~{rotation}~{gge_main}~~0"
        f"^^{x}~{y}"
        f"^^{label}~#0000FF~{lx}~{ly}~{lrot}~~1~Times New Roman~8pt~{gge_flag}"
        f"^^PL~{pl_coords}~#0000FF~1~0~transparent~{gge_pl}~0"
    )
    return flag_str


def make_gnd_flag(x: float, y: float, rotation: int, label: str = "GND") -> str:
    """Generate a GND power flag with the standard ground symbol.

    Real EasyEDA GND flags have 5 PL entries: 1 stem + 4 bars of decreasing width.
    Pattern from real export (rotation=90, pointing right):
      PL stem:  10px from x to bar start
      PL bar1:  ±9 (18px wide)
      PL bar2:  ±6 (12px wide)  (+2 offset)
      PL bar3:  ±3 (6px wide)   (+4 offset)
      PL bar4:  ±1 (2px wide)   (+6 offset)
    """
    x, y = int(x), int(y)
    gge_main = next_gge()
    gge_flag = next_flag_gge()

    shapes = []
    if rotation == 90:  # flag points right, bars extend right
        bx = x + 10
        shapes.append(f"PL~{bx} {y} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx} {y-9} {bx} {y+9}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx+2} {y-6} {bx+2} {y+6}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx+4} {y-3} {bx+4} {y+3}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx+6} {y-1} {bx+6} {y+1}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x + 18, y + 4, 0
    elif rotation == 270:  # flag points left, bars extend left
        bx = x - 10
        shapes.append(f"PL~{bx} {y} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx} {y-9} {bx} {y+9}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx-2} {y-6} {bx-2} {y+6}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx-4} {y-3} {bx-4} {y+3}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{bx-6} {y-1} {bx-6} {y+1}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 22, y + 4, 0
    elif rotation == 0:  # flag points down, bars extend down
        by = y + 10
        shapes.append(f"PL~{x} {by} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-9} {by} {x+9} {by}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-6} {by+2} {x+6} {by+2}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-3} {by+4} {x+3} {by+4}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-1} {by+6} {x+1} {by+6}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 5, y + 27, 0
    else:  # 180, flag points up, bars extend up
        by = y - 10
        shapes.append(f"PL~{x} {by} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-9} {by} {x+9} {by}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-6} {by-2} {x+6} {by-2}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-3} {by-4} {x+3} {by-4}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-1} {by-6} {x+1} {by-6}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 5, y - 27, 0

    pl_section = "^^".join(shapes)

    flag_str = (
        f"F~part_netLabel_gnD~{x}~{y}~{rotation}~{gge_main}~~0"
        f"^^{x}~{y}"
        f"^^{label}~#000000~{lx}~{ly}~{lrot}~start~1~Times New Roman~9pt~{gge_flag}"
        f"^^{pl_section}"
    )
    return flag_str


def make_vcc_flag(x: float, y: float, rotation: int, label: str = "VCC") -> str:
    """Generate a VCC power flag with the standard bar symbol."""
    x, y = int(x), int(y)
    gge_main = next_gge()
    gge_flag = next_flag_gge()

    shapes = []
    if rotation == 90:  # bar to the left
        bx = x - 10
        shapes.append(f"PL~{bx} {y} {x} {y}~#000000~1~0~none~{next_gge()}~0")
        shapes.append(f"PL~{bx} {y-5} {bx} {y+5}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 20, y + 4, 0
    elif rotation == 0:  # bar above
        by = y - 10
        shapes.append(f"PL~{x} {by} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-5} {by} {x+5} {by}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 10, y - 15, 0
    else:  # default: bar above
        by = y - 10
        shapes.append(f"PL~{x} {by} {x} {y}~#000000~1~0~transparent~{next_gge()}~0")
        shapes.append(f"PL~{x-5} {by} {x+5} {by}~#000000~1~0~transparent~{next_gge()}~0")
        lx, ly, lrot = x - 10, y - 15, 0

    pl_section = "^^".join(shapes)

    flag_str = (
        f"F~part_netLabel_VCC~{x}~{y}~{rotation}~{gge_main}~~0"
        f"^^{x}~{y}"
        f"^^{label}~#000000~{lx}~{ly}~{lrot}~start~1~Times New Roman~9pt~{gge_flag}"
        f"^^{pl_section}"
    )
    return flag_str


def make_nc_marker(x: float, y: float) -> str:
    """Generate a No Connect (X) marker at the given pin endpoint.

    Format learned from real EasyEDA schematics:
      O~X~Y~ggeID~M (X-4) (Y-4) L (X+4) (Y+4) M (X+4) (Y-4) L (X-4) (Y+4)~#33cc33~0

    The marker draws a green X (two diagonal lines, 8px wide) centered on
    the pin endpoint, telling EasyEDA's DRC that the pin is intentionally
    left unconnected.
    """
    x, y = int(x), int(y)
    gge = next_gge()
    return (
        f"O~{x}~{y}~{gge}"
        f"~M {x-4} {y-4} L {x+4} {y+4} M {x+4} {y-4} L {x-4} {y+4}"
        f"~#33cc33~0"
    )


def make_wire(x1, y1, x2, y2):
    """Generate a wire shape string.
    Format: W~points~#color~strokeWidth~strokeStyle~fillColor~ggeID~locked
    NO snapping — coordinates must exactly match pin/flag positions.
    Symbols may use a 5px internal grid, and snapping creates connection gaps."""
    gge = next_gge()
    return f"W~{int(x1)} {int(y1)} {int(x2)} {int(y2)}~#008800~1~0~none~{gge}~0"


# ── Component Placement ───────────────────────────────────────────────

def calculate_grid_position_ic(index: int, y_start: int) -> tuple:
    """Grid position for ICs (3+ pins) — wider spacing."""
    col = index % GRID_COLS_IC
    row = index // GRID_COLS_IC
    x = snap10(GRID_START_X + col * GRID_SPACING_IC_X)
    y = snap10(y_start + row * GRID_SPACING_IC_Y)
    return x, y


def calculate_grid_position_passive(index: int, y_start: int) -> tuple:
    """Grid position for passives (2-pin) — tighter spacing."""
    col = index % GRID_COLS_PASSIVE
    row = index // GRID_COLS_PASSIVE
    x = snap10(GRID_START_X + col * GRID_SPACING_PASSIVE_X)
    y = snap10(y_start + row * GRID_SPACING_PASSIVE_Y)
    return x, y


def get_flag_position(pin_x, pin_y, pin_rotation):
    """Calculate flag position and rotation from a pin.

    The flag is placed at the end of a stub wire extending from the pin.
    The flag's arrow/symbol should point TOWARD the pin (back toward
    the component), so the flag rotation is 180° opposite to the
    direction we extend.

    Pin rotation convention:
      0   = pin extends right (dot is right of body)
      90  = pin extends up (dot is above body)
      180 = pin extends left (dot is left of body)
      270 = pin extends down (dot is below body)

    Flag rotation convention:
      0   = arrow points right, body extends left
      90  = arrow points up, body extends down
      180 = arrow points left, body extends right
      270 = arrow points down, body extends up

    So if pin extends RIGHT, flag is further right, and flag should
    point LEFT (rotation=180) back toward the pin.
    """
    offset = FLAG_OFFSET
    # NO snapping — flag position must maintain a straight wire from the pin.
    # Symbols may have pins on a 5px grid, and snapping would create a 5px gap.
    if pin_rotation == 0:    # pin extends right → flag further right, points left
        return int(pin_x + offset), int(pin_y), 180
    elif pin_rotation == 90:  # pin extends up → flag further up, points down
        return int(pin_x), int(pin_y - offset), 270
    elif pin_rotation == 180: # pin extends left → flag further left, points right
        return int(pin_x - offset), int(pin_y), 0
    elif pin_rotation == 270: # pin extends down → flag further down, points up
        return int(pin_x), int(pin_y + offset), 90
    return int(pin_x + offset), int(pin_y), 180


# ── LIB Entry Assembly ────────────────────────────────────────────────
# Real format from EasyEDA exports:
# LIB~X~Y~c_para~ROTATION~0~ggeID~uuid~puuid~0~??~yes~yes~??~num
#   #@$sub_shape1#@$sub_shape2...

def build_cpara_string(designator: str, value: str, comp_data: dict,
                       lcsc_part: str = "") -> str:
    """Build the backtick-delimited c_para string.

    Includes uuid, puuid, and LCSC metadata so that:
      - EasyEDA's Properties dialog shows supplier info
      - BOM export includes LCSC part numbers (critical for JLCPCB ordering)
      - JSON round-trip export/import preserves linkage data
    """
    parts = []

    if comp_data.get("package"):
        parts.extend(["package", comp_data["package"]])

    parts.extend(["pre", designator])

    if value:
        parts.extend(["Value", value])
        parts.extend(["nameAlias", "Value"])

    # Copy relevant fields from API c_para
    api_cpara = comp_data.get("c_para", {})
    for key in ("Supplier", "Supplier Part", "Manufacturer", "Manufacturer Part",
                "JLCPCB Part Class", "spicePre", "spiceSymbolName"):
        if key in api_cpara:
            parts.extend([key, api_cpara[key]])

    # Inject uuid/puuid and LCSC linkage into c_para.
    # Without these, the Properties dialog won't show supplier info and
    # BOM export won't include LCSC part numbers.
    uuid = comp_data.get("uuid", "")
    puuid = comp_data.get("puuid", "")
    if uuid:
        parts.extend(["uuid", uuid])
    if puuid:
        parts.extend(["puuid", puuid])
    if lcsc_part:
        parts.extend(["LcscPart", lcsc_part])
        # Ensure Supplier and SupplierPart are always present
        if "Supplier" not in api_cpara:
            parts.extend(["Supplier", "LCSC"])
        if "Supplier Part" not in api_cpara:
            parts.extend(["Supplier Part", lcsc_part])

    return "`".join(parts)


def build_lib_entry(designator, value, comp_data, canvas_x, canvas_y,
                    lcsc_part=""):
    """Build a complete LIB shape string for the schematic."""
    origin_x = comp_data["origin_x"]
    origin_y = comp_data["origin_y"]

    # Snap the offset so that pin dots land on the 10px grid.
    # If the component origin is off-grid (e.g. 405), we adjust canvas_x
    # so that dx is a multiple of 10, ensuring all pin coordinates snap.
    dx = snap10(canvas_x - origin_x)
    dy = snap10(canvas_y - origin_y)
    # Recalculate actual canvas position from snapped offset
    canvas_x = origin_x + dx
    canvas_y = origin_y + dy

    cpara = build_cpara_string(designator, value, comp_data, lcsc_part)

    uuid = comp_data.get("uuid", "")
    puuid = comp_data.get("puuid", "")

    # Collect all shapes (handle subparts)
    all_shapes = list(comp_data["shapes"])
    all_pins = []

    if comp_data.get("subparts"):
        for sp in comp_data["subparts"]:
            sp_dx = canvas_x - sp["origin_x"]
            sp_dy = canvas_y - sp["origin_y"]
            all_shapes.extend(sp["shapes"])
            for pin in sp["pins"]:
                all_pins.append({
                    "pin_number": pin["pin_number"],
                    "x": pin["x"] + sp_dx,
                    "y": pin["y"] + sp_dy,
                    "rotation": pin["rotation"],
                    "name": pin["name"],
                })
    else:
        for pin in comp_data["pins"]:
            all_pins.append({
                "pin_number": pin["pin_number"],
                "x": int(pin["x"] + dx),   # NO snap — must match actual LIB pin position
                "y": int(pin["y"] + dy),    # Symbols may use 5px grid internally
                "rotation": pin["rotation"],
                "name": pin["name"],
            })

    # Offset all shapes and assign globally unique gge IDs.
    # API shapes reuse IDs like gge26, rep2 — these MUST be unique across the
    # entire schematic or EasyEDA's footprint checker breaks.
    offset_shapes = []
    seen_pins = set()
    for s in all_shapes:
        if isinstance(s, str):
            os = offset_shape(s, dx, dy)
            # Deduplicate pins from subparts
            if os.startswith("P~"):
                pf = os.split("^^")[0].split("~")
                if len(pf) >= 4:
                    pk = pf[3]
                    if pk in seen_pins:
                        continue
                    seen_pins.add(pk)
            # Replace all gge/rep IDs with globally unique ones
            os = _rename_gge_ids(os)
            offset_shapes.append(os)

    gge = next_gge()

    # Add T~P~ (prefix/designator) and T~N~ (name/value) text sub-shapes.
    # These are required for EasyEDA to display the component reference and value.
    # Format from real schematics:
    #   T~{mark}~{x}~{y}~{rot}~{color}~{font}~{size}~{weight}~{style}~
    #   {baseline}~{type}~{text}~{visible}~{anchor}~{ggeID}~{locked}~{pinpart}
    #
    # Place prefix ABOVE and value BELOW the component center
    # with enough offset to avoid overlapping the component body.
    cx, cy = int(canvas_x), int(canvas_y)
    # Adjust label offset based on component size (more pins = bigger body)
    num_pins = len(comp_data.get("pins", []))
    if num_pins > 2:
        # ICs — place labels further above to clear pin text
        tp_y = cy - 30
        tn_y = cy - 20
    else:
        # Passives — tighter labels
        tp_y = cy - 16
        tn_y = cy - 8
    tp_shape = (
        f"T~P~{cx + 6}~{tp_y}~0~#000080~Arial~~~~~comment"
        f"~{designator}~1~start~{next_gge()}~0~pinpart"
    )
    tn_shape = (
        f"T~N~{cx + 6}~{tn_y}~0~#000080~Arial~~~~~comment"
        f"~{value}~1~start~{next_gge()}~0~pinpart"
    )
    offset_shapes.append(tp_shape)
    offset_shapes.append(tn_shape)

    # Build LIB line matching real EasyEDA format (16 fields):
    # LIB~X~Y~c_para~ROTATION~0~ggeID~field7~field8~0~hash1~yes~yes~hash2~timestamp~hash3
    #
    # CRITICAL — Field 7/8 ordering:
    #   Field 7 = uuid  (SYMBOL UUID, from API result.uuid)
    #   Field 8 = puuid (FOOTPRINT UUID, from API head.puuid)
    #
    # Confirmed by comparing against real EasyEDA-exported schematics.
    # The DOM attribute names are MISLEADING (field 7 → DOM "puuid",
    # field 8 → DOM "uuid") — do NOT trust DOM attribute names.
    #
    # IMPORTANT: Even with correct ordering, JSON import does NOT auto-fetch
    # footprint geometry. After import, user MUST run:
    #   Design → Update Components from Library → Select All → Update
    # See pipeline step 7 in the module docstring.
    lib_header = (
        f"LIB~{int(canvas_x)}~{int(canvas_y)}~{cpara}"
        f"~0~0~{gge}~{uuid}~{puuid}~0~~yes~yes~~~"
    )

    sub_shapes_str = "#@$".join(offset_shapes)
    lib_str = f"{lib_header}#@${sub_shapes_str}"

    return lib_str, all_pins


# ── Main Generator ────────────────────────────────────────────────────

def generate_schematic(netlist: dict, output_path: str):
    """Generate an EasyEDA schematic JSON from a netlist."""
    components = netlist["components"]
    nets = netlist["nets"]

    print(f"Generating schematic with {len(components)} components and {len(nets)} nets\n")

    # Step 1: Fetch all component symbols
    print("Step 1: Fetching component symbols from EasyEDA API...")
    comp_data = {}
    lcsc_cache = {}

    for i, (ref, info) in enumerate(components.items()):
        lcsc = info["lcsc"]
        if lcsc in lcsc_cache:
            comp_data[ref] = lcsc_cache[lcsc]
            print(f"  [{i+1}/{len(components)}] {ref} ({lcsc}) — cached")
        else:
            print(f"  [{i+1}/{len(components)}] {ref} ({lcsc}) — fetching...")
            data = fetch_component(lcsc)
            if "error" in data:
                print(f"    ERROR: {data['error']}")
                continue
            puuid_status = "✓" if data["puuid"] else "✗"
            print(f"    OK: {data['title']}, {len(data['pins'])} pins, puuid={puuid_status}")
            lcsc_cache[lcsc] = data
            comp_data[ref] = data
            if i < len(components) - 1:
                time.sleep(API_DELAY)

    print(f"\nFetched {len(comp_data)} / {len(components)} components\n")

    # Step 2: Place components on grid — ICs first, then passives below
    print("Step 2: Placing components on grid...")
    shape_entries = []
    pin_map = {}  # {ref: {pin_num: {x, y, rotation}}}

    # Separate ICs (3+ pins) from passives (2 pins)
    ic_refs = [(ref, data) for ref, data in comp_data.items() if len(data["pins"]) > 2]
    passive_refs = [(ref, data) for ref, data in comp_data.items() if len(data["pins"]) <= 2]

    print(f"  ICs: {len(ic_refs)}, Passives: {len(passive_refs)}")

    # Place ICs first
    ic_y_start = GRID_START_Y
    max_ic_y = ic_y_start
    for i, (ref, data) in enumerate(ic_refs):
        cx, cy = calculate_grid_position_ic(i, ic_y_start)
        max_ic_y = max(max_ic_y, cy)
        value = components[ref].get("value", "")
        lcsc = components[ref].get("lcsc", "")
        lib_str, placed_pins = build_lib_entry(ref, value, data, cx, cy, lcsc)
        shape_entries.append(lib_str)
        pin_map[ref] = {}
        for p in placed_pins:
            pin_map[ref][p["pin_number"]] = p
        print(f"  {ref} at ({cx}, {cy}) — {len(placed_pins)} pins [IC]")

    # Place passives below ICs with tighter spacing
    passive_y_start = max_ic_y + GRID_SPACING_IC_Y  # gap after ICs
    for i, (ref, data) in enumerate(passive_refs):
        cx, cy = calculate_grid_position_passive(i, passive_y_start)
        value = components[ref].get("value", "")
        lcsc = components[ref].get("lcsc", "")
        lib_str, placed_pins = build_lib_entry(ref, value, data, cx, cy, lcsc)
        shape_entries.append(lib_str)
        pin_map[ref] = {}
        for p in placed_pins:
            pin_map[ref][p["pin_number"]] = p
        print(f"  {ref} at ({cx}, {cy}) — {len(placed_pins)} pins [passive]")

    # Step 3: Generate net flags
    print(f"\nStep 3: Generating net flags ({len(nets)} nets)...")

    for net_name, endpoints in nets.items():
        count = len(endpoints)
        flag_label = make_flag_label(net_name, count)

        placed = 0
        for endpoint in endpoints:
            if "." not in endpoint:
                print(f"  WARNING: Invalid endpoint '{endpoint}' — skipping")
                continue

            ref, pin_num = endpoint.rsplit(".", 1)
            if ref not in pin_map or pin_num not in pin_map[ref]:
                print(f"  WARNING: {endpoint} not found — skipping")
                continue

            pin = pin_map[ref][pin_num]
            px, py, prot = pin["x"], pin["y"], pin["rotation"]

            # Flag position (end of stub wire)
            fx, fy, frot = get_flag_position(px, py, prot)

            # Stub wire from pin to flag
            shape_entries.append(make_wire(px, py, fx, fy))

            # Net flag — use appropriate symbol type
            net_lower = net_name.lower()
            if net_lower in ("gnd", "agnd", "dgnd", "gnd_d", "gnd_a"):
                shape_entries.append(make_gnd_flag(fx, fy, frot, flag_label))
            elif net_lower in ("vcc", "vdd", "v+", "vaa", "+5v", "+3.3v", "+9v", "+12v"):
                shape_entries.append(make_vcc_flag(fx, fy, frot, flag_label))
            else:
                shape_entries.append(make_net_flag(fx, fy, frot, flag_label))

            placed += 1

        suffix = f" ({flag_label})" if ":" in flag_label else ""
        print(f"  {net_name}: {placed}/{count} flags placed{suffix}")

    # Step 3.5: Place NC (No Connect) markers on unconnected pins
    # Build set of all connected pins from the netlist
    connected_pins = set()
    for net_name, endpoints in nets.items():
        for endpoint in endpoints:
            connected_pins.add(endpoint)   # e.g. "U2.17"

    nc_count = 0
    for ref, pins in pin_map.items():
        for pin_num, pin in pins.items():
            endpoint_key = f"{ref}.{pin_num}"
            if endpoint_key not in connected_pins:
                # This pin has no net connection — place an NC X marker
                px, py = pin["x"], pin["y"]
                shape_entries.append(make_nc_marker(px, py))
                nc_count += 1

    print(f"\nStep 3.5: Placed {nc_count} NC (No Connect) markers on unconnected pins")

    # Step 4: Assemble schematic JSON (correct nested structure)
    print(f"\nStep 4: Assembling schematic JSON ({len(shape_entries)} shapes)...")

    schematic = {
        "editorVersion": "6.5.54",
        "docType": "5",
        "title": netlist.get("title", "Generated Schematic"),
        "description": netlist.get("description", "Auto-generated"),
        "colors": {},
        "schematics": [
            {
                "docType": "1",
                "title": netlist.get("title", "Generated Schematic"),
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
                        "transformList": "",
                    },
                    "canvas": "CA~1000~1000~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0",
                    "shape": shape_entries,
                    "BBox": {
                        "x": 0, "y": 0,
                        "width": 2000, "height": 1600,
                    },
                    "colors": {},
                }
            }
        ],
    }

    Path(output_path).write_text(
        json.dumps(schematic, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"\nOutput: {output_path}")
    print(f"  Components: {len(comp_data)}")
    print(f"  Nets: {len(nets)}")
    print(f"  Shapes: {len(shape_entries)}")
    print(f"\nNext steps:")
    print(f"  1. Open EasyEDA Standard")
    print(f"  2. File → Open → EasyEDA Source → select {output_path}")
    print(f"")
    print(f"  *** CRITICAL — do this BEFORE anything else: ***")
    print(f"  3. Design → Update Components from Library")
    print(f'     ☐ Check the box: "Check component latest version when open schematic"')
    print(f"     ☐ Select All → Update → OK on the warning")
    print(f"     (This fetches footprint geometry — without it ALL footprints fail)")
    print(f"")
    print(f"  4. Design → Footprints Verification → Check Footprints (should be 0 issues)")
    print(f"  5. Rearrange components as desired")
    print(f"  6. Design → Convert Schematic to PCB")


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate EasyEDA schematic JSON from a structured netlist"
    )
    parser.add_argument("--netlist", "-n", required=True, help="Input netlist JSON")
    parser.add_argument("--output", "-o", required=True, help="Output EasyEDA JSON")
    parser.add_argument("--delay", "-d", type=float, default=API_DELAY,
                        help=f"API delay (default: {API_DELAY}s)")
    args = parser.parse_args()

    netlist = json.loads(Path(args.netlist).read_text(encoding="utf-8"))

    if "components" not in netlist or "nets" not in netlist:
        print("ERROR: netlist must have 'components' and 'nets' keys", file=sys.stderr)
        sys.exit(1)

    generate_schematic(netlist, args.output)


if __name__ == "__main__":
    main()
