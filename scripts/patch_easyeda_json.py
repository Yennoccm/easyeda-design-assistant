#!/usr/bin/env python3
"""
Patch an EasyEDA Standard schematic JSON with UUID/puuid data so that
footprints resolve correctly when converting schematic → PCB.

THE KEY INSIGHT:
EasyEDA Standard LIB entries have 16 tilde-delimited fields. The uuid and puuid
MUST be set as fields 7 and 8 in the tilde-delimited line — these become DOM
attributes on the <g> element that the PCB conversion engine reads. Putting them
only inside the c_para backtick string (field 3) is NOT sufficient.

The full LIB format:
  LIB~x~y~c_para~rotation~0~ggeID~puuid~uuid~0~hash1~yes~yes~hash2~timestamp~hash3#@$sub_shapes

Also: EasyEDA Standard project JSON is NESTED. The shape array lives at
schematics[0].dataStr.shape, NOT at the top level.

Usage:
    # Using a UUID JSON file from easyeda_uuid_lookup.py:
    python patch_easyeda_json.py \\
        --input schematic.json \\
        --uuids uuids.json \\
        --parts parts_map.json \\
        --output schematic_patched.json

    # parts_map.json maps designator → LCSC part number:
    # { "C1": "C1620078", "U1": "C7236", "R1": "C723553" }
    #
    # uuids.json is the output from easyeda_uuid_lookup.py:
    # { "C1620078": { "uuid": "...", "puuid": "...", "package": "..." } }
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ── EasyEDA LIB Format ──────────────────────────────────────────────────
#
# Full 16-field format:
#   Field 0:  LIB (type prefix)
#   Field 1:  x position
#   Field 2:  y position
#   Field 3:  c_para (backtick-delimited key-value string)
#   Field 4:  rotation (0, 90, 180, 270)
#   Field 5:  0 (always)
#   Field 6:  ggeID (e.g., gge1234)
#   Field 7:  puuid (footprint UUID) ← CRITICAL
#   Field 8:  uuid (schematic symbol UUID) ← CRITICAL
#   Field 9:  0 (always)
#   Field 10: hash1 (can be empty)
#   Field 11: yes (flag)
#   Field 12: yes (flag)
#   Field 13: hash2 (can be empty)
#   Field 14: timestamp (can be empty)
#   Field 15: hash3 (can be empty)
#   Then: #@$ separator + sub-shapes
#
# Minimal/legacy format (fewer fields):
#   LIB~x~y~c_para~~0~ggeID#@$sub_shapes
#   (uuid and puuid are missing — this is what we need to fix)


def parse_cpara(blob: str) -> dict:
    """Parse backtick-delimited c_para into ordered dict-like structure."""
    tokens = blob.split("`")
    fields = {"_order": [], "_values": {}}
    i = 0
    while i < len(tokens) - 1:
        key = tokens[i]
        val = tokens[i + 1] if i + 1 < len(tokens) else ""
        if key:
            if key not in fields["_values"]:
                fields["_order"].append(key)
            fields["_values"][key] = val
        i += 2
    return fields


def render_cpara(fields: dict) -> str:
    """Render parsed c_para back to backtick-delimited string."""
    parts = []
    for key in fields["_order"]:
        parts.append(key)
        parts.append(fields["_values"].get(key, ""))
    return "`".join(parts)


def set_cpara_field(fields: dict, key: str, value: str):
    """Set a field in the c_para, adding it if not present."""
    if key not in fields["_values"]:
        fields["_order"].append(key)
    fields["_values"][key] = value


def get_cpara_field(fields: dict, key: str, default: str = "") -> str:
    return fields["_values"].get(key, default)


def patch_lib_entry(lib_str: str, parts_map: dict, uuid_data: dict) -> tuple:
    """
    Patch a single LIB entry with UUID/puuid data.

    Handles both the full 16-field format and the minimal/legacy format.
    Sets uuid/puuid as tilde-delimited fields (7 and 8) AND in c_para.

    Returns (patched_string, designator_or_None, was_changed).
    """
    # Split on #@$ to separate the LIB header from sub-shapes
    head, sep, rest = lib_str.partition("#@$")

    # Split the header into tilde-delimited fields
    tilde_fields = head.split("~")

    if len(tilde_fields) < 4 or tilde_fields[0] != "LIB":
        return lib_str, None, False

    # Field 3 is always c_para
    cpara_blob = tilde_fields[3]
    cpara = parse_cpara(cpara_blob)

    # Get the designator
    pre = get_cpara_field(cpara, "pre", "")
    if not pre:
        return lib_str, None, False

    # Look up the LCSC part number for this designator
    lcsc = parts_map.get(pre, "")
    if not lcsc:
        return lib_str, pre, False

    # Look up the UUID data for this LCSC part
    uuids = uuid_data.get(lcsc, {})
    if "error" in uuids or not uuids.get("puuid"):
        return lib_str, pre, False

    uuid_val = uuids.get("uuid", "")
    puuid_val = uuids.get("puuid", "")
    package = uuids.get("package", "")

    # ── Update c_para fields ──
    if uuid_val:
        set_cpara_field(cpara, "uuid", uuid_val)
    if puuid_val:
        set_cpara_field(cpara, "puuid", puuid_val)
    if package:
        set_cpara_field(cpara, "package", package)
    if lcsc:
        set_cpara_field(cpara, "LcscPart", lcsc)

    new_cpara = render_cpara(cpara)
    tilde_fields[3] = new_cpara

    # ── Set uuid/puuid as tilde-delimited fields 7 and 8 ──
    # This is the CRITICAL fix. These become DOM attributes on the <g> element.
    # Field 7 = puuid (footprint UUID)
    # Field 8 = uuid (symbol UUID)
    if len(tilde_fields) >= 16:
        # Full 16-field format — set fields 7 and 8 directly
        if puuid_val:
            tilde_fields[7] = puuid_val
        if uuid_val:
            tilde_fields[8] = uuid_val
    elif len(tilde_fields) >= 9:
        # Has enough fields but might have empty uuid/puuid slots
        if puuid_val:
            tilde_fields[7] = puuid_val
        if uuid_val:
            tilde_fields[8] = uuid_val
    else:
        # Minimal/legacy format: LIB~x~y~c_para~~0~ggeID (7 fields)
        # We need to expand to at least 16 fields.
        # Current: [LIB, x, y, c_para, "", "0", ggeID]
        #
        # Target:  [LIB, x, y, c_para, rotation, "0", ggeID, puuid, uuid,
        #           "0", "", "yes", "yes", "", "", ""]
        #
        # The "" field at index 4 is rotation (default 0), field 5 is "0",
        # field 6 is the ggeID.

        # Ensure we have at least 7 fields
        while len(tilde_fields) < 7:
            tilde_fields.append("")

        gge_id = tilde_fields[6]

        # Expand: insert puuid (field 7), uuid (field 8), and remaining fields
        # after ggeID
        expanded = tilde_fields[:7]  # LIB through ggeID
        expanded.append(puuid_val)    # field 7: puuid (footprint)
        expanded.append(uuid_val)     # field 8: uuid (symbol)
        expanded.append("0")          # field 9: always 0
        expanded.append("")           # field 10: hash1
        expanded.append("yes")        # field 11: flag
        expanded.append("yes")        # field 12: flag
        expanded.append("")           # field 13: hash2
        expanded.append("")           # field 14: timestamp
        expanded.append("")           # field 15: hash3
        tilde_fields = expanded

    # Rebuild the head
    new_head = "~".join(tilde_fields)

    if sep:
        return new_head + sep + rest, pre, True
    else:
        return new_head, pre, True


def find_shape_array(data: dict) -> tuple:
    """
    Find the shape array in the schematic JSON, handling both formats:
    1. Nested: schematics[0].dataStr.shape (standard project format, docType "5")
    2. Flat: data.shape (single-sheet export, docType "1")

    Returns (shape_list, setter_function) where setter_function writes back.
    """
    # Try nested format first (docType "5" project)
    schematics = data.get("schematics", [])
    if schematics and isinstance(schematics, list):
        for i, sheet in enumerate(schematics):
            data_str = sheet.get("dataStr", {})
            if isinstance(data_str, dict) and "shape" in data_str:
                shapes = data_str["shape"]
                def setter(new_shapes, _i=i):
                    data["schematics"][_i]["dataStr"]["shape"] = new_shapes
                return shapes, setter

    # Try flat format (docType "1" single sheet)
    if "shape" in data:
        def setter(new_shapes):
            data["shape"] = new_shapes
        return data["shape"], setter

    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Patch EasyEDA schematic JSON with UUID/puuid data for footprint linking"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Input EasyEDA schematic JSON file"
    )
    parser.add_argument(
        "--uuids", "-u", required=True,
        help="UUID data JSON from easyeda_uuid_lookup.py"
    )
    parser.add_argument(
        "--parts", "-p", required=True,
        help="Parts map JSON: { designator: LCSC_part_number }"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Output patched JSON file"
    )
    args = parser.parse_args()

    # Load inputs
    schematic = json.loads(Path(args.input).read_text(encoding="utf-8"))
    uuid_data = json.loads(Path(args.uuids).read_text(encoding="utf-8"))
    parts_map = json.loads(Path(args.parts).read_text(encoding="utf-8"))

    doc_type = schematic.get("docType", "unknown")
    print(f"Document type: {doc_type}")

    shapes, set_shapes = find_shape_array(schematic)
    if shapes is None:
        print("ERROR: Could not find shape array in schematic JSON.", file=sys.stderr)
        print("Expected either schematics[0].dataStr.shape (project) or shape (single sheet).",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(shapes)} shapes in schematic")

    patched_count = 0
    skipped = []
    patched_refs = []

    new_shapes = []
    for s in shapes:
        if isinstance(s, str) and s.startswith("LIB~"):
            patched, ref, changed = patch_lib_entry(s, parts_map, uuid_data)
            new_shapes.append(patched)
            if changed:
                patched_count += 1
                patched_refs.append(ref)
            elif ref:
                lcsc = parts_map.get(ref, "")
                if lcsc:
                    uuids = uuid_data.get(lcsc, {})
                    reason = uuids.get("error", "no puuid in UUID data")
                    skipped.append(f"{ref} ({lcsc}): {reason}")
                else:
                    skipped.append(f"{ref}: not in parts map")
        else:
            new_shapes.append(s)

    set_shapes(new_shapes)

    # Write output
    Path(args.output).write_text(
        json.dumps(schematic, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Report
    print(f"\nPatched {patched_count} components: {', '.join(patched_refs)}")
    if skipped:
        print(f"\nSkipped {len(skipped)} components:")
        for s in skipped:
            print(f"  - {s}")

    print(f"\nOutput: {args.output}")
    print("\nNEXT STEPS:")
    print("1. Import the patched JSON into EasyEDA (File → Open → EasyEDA Source)")
    print("2. If footprints still don't resolve, run the browser DOM fix:")
    print("   (see SKILL.md Phase 4, Method B)")
    print("3. Design → Convert Schematic to PCB to verify all footprints")


if __name__ == "__main__":
    main()
