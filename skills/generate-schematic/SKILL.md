---
name: generate-schematic
description: >
  Generate a valid EasyEDA Standard schematic JSON file from a structured netlist.
  This skill takes a netlist (components + nets + LCSC part numbers) and produces
  an importable EasyEDA schematic with correct symbols, net flags, stub wires,
  designators, values, and footprint UUIDs — ready for File → Open → EasyEDA Source.

  Use this skill when the user has a completed circuit design (from circuit-designer
  or their own work) and wants to programmatically generate the EasyEDA schematic
  JSON rather than manually placing components. Also trigger when the user says
  "generate the schematic", "create the EasyEDA JSON", "make the schematic file",
  "turn this netlist into a schematic", or "I have the circuit, now make the file".

  This skill wraps the generate_easyeda_schematic.py engine script which handles
  all the precise coordinate math, API fetching, grid snapping, and format compliance.
  The skill's job is to structure the input, invoke the engine, validate the output,
  and guide the user through import.
---

# Generate EasyEDA Schematic

Programmatically generate a valid EasyEDA Standard schematic JSON from a structured
netlist. The output file can be imported directly via File → Open → EasyEDA Source.

## When to Use This Skill

- You have a completed circuit design with component values and LCSC part numbers
- You want to skip manual component placement and go straight to an importable file
- You're coming from the circuit-designer skill and want to continue the pipeline
- You have a netlist in any format and want an EasyEDA schematic

## Pipeline Position

```
  circuit-designer (idea → circuit design + netlist)
      ↓
  ★ generate-schematic (netlist → EasyEDA JSON)  ← YOU ARE HERE
      ↓
  easyeda-design-assistant (refinement + footprint linking + PCB prep)
```

---

## Phase 1: Build the Netlist JSON

The generator engine requires a structured netlist JSON. If the user doesn't already
have one, build it from their circuit design.

### Netlist JSON Schema

```json
{
  "title": "Project Name",
  "description": "Brief description",
  "components": {
    "R1": { "lcsc": "C723553",  "value": "1kΩ" },
    "R2": { "lcsc": "C119208",  "value": "20kΩ" },
    "C1": { "lcsc": "C1620078", "value": "100nF" },
    "U1": { "lcsc": "C7236",    "value": "TL072CP" }
  },
  "nets": {
    "VCC":   ["R1.1", "R2.1", "U1.8"],
    "GND":   ["C1.2", "U1.4"],
    "SIG_A": ["R1.2", "C1.1"],
    "FB":    ["R2.2", "U1.1", "U1.2"]
  }
}
```

### Key Rules for the Netlist

**Components:**
- Keys are reference designators (R1, C1, U1, etc.)
- `lcsc` is the LCSC part number (starts with C followed by digits)
- `value` is the display value (shown on the schematic)

**Nets:**
- Keys are net names (any string — colons are allowed)
- Values are arrays of endpoints in `REF.PIN_NUMBER` format
- Pin numbers must match the EasyEDA symbol's actual pin numbering
- Every pin that participates in the circuit should appear in exactly one net

**NETNAME:N Convention (automatic):**
The generator automatically applies the naming convention:
- 2-endpoint nets: flag label = NETNAME (e.g., `SIG_A`)
- 3+ endpoint nets: flag label = NETNAME:N (e.g., `VCC:5`)
This lets humans verify connection counts at a glance.

### Finding LCSC Part Numbers

If the user doesn't have LCSC numbers:

1. **Search LCSC directly:**
   Use web search for `site:lcsc.com {part description}` or
   `lcsc.com {manufacturer part number}`

2. **Use the EasyEDA API:**
   The generator script fetches component symbols from EasyEDA's API using LCSC
   numbers. If a part isn't on LCSC, it can't be auto-generated — the user will
   need to place it manually in EasyEDA.

3. **Common LCSC numbers for prototyping:**
   - Through-hole resistors (1/4W): C723553 (1kΩ), C119208 (20kΩ), etc.
   - Through-hole ceramic caps: C1620078 (100nF), etc.
   - DIP-8 op-amps: C7236 (TL072CP), etc.
   - Always verify these are in stock before committing.

### Finding Pin Numbers

Pin numbers must match the EasyEDA symbol, not the physical package. To check:

