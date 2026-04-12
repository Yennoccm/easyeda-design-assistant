---
name: easyeda-design-assistant
description: >
  End-to-end EasyEDA Standard design assistant — from schematic design through part selection,
  footprint linking, and PCB preparation. Guides users through the full hardware design flow:
  circuit design, choosing ICs/MCUs first then matching passives, SMD vs through-hole decisions,
  LCSC vs DigiKey sourcing strategy, and the critical footprint linking step that makes EasyEDA
  actually resolve footprints during PCB conversion. Use this skill whenever the user mentions
  EasyEDA, designing a PCB, choosing electronic components, schematic design, footprint linking,
  LCSC parts, JLCPCB assembly, "footprints don't resolve", "can't find footprint on server",
  converting schematics to PCB, or any hardware/electronics design workflow. Also trigger when
  users ask about SMD vs through-hole, component sourcing, or going from a circuit idea to a
  physical board.
---

# EasyEDA Design Assistant

A soup-to-nuts guide for designing electronics in EasyEDA Standard — from circuit concept
through to a PCB-ready schematic with fully linked footprints.

## Decision Tree — Where Are You?

Ask the user where they are, then jump in at the right point:

```
"I have a circuit idea but haven't started the schematic"
  → Phase 1: Schematic Design

"I have a schematic but need to pick real parts"
  → Phase 2: Part Selection (start with ICs/complex parts)

"I have parts picked but footprints don't work in EasyEDA"
  → Phase 4: Footprint Linking (the technical fix)

"I'm ready to convert my schematic to PCB"
  → Phase 5: PCB Preparation

"My footprints say 'can't find on server'"
  → Phase 4, Section: Diagnosis & Fix
```

---

## Phase 1: Schematic Design

Help the user design their circuit in EasyEDA Standard. The key principle here is
**design the topology first, pick specific parts second**. Use generic symbols (capacitor,
resistor, IC block) with approximate values, then refine in Phase 2.

### Design Order That Works

1. **Start with the core IC/module** — the MCU, radio chip, sensor, or whatever drives the
   design. Everything else flows from its requirements.
2. **Add power supply** — voltage regulators, decoupling, power distribution.
   The IC datasheets will specify required bypass caps, voltage ranges, etc.
3. **Add supporting passives** — pull-ups, bias resistors, coupling caps, filters.
   Again, driven by the IC datasheet recommendations.
4. **Add connectors, switches, indicators** — the physical interface.
5. **Add protection** — ESD, reverse polarity, fuses if needed.

### Schematic Best Practices for EasyEDA

- Use **hierarchical labels** and **net names** rather than running wires across the whole sheet
- Group related circuits into logical blocks with text labels
- Put pin numbers on IC symbols even in the draft phase — they matter for footprint linking later
- Add a BOM table or notes section on the schematic for reference

---

## Phase 2: Part Selection

This is where the schematic gets real. The critical insight: **pick complex parts first,
then choose passives to match.**

### Step 1: Choose Your Core ICs

These drive everything else:
- MCU / processor
- Radio / wireless module
- Sensor ICs
- Specialty ICs (mixers, amplifiers, converters)

For each IC, capture: manufacturer part number, package type, key specs, datasheet link.

### Step 2: The SMD vs Through-Hole Decision

This affects every subsequent part choice. Help the user decide:

**Choose Through-Hole (TH) if:**
- Hand-soldering a prototype
- Using breadboard-compatible parts
- Need to swap components during development
- Working with high-power components (large caps, power resistors)
- Teaching or learning (easier to inspect and rework)

**Choose SMD if:**
- Using JLCPCB or other assembly service
- Need small board size
- High-frequency design (shorter traces matter)
- Production run (faster, cheaper assembly)
- Most modern ICs are SMD-only anyway

**Mixed approach** (common and fine):
- SMD for ICs that only come in SMD packages
- TH for connectors, switches, through-hole-only parts
- Choose TH or SMD for passives based on above criteria

### Step 3: The Sourcing Decision