1. Look up the part on easyeda.com or lcsc.com
2. Open the schematic symbol
3. Note the pin numbers as labeled on the symbol

For common 2-pin passives (resistors, caps): pins are typically 1 and 2.
For ICs: check the specific symbol — pin numbers match the datasheet.

---

## Phase 2: Run the Generator

Once the netlist JSON is ready, invoke the engine script.

### Save the Netlist

Save the netlist JSON to the project's scripts directory:

```bash
# Save to the scripts directory alongside the generator
cat > {project_root}/scripts/netlist.json << 'EOF'
{netlist JSON here}
EOF
```

### Run the Generator

```bash
python {project_root}/scripts/generate_easyeda_schematic.py \
    --netlist {project_root}/scripts/netlist.json \
    --output {output_path}/schematic.json
```

The script will:
1. Fetch component symbols from EasyEDA's API (with 1s delay between requests)
2. Place components on a grid
3. Generate net flags with the NETNAME:N convention
4. Create stub wires from each pin to its flag
5. Add designator (T~P~) and value (T~N~) labels
6. Assemble the complete nested JSON structure
7. Snap ALL coordinates to the 10px grid

### Handle API Failures

If a component's LCSC number is wrong or the part isn't in EasyEDA's library,
the script will print an error and skip that component. Check the output for
any "ERROR" lines and fix the LCSC numbers before re-running.

---

## Phase 3: Validate the Output

Run a validation audit on the generated JSON before presenting it to the user.

### Quick Validation Script