**LCSC-first (JLCPCB assembly flow):**
- Search LCSC directly for parts
- Prefer "Basic" parts (cheaper assembly fee, ~$0.001/joint vs ~$0.007)
- "Extended" parts work but add cost
- EasyEDA has native LCSC integration — searching by LCSC part number in the library
  gives you fully linked components with footprints

**DigiKey-first (US prototyping / hand-assembly):**
- Better datasheets, wider selection, faster US shipping
- After selecting DigiKey parts, cross-reference to LCSC numbers for EasyEDA footprint linking
- Some DigiKey parts won't have LCSC equivalents — those need manual footprint assignment

**The bridge between them:** What matters for EasyEDA is the **LCSC part number**.
Even if you're buying from DigiKey, you need the LCSC number to get the footprint UUID
from EasyEDA's API. Find a part on LCSC with the same footprint if the exact part isn't there.

### Step 4: Choose Passives to Match

Now that you know your ICs, package style, and sourcing strategy:

- **Capacitors**: Match voltage rating to your rails. Use values from IC datasheets for
  bypass/decoupling. For TH, radial MLCC or film caps are typical.
- **Resistors**: Standard 1% metal film for TH, 0402/0603/0805 for SMD.
  Values driven by IC requirements (pull-ups, voltage dividers, current limiting).
- **Inductors**: If needed for filters or switching regulators, size matters —
  check current rating and DCR.

### Step 5: Build the Parts Map

Create a comprehensive mapping:

```
| Designator | Value  | MFR Part           | DigiKey PN        | LCSC     | Package                        |
|------------|--------|--------------------|-------------------|----------|--------------------------------|
| U1         | SA612AN| SA612AN/01,112     | 568-SA612AN-ND    | C7236    | DIP-8_L9.6-W6.4-P2.54         |
| C1         | 100pF  | FG18C0G1H101JNT06  | 445-173170-1-ND   | C1620078 | CAP-TH_L4.0-W2.5-P2.50-D0.5-A |
```

---

## Phase 3: LCSC UUID Lookup

For each LCSC part number, fetch the EasyEDA component UUID data. This is needed for
footprint linking in Phase 4.

### Using the Bundled Script

Run `scripts/easyeda_uuid_lookup.py`:

```bash
python scripts/easyeda_uuid_lookup.py C1620078 C1620174 C7236
```

Output (JSON):
```json
{
  "C1620078": {
    "uuid": "4be8f647c5ce4d118db7e8f5a2b01fa3",
    "puuid": "f5f8fd4f693946708ecf1aabd745c3e6",
    "pdatastrid": "b8be95a59430446f94762730ae02f6cd",
    "package": "CAP-TH_L4.0-W2.5-P2.50-D0.5-A"
  }
}
```

The three critical values:
- `uuid` — identifies the schematic symbol in EasyEDA's library
- `puuid` — identifies the footprint (package) — **the essential one**
- `pdatastrid` — secondary package identifier

### When the API Returns Nothing

Some parts don't exist in EasyEDA's library. Strategy:
1. Find a **sibling part** with the same footprint (different value, same package)
2. Search LCSC by footprint name to find any part that uses it
3. Flag for manual assignment via the Footprint Manager (Phase 4, Section 5)

---

## Phase 4: Footprint Linking — The Core Technical Fix

This is the critical phase that makes everything work. Read `references/easyeda_json_format.md`
for the full JSON format specification.

### The Key Insight

EasyEDA's JSON import (File → Open → EasyEDA Source) loads component symbol shapes
from the file but does **NOT** auto-fetch footprint geometry from the server. Even
with correct UUIDs in the LIB header and c_para, the Footprint Manager shows empty
PAD information for every component, and pin-to-pad verification fails across the board.

**The fix is simple:** After importing the JSON, run "Update from Library."

### Method A: Update from Library (Recommended — Works Reliably)

After importing the schematic JSON:

1. Go to **Design → Update Components from Library**
2. Check the box: **"Check component latest version when open schematic"**
3. Click the **header checkbox** to select all components in the list
4. **CRITICAL: Check ONLY the "Footprint" (or "Package") column checkbox.**
   Do NOT check the "Symbol" column. If you update the symbol, EasyEDA will
   replace your schematic symbols with PCB footprint graphics (black rectangles)
   for any part whose library entry uses the footprint as its primary shape.
5. Click **Update**
6. Click **OK** on the warning dialog about flipped/mirrored components

This forces EasyEDA to fetch the footprint data from its server for every
component in one batch operation (~10 seconds), without overwriting the
schematic symbol shapes that the generator created.

**Why this works:** When you place a component manually from the library, EasyEDA
auto-fetches the footprint. JSON import skips that fetch. "Update from Library"
triggers the same server-side fetch for all components at once.

**⚠ WARNING:** Checking "Select All" columns (or the symbol column specifically)
will overwrite schematic symbols. Many LCSC parts store the PCB footprint as
their primary library representation, so an unrestricted update replaces your
schematic view with footprint graphics. Only update the Footprint/Package column.

### Method B: Pre-Import Validation (Catches Broken Parts Early)

Run `scripts/validate_footprints.py` BEFORE generating the schematic:

```bash
python scripts/validate_footprints.py --netlist netlist.json
```

This checks every LCSC part's footprint against EasyEDA's API server. Parts with
broken or deprecated footprints (like C1808 whose C0805 footprint was removed from
the server) are flagged so you can swap them before importing.

### Methods That Do NOT Work (Documented for Posterity)

**Browser JavaScript API (`callCommand`):**
Commands like `updatePackageUuid`, `updatePackageAndPin`, `fixedJsonCache` crash
on JSON-imported schematics because JSON import doesn't initialize the internal
data structures these commands depend on. Errors include:
- "Cannot set properties of undefined (setting 'hasIdFlag')"
- "Cannot read properties of undefined (reading 'pin')"

These commands may work on schematics created natively in EasyEDA (as was the case
with the SA612 project), but they are NOT reliable for JSON-imported schematics.
See `scripts/post_import_fix.js` for full documentation of what was tried.

**DOM attribute patching via JavaScript:**
Setting `puuid`/`uuid` attributes directly on `<g>` elements updates the DOM but
does not trigger the footprint geometry fetch. The attributes are correct but the
engine still has no footprint data to work with.

### Verification

1. Import JSON (File → Open → EasyEDA Source)
2. Run "Update from Library" (Method A above)
3. Design → Footprints Verification → Check Footprints
   - All green = done
   - "Can't find footprint on server" = that LCSC part has a broken footprint.
     Replace it in the netlist and regenerate.
4. Design → Convert Schematic to PCB

### Footprint Manager (for individual problem parts)

If a specific component fails after "Update from Library":

1. In the Footprint Verification dialog, find the red component
2. Right-click the component in the schematic → Properties
3. Click the footprint field → search for a valid alternative
4. Or: replace the LCSC part number in the netlist and regenerate

---

## Phase 4B: Schematic Verification (Multi-Pass)

After footprints are linked but BEFORE converting to PCB, verify the schematic itself.
This is where the most common and costly errors hide — net connection mistakes, wrong
component values, missing grounds, analog/digital ground conflicts. These errors are
trivial to fix in the schematic but painful to debug on a physical board.

The same iterative approach as circuit design verification: keep running passes until
2 consecutive passes find zero issues.

### Pass 1: Net-by-Net Connectivity Audit

Open the schematic and trace every net from source to destination:

**Power nets:**
- Trace VCC from the supply to every IC power pin. Is every IC actually connected?
  (A net label that's one character off — "VCC" vs "Vcc" vs "VCC1" — creates a
  disconnected net that looks connected. EasyEDA is case-sensitive on net names.)
- Trace GND from every IC ground pin back to the supply ground. Every single one.
- If the design has multiple voltage rails (3.3V, 5V, 12V), verify each IC is on
  the correct rail. A 3.3V IC on the 5V rail will burn.