```python
import json, re

def validate_schematic(filepath):
    with open(filepath) as f:
        sch = json.load(f)

    shapes = sch["schematics"][0]["dataStr"]["shape"]
    errors = 0

    # 1. Grid compliance — every coordinate must be a multiple of 10
    for shape in shapes:
        if shape.startswith("W~"):
            pts = shape.split("~")[1].split(" ")
            for j in range(0, len(pts), 2):
                x, y = int(pts[j]), int(pts[j+1])
                if x % 10 != 0 or y % 10 != 0:
                    print(f"GRID ERROR: Wire ({x},{y})")
                    errors += 1
        if shape.startswith("LIB~"):
            pre = re.search(r'pre`([^`]*)`', shape)
            for m in re.finditer(r'P~show~\d+~(\d+)~(-?\d+)~(-?\d+)', shape):
                pn, px, py = m.group(1), int(m.group(2)), int(m.group(3))
                if px % 10 != 0 or py % 10 != 0:
                    print(f"GRID ERROR: {pre.group(1) if pre else '?'} pin {pn} at ({px},{py})")
                    errors += 1

    # 2. Every LIB has package, designator, value, and text labels
    for shape in shapes:
        if shape.startswith("LIB~"):
            pkg = re.search(r'package`([^`]*)`', shape)
            pre = re.search(r'pre`([^`]*)`', shape)
            has_tp = 'T~P~' in shape
            has_tn = 'T~N~' in shape
            if not pkg or not pkg.group(1):
                print(f"ERROR: {pre.group(1) if pre else '?'} missing package")
                errors += 1
            if not has_tp:
                print(f"ERROR: {pre.group(1) if pre else '?'} missing T~P~ (designator label)")
                errors += 1

    # 3. Summary
    lib_count = sum(1 for s in shapes if s.startswith("LIB~"))
    wire_count = sum(1 for s in shapes if s.startswith("W~"))
    flag_count = sum(1 for s in shapes if s.startswith("F~"))
    print(f"\n{lib_count} components, {wire_count} wires, {flag_count} flags")
    print(f"Validation: {errors} errors")
    return errors == 0
```

Run this on the output file. If there are grid errors, there's a bug in the
generator — do NOT deliver the file. Fix the generator first.

---

## Phase 4: Deliver and Guide Import

### Present the File

Give the user the generated schematic JSON file and clear import instructions.

### Import Instructions for the User

1. Open **EasyEDA Standard** (desktop or web)
2. Go to **File → Open → EasyEDA Source**
3. Select the generated `.json` file
4. The schematic will open with all components, flags, and stub wires placed

### CRITICAL POST-IMPORT STEP: Link Footprints

**This step is ESSENTIAL.** JSON import loads symbol shapes but does NOT fetch
footprint geometry from EasyEDA's server. Without this step, ALL components will
fail Footprint Verification (the PAD information column will be completely empty).

**Tell the user to do this immediately after import:**

1. Go to **Design → Update Components from Library**
2. Check the box: **"Check component latest version when open schematic"**
3. Click **Select All** (header checkbox in the component list)
4. Click **Update**
5. Click **OK** on the warning dialog about flipped/mirrored components

This fetches the latest symbol + footprint data from EasyEDA's server for every
component in one batch operation. Takes about 10 seconds.

**Why this is needed:** When you place a component from the EasyEDA library
manually, it auto-fetches the footprint. But JSON import skips that fetch entirely.
The UUIDs in the JSON are correct — EasyEDA just needs to be told to go get the
actual footprint geometry from its server.

### What the User Should Expect

- Components placed on a grid with designators and values visible
- Net flags (VCC, GND, signal names) connected via short stub wires
- The NETNAME:N naming convention showing connection counts
- Correct footprint UUIDs already embedded (if LCSC parts were used)

### What the User Needs to Do After Import

1. **Link footprints** — Run "Update from Library" as described above. This is
   the single most important post-import step.
2. **Verify footprints** — Design → Footprints Verification → Check Footprints.
   Should show 0 issues. If any part shows "Can't find footprint on server," that
   specific LCSC part has a broken/deprecated footprint on EasyEDA's server —
   replace it in the netlist with a working alternative and regenerate.
3. **Rearrange components** — the auto-grid layout is functional but not pretty.
   Move components into a logical arrangement for readability.
4. **Verify connections** — spot-check a few flags to confirm the net names match
   the circuit design.
5. **Add any components not on LCSC** — parts without LCSC numbers were skipped
   by the generator. Place them manually and wire them in.

---

## Troubleshooting

### "Components show P? instead of R1, C1, etc."
The T~P~ text sub-shapes are missing or malformed. The generator adds these
automatically — if they're not showing, check that the LIB entries contain
`T~P~...~{designator}~1~start~...~pinpart` sub-shapes.

### "Flags point the wrong direction"
Flag rotation should be 180° opposite to the pin extension direction. If a pin
extends right (rot=0), the flag at the end of the stub wire should point left
(rot=180) back toward the pin.

### "Wires don't follow when I move components"
Pin dot coordinates are probably off the 10px grid. Run the validation script
to check. Every coordinate in the schematic must be a multiple of 10.

### "Footprint not found on server during PCB conversion"
The component needs footprint linking. Use the easyeda-design-assistant skill's
Phase 4, or manually Shift+F in EasyEDA and search for the LCSC part number.

### "Part not found in EasyEDA API"
The LCSC number is wrong or the part has been discontinued. Search lcsc.com
for an alternative and update the netlist.

---

## Reference: Generator Script Location

The engine script and supporting files live in the project's `scripts/` directory:

- `scripts/generate_easyeda_schematic.py` — Main generator engine
- `scripts/easyeda_uuid_lookup.py` — UUID lookup utilities
- `scripts/patch_easyeda_json.py` — Post-generation patching
- `references/easyeda_json_format.md` — Format specification

## Reference: EasyEDA JSON Format Quick Reference

```
Wire:      W~x1 y1 x2 y2~#008800~1~0~none~ggeN~0
Junction:  J~x~y~2.5~#CC0000~ggeN~0
GND flag:  F~part_netLabel_gnD~x~y~rot~ggeN~~0^^x~y^^GND~#000000~lx~ly~...^^PL~...
VCC flag:  F~part_netLabel_VCC~x~y~rot~ggeN~~0^^x~y^^VCC~#000000~lx~ly~...^^PL~...
Net flag:  F~part_netLabel_netPort~x~y~rot~ggeN~~0^^x~y^^NAME~#0000FF~lx~ly~...^^PL~...
LIB:       LIB~x~y~c_para~rot~0~ggeID~uuid~puuid~0~~yes~yes~~~#@$shapes...
Text:      T~{N|P}~x~y~rot~#000080~Arial~~~~~comment~text~1~start~ggeID~0~pinpart
```

All coordinates MUST be multiples of 10.