**Signal nets:**
- For every signal connection in the circuit design, verify the corresponding wire
  or net label exists in the schematic. Don't assume — check each one.
- Look for "almost connected" wires — two wires that visually touch but aren't
  electrically joined (no junction dot in EasyEDA). This is the #1 schematic entry error.
- Check that net labels match exactly between sheets (if using multi-sheet schematics).

**Ground topology:**
- **Analog and digital grounds must be separate nets** that connect at ONE point
  (usually at the power supply). If your design has both analog circuits (op-amps,
  ADCs, sensors) and digital circuits (MCU, encoders, displays), they need separate
  ground planes that star-connect at the supply.
- In EasyEDA, this means using different net names: "AGND" and "DGND" (not both "GND").
- The single connection point should be a 0Ω resistor or ferrite bead between AGND
  and DGND, placed near the power supply.
- If the circuit designer specified "keep analog and digital separate" but the
  schematic has one GND net for everything, this MUST be fixed before PCB conversion.

### Pass 2: Component Value Cross-Check

Compare every component value in the schematic against the circuit design document
(the output from the circuit-designer skill or the user's reference):

**Resistors — check each one:**
- Is the value in the schematic exactly what the circuit design specifies?
  (10kΩ vs 10Ω vs 100kΩ — one digit off is a different circuit)
- Are the units correct? (EasyEDA uses "10k" not "10000" — verify the display)
- For voltage dividers: recalculate the output voltage with the schematic values.
  Does it match the intended voltage?

**Capacitors — check each one:**
- Value: 100pF vs 100nF vs 100µF are 1000× apart. Verify units carefully.
- Voltage rating: Is it in the component properties? A 6.3V cap on a 9V rail
  will fail, possibly violently.
- Electrolytic polarity: In the schematic, is the + pin connected to the more
  positive node? (Easy to flip during schematic entry.)

**ICs — check pin assignments:**
- Compare the schematic pin connections against the IC datasheet pinout.
  Not the circuit design document — the actual datasheet. Pin numbers sometimes
  differ between DIP and SOIC packages of the same IC.
- Verify pin 1 orientation. A flipped IC in the schematic means every pin is wrong.
- Are NC (no-connect) pins actually unconnected? Some "NC" pins are internally
  connected and must not be tied to anything.

**Designators:**
- Are they consistent? No duplicate designators (two components both called R1).
- Do they match the parts map? (R1 in the schematic should be the same R1 in the BOM.)

### Pass 3: EasyEDA-Specific Checks

These are errors unique to the EasyEDA editor that won't show up in a generic
schematic review:

- **Run ERC (Electrical Rules Check):** Design → Electrical Rules Check. Fix every
  error and warning. Don't ignore warnings — they often indicate real problems.
- **Check for unconnected pins:** ERC will flag these, but also visually scan for
  pins that should be connected but aren't flagged (e.g., a pin connected to a
  net label that doesn't go anywhere).
- **Verify component properties:** Click each IC and check that the properties
  dialog shows the correct package, LCSC part number, and puuid. If any of these
  are missing or wrong, the footprint linking will fail silently.
- **Check for overlapping wires:** Two wires on top of each other look like one
  wire but may create unintended connections or short circuits.
- **Verify hierarchical labels** (if using multi-sheet): Each label must have a
  matching label on the connected sheet with the exact same name.

### Pass 4: Power Integrity Check

Focus exclusively on the power distribution:

- **Decoupling cap placement:** For every IC, verify there is a decoupling cap
  (100nF minimum) connected between its VCC and GND pins in the schematic.
  Not "near" — directly connected to those specific pins/nets.
- **Bulk capacitors:** Are there bulk caps (10µF+) at the power supply output
  and at the input of each voltage regulator?
- **Current paths:** Trace the current path for the highest-current component
  (motor, relay, transmitter, LED array). Does that current flow through any
  thin traces or shared ground paths that could cause voltage drops?
- **Regulator input voltage:** Is Vin to each regulator within its operating range
  under worst-case conditions (battery almost dead, max load)?
- **Power sequencing:** If there are multiple regulators, does the enable/shutdown
  sequence matter? Some ICs require their I/O voltage rail before their core rail.

### Verification Output

Same format as the circuit-designer verification:

```
## Schematic Verification Pass [N]

### Issues Found: [count]

1. **[CRITICAL]** C3 — Value shows 100nF in schematic but circuit design specifies 100pF
   - Fix: Change C3 value to 100pF in component properties
   - Impact: 1000× wrong capacitance would completely change filter response

2. **[CRITICAL]** U2 GND pin — Connected to VCC net instead of GND
   - Fix: Rewire pin 4 of U2 to GND net
   - Impact: Would destroy IC on power-up

3. **[WARNING]** AGND and DGND — Both labeled "GND" in schematic
   - Fix: Rename analog ground net to "AGND", add 0Ω resistor at star point
   - Impact: Noise coupling from digital switching into analog signal path

### Status: [CLEAN / issues found — fix and re-verify]
```

**Do not proceed to PCB conversion until 2 consecutive clean passes.**

---

## Phase 5: PCB Preparation

Once all footprints resolve AND the schematic has passed verification, PCB setup:

### Board Setup
- **2-layer** is fine for most hobby/prototype designs
- **4-layer** for high-speed digital, dense SMD, or RF circuits
- Set board outline in EasyEDA before placing components

### Design Rules (DRC)
- **Trace width**: 10mil minimum for signal, 20-30mil for power, wider for high current
- **Clearance**: 6-8mil minimum (JLCPCB supports 5mil but leave margin)
- **Via size**: 0.3mm drill / 0.6mm annular ring is a safe default
- **For JLCPCB**: check their current capabilities page — they update frequently

### Layout Tips
- Place ICs first, then their bypass caps as close as possible
- Route power and ground first
- Keep analog and digital sections separated
- Use ground pours on both layers

### PCB Layout Verification

After routing, before generating Gerbers:

**Ground integrity:**
- If the design has separate AGND/DGND, verify the ground pours are actually
  separate on the PCB. Check that the single connection point (0Ω resistor or
  ferrite bead) is the only bridge between them.
- Look for ground loops — current paths that form a loop through the ground plane.
  Especially common when a signal trace crosses a split in the ground plane,
  forcing return current to detour around the split.
- Verify that high-current ground returns (relay, motor, buzzer) don't share
  a ground trace with sensitive analog signals.

**Decoupling cap proximity:**
- Every IC's decoupling cap should be within 5mm of its power pins, connected
  with short, wide traces. If EasyEDA placed the cap on the other side of the
  board, move it. A decoupling cap 2 inches from the IC it's supposed to decouple
  is doing almost nothing.

**Trace width audit:**
- Signal traces: 10mil minimum (6mil absolute minimum for JLCPCB)
- Power traces: 20mil+ (calculate based on current: 1A needs ~30mil on outer layer)
- Ground traces (if not using pour): same width as power traces
- High-current paths (relay coils, motor drivers): 40mil+ or use polygon fills

**DRC must pass clean.** Run Design → Design Rule Check and fix every error.
Warnings about clearance or trace width should be investigated, not ignored.

---

## Common Pitfalls

1. **puuid in c_para but not as DOM attribute** — The #1 footprint linking mistake.
   Properties dialog shows the right package but PCB conversion fails.

2. **Picking passives before ICs** — IC datasheets specify required caps, resistors, etc.
   Pick the IC first, then match passives to its requirements.

3. **Parts not in LCSC library** — Some parts (especially niche TH components) don't have
   EasyEDA library entries. Find sibling parts or use the Footprint Manager.

4. **Stale editor cache** — Footprints that work in one session may break after reopening.
   The fix must be in the JSON, not just the live DOM.

5. **Mixing LCSC Basic and Extended** — Extended parts add assembly cost at JLCPCB.
   If cost matters, prefer Basic parts where possible.

6. **Rate limiting** — EasyEDA API throttles after ~10-12 rapid requests. Add delays.