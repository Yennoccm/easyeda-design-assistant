# EasyEDA Standard JSON Format Reference

This document describes the internal JSON format used by EasyEDA Standard Edition
for schematic files. Understanding this format is essential for programmatic
footprint linking and component patching.

## Top-Level Structure

An EasyEDA Standard schematic JSON file uses a **nested** structure. The shape
array lives inside `schematics[0].dataStr`, NOT at the top level:

```json
{
  "editorVersion": "6.5.54",
  "docType": "5",
  "title": "My Schematic",
  "description": "",
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
          "newgId": true,
          "c_para": { "Prefix Start": "1" },
          "c_spiceCmd": "null",
          "hasIdFlag": true,
          "x": "0",
          "y": "0",
          "importFlag": 0,
          "transformList": ""
        },
        "canvas": "CA~1000~1000~#FFFFFF~yes~#CCCCCC~5~1000~1000~line~5~pixel~5~0~0",
        "shape": [
          "LIB~...component data...",
          "W~...wire data...",
          "F~...net flag data...",
          "T~...text data..."
        ],
        "BBox": { "x": 0, "y": 0, "width": 2000, "height": 1600 },
        "colors": {}
      }
    }
  ]
}
```

**CRITICAL**: The root `docType` is `"5"` (project). Each schematic sheet
inside `schematics[]` has `docType: "1"`.

The `shape` array inside `dataStr` contains all schematic elements as
tilde-delimited strings.


## Shape Types

Each string in the `shape` array starts with a type prefix:

| Prefix | Type             | Description                                    |
|--------|------------------|------------------------------------------------|
| LIB    | Library component| IC, resistor, cap, etc. — the main one we patch|
| W      | Wire             | Electrical connection between pins              |
| F      | Net flag         | Named net flag (VCC, GND, signal names)        |
| T      | Text annotation  | Free text on schematic                          |
| J      | Junction         | Wire junction dot                               |
| B      | Bus              | Bus line                                        |
| P      | Pin              | Standalone pin (rare in component context)      |
| PL     | Polyline         | Decorative polyline                             |
| R      | Rectangle        | Decorative rectangle                            |
| E      | Ellipse          | Decorative ellipse                              |
| PI     | Image            | Embedded image                                  |

**NOTE**: EasyEDA uses `F~` for net flags, NOT `N~`. The `N~` prefix does not
exist in EasyEDA Standard schematic JSON.


## LIB Entry Format (Components)

LIB entries are the most complex and the ones we need to patch for footprint
linking. The full format has 16 tilde-delimited fields:

```
LIB~{x}~{y}~{c_para}~{rotation}~0~{ggeID}~{puuid}~{uuid}~0~{hash1}~yes~yes~{hash2}~{timestamp}~{hash3}#@${sub_shapes}
```

### Field breakdown (16 fields):

- Field 0: `LIB` — type prefix
- Field 1: `x` — X position on schematic canvas
- Field 2: `y` — Y position on schematic canvas
- Field 3: `c_para` — Backtick-delimited key-value string (see below)
- Field 4: `rotation` — Component rotation (0, 90, 180, 270)
- Field 5: `0` — Always 0
- Field 6: `ggeID` — Internal element ID (e.g., `gge1234`)
- Field 7: `puuid` — **Footprint UUID** (from API `head.puuid`) — **CRITICAL for PCB conversion**
- Field 8: `uuid` — **Symbol UUID** (from API `result.uuid`)
- Field 9: `0` — Always 0
- Field 10: `hash1` — Internal hash (can be empty)
- Field 11: `yes` — Flag
- Field 12: `yes` — Flag
- Field 13: `hash2` — Internal hash (can be empty)
- Field 14: `timestamp` — Unix timestamp (can be empty)
- Field 15: `hash3` — Internal hash (can be empty)
- `#@$` — Separator between the LIB header and its sub-shapes
- `sub_shapes` — The component's graphical elements (pins, lines, arcs, text)

**CRITICAL**: puuid and uuid MUST be in fields 7 and 8 as separate tilde-delimited
values. Putting them only inside the c_para string is NOT sufficient for footprint
resolution.


## The c_para String

This is the heart of component metadata. It uses backtick (`) delimiters
to store key-value pairs:

```
package`DIP-8_L9.6-W6.4-P2.54`pre`U1`Manufacturer`NXP`ManufacturerPart`SA612AN`Supplier`LCSC`SupplierPart`C7236`uuid`41b2f5848a1b0d1b7eec0172d6bcc450`puuid`e0c08598662c4de4af4df4ac354c8345`
```

### Standard c_para fields:

| Field             | Example                              | Purpose                                   |
|-------------------|--------------------------------------|-------------------------------------------|
| package           | DIP-8_L9.6-W6.4-P2.54               | Footprint name                            |
| pre               | U1                                   | Designator / reference prefix             |
| nameAlias         | SA612AN                              | Display name alias                        |
| name              |                                      | Component name (often empty)              |
| Value             | 100pF                                | Component value                           |
| uuid              | 41b2f5848a1b0d1b7eec0172d6bcc450    | Schematic symbol UUID                     |
| puuid             | e0c08598662c4de4af4df4ac354c8345    | **Footprint (package) UUID — CRITICAL**   |
| Supplier          | LCSC                                 | Parts supplier                            |
| SupplierPart      | C7236                                | Supplier part number                      |
| LcscPart          | C7236                                | LCSC part number specifically             |
| Manufacturer      | NXP Semiconductors                   | Manufacturer name                         |
| ManufacturerPart  | SA612AN                              | Manufacturer part number                  |
| Description       | Double-balanced mixer, DIP-8         | Part description                          |

### Parsing c_para in Python:

```python
def parse_cpara(blob: str) -> dict:
    tokens = blob.split("`")
    result = {}
    for i in range(0, len(tokens) - 1, 2):
        if tokens[i]:
            result[tokens[i]] = tokens[i + 1]
    return result
```


## The DOM Attribute Mapping (WARNING: Names Are Misleading)

When EasyEDA Standard renders a schematic JSON into its SVG editor, each LIB
entry becomes a `<g>` (group) element in the SVG DOM. The tilde-delimited
fields map to DOM attributes as follows:

```
LIB field 7  →  DOM attribute named "puuid"  →  contains FOOTPRINT puuid
LIB field 8  →  DOM attribute named "uuid"   →  contains SYMBOL uuid
```

**NOTE:** The DOM attribute names happen to match the actual content here:
field 7 → DOM "puuid" → contains the footprint puuid from API `head.puuid`
field 8 → DOM "uuid" → contains the symbol uuid from API `result.uuid`

This was confirmed empirically by comparing v7 (working) against v8 (broken,
fields accidentally swapped during refactoring). All 43 components matched
when puuid was in field 7 and uuid was in field 8.

```html
<g c_para="package`DIP-8`pre`U1`..."
   puuid="2b0d9dd390ab4a51..."   <-- populated from LIB field 7 (FOOTPRINT puuid)
   uuid="b19c63845b9c45a3..."    <-- populated from LIB field 8 (SYMBOL uuid)
   id="gge1234"
   class="component">
</g>
```

### The PCB engine resolves footprints using the value in field 7 (footprint puuid).

If field 7 is empty or contains the wrong UUID, pin-to-pad verification fails
and "Update from Library" will show PCB footprint graphics instead of
schematic symbols.

### The Real Fix: Get the JSON right at generation time

The correct approach is to put the right UUIDs in the right tilde fields when
generating the JSON. No browser JavaScript is needed if the JSON is correct:

```python
# CORRECT — puuid (footprint) in field 7, uuid (symbol) in field 8:
lib_header = f"LIB~{x}~{y}~{cpara}~0~0~{gge}~{puuid}~{uuid}~0~~yes~yes~~~"

# WRONG — swapping them causes Update from Library to break:
lib_header = f"LIB~{x}~{y}~{cpara}~0~0~{gge}~{uuid}~{puuid}~0~~yes~yes~~~"
```

Get uuid and puuid from the EasyEDA API:
```
GET https://easyeda.com/api/products/{LCSC_PART}/components
→ result.dataStr.head.puuid = footprint UUID → goes in field 7
→ result.uuid = schematic symbol UUID  → goes in field 8
```

### Legacy: Browser JavaScript Diagnostic (for debugging only)

The browser JavaScript fix below was used during debugging to diagnose the
field mapping. It is NOT needed if the JSON is generated correctly. Retained
here as a diagnostic reference:

```javascript
// Run in EasyEDA editor console to inspect DOM attribute mapping:
const iframe = document.querySelector('iframe');
const iframeDoc = iframe.contentDocument;
const svgEl = iframeDoc.querySelector('#svgcontent');
svgEl.querySelectorAll('g[c_para]').forEach(g => {
    const pre = (g.getAttribute('c_para') || '').match(/pre`([^`]+)/);
    console.log(pre?.[1], 'puuid_dom=', g.getAttribute('puuid'),
                'uuid_dom=', g.getAttribute('uuid'));
});
```


## Sub-Shape Formats

After the `#@$` separator, a LIB entry contains its graphical sub-elements,
also delimited by `#@$`:

### Pin (P prefix in sub-shapes):
```
P~{x}~{y}~{rotation}~{pin_number}~{pin_name}~{length}~{type}~...
```
Pin types: input (I), output (O), bidirectional (B), passive (P), etc.

### Line (PL prefix):
```
PL~{x1}~{y1}~{x2}~{y2}~...~{stroke_width}~{color}
```

### Text (T prefix in sub-shapes):
```
T~{x}~{y}~{rotation}~{text}~{font_size}~{color}
```

### Arc (A prefix):
```
A~{cx}~{cy}~{rx}~{ry}~{start_angle}~{end_angle}~...
```


## Net Flag Format (F~ entries)

EasyEDA uses `F~` entries for net flags (NOT `N~`). Flags use `^^` to separate
multiple sections within a single shape string.

### General format:
```
F~{part_type}~{x}~{y}~{rotation}~{ggeID}~~0
  ^^{x}~{y}
  ^^{label}~{color}~{labelX}~{labelY}~{labelRot}~{align}~1~{font}~{size}~{flag_ggeID}
  ^^PL~{polyline1}~{color}~1~0~transparent~{ggeID}~0
  ^^PL~{polyline2}~...
```

### Flag part types:
- `part_netLabel_netPort` — Custom signal net (blue #0000FF, pentagon arrow shape)
- `part_netLabel_gnD` — Ground net (black #000000, decreasing-width bars)
- `part_netLabel_VCC` — Power rail (black #000000, horizontal bar symbol)

### netPort flag (custom signals):
Uses a pentagon/arrow polyline shape that points toward the pin connection.
```
F~part_netLabel_netPort~240~-260~0~gge32313~~0
  ^^240~-260
  ^^VAA~#0000FF~196.77~-255~0~~1~Times New Roman~8pt~flag_gge511
  ^^PL~240 -260 235 -255 220 -255 220 -265 235 -265 240 -260~#0000FF~1~0~transparent~gge32325~0
```

### GND flag:
Has 5 PL sections: 1 stem line + 4 horizontal bars of decreasing width.
```
F~part_netLabel_gnD~400~-225~90~gge31923~~0
  ^^400~-225
  ^^GND~#000000~416.5~-220.92~0~start~1~Times New Roman~9pt~flag_gge496
  ^^PL~410 -225 400 -225~#000000~1~0~transparent~gge31935~0       (stem, 10px)
  ^^PL~410 -216 410 -234~#000000~1~0~transparent~gge31938~0       (bar1, ±9)
  ^^PL~412 -219 412 -231~#000000~1~0~transparent~gge31941~0       (bar2, ±6)
  ^^PL~414 -222 414 -228~#000000~1~0~transparent~gge31944~0       (bar3, ±3)
  ^^PL~416 -224 416 -226~#000000~1~0~transparent~gge31947~0       (bar4, ±1)
```

### VCC flag:
Has 2 PL sections: 1 stem line + 1 horizontal bar.
```
F~part_netLabel_VCC~220~-225~90~gge32353~~0
  ^^220~-225
  ^^VCC~#000000~184.81~-221~0~start~1~Times New Roman~9pt~flag_gge517
  ^^PL~210 -225 220 -225~#000000~1~0~none~gge32365~0              (stem, 10px)
  ^^PL~210 -220 210 -230~#000000~1~0~transparent~gge32368~0       (bar, ±5)
```

### NETNAME:N Convention:
When generating schematics programmatically, use flag labels with a count suffix:
- 2 endpoints on a net: label = `NETNAME` (e.g., `SIG_A`)
- 3+ endpoints on a net: label = `NETNAME:N` (e.g., `VCC:3`, `GND:5`)
This makes connection counts verifiable at a glance.


## EasyEDA API

### Component lookup by LCSC number:
```
GET https://easyeda.com/api/products/{LCSC_PART}/components
```

Response:
```json
{
    "success": true,
    "result": {
        "uuid": "41b2f5848a1b0d1b7eec0172d6bcc450",
        "title": "SA612AN",
        "docType": 1,
        "dataStr": {
            "head": {
                "docType": "1",
                "puuid": "e0c08598662c4de4af4df4ac354c8345",
                "c_para": { ... }
            },
            "shape": [ ... ]
        }
    }
}
```

- The API returns a **single object** (not an array) for standard parts
- `result.uuid` = Schematic symbol UUID → goes in LIB field 8
- `result.dataStr.head.puuid` = Footprint UUID → goes in LIB field 7

### Rate limiting:
- ~10-12 requests before throttling
- Add 1-second delays between requests
- Throttled responses return HTML instead of JSON


## Footprint Resolution Flow

When you click Design → Convert Schematic to PCB, EasyEDA:

1. Iterates over all `<g>` elements with component data
2. Reads the `puuid` **DOM attribute** (not c_para string)
3. Fetches the footprint data from EasyEDA's server using that puuid
4. If puuid is empty or invalid → "Can't find footprint on server" error

### Verification checklist:
- [ ] Each component has `puuid` in its c_para string (data persistence)
- [ ] Each component's `<g>` element has `puuid` as a DOM attribute (engine reads this)
- [ ] The puuid value matches a real footprint in EasyEDA's library
- [ ] Footprint Verification dialog shows all green


## gge IDs — Global Uniqueness Requirement

Every element in an EasyEDA schematic has a `gge{N}` identifier (e.g., `gge5`,
`gge1234`). These appear in:
- LIB header field 6 (the component's own ID)
- Every sub-shape inside a LIB entry (pins, lines, text, arcs)
- Wires, net flags, junctions, and all other top-level shapes

**CRITICAL RULE: Every gge ID must be globally unique across the entire schematic.**

A hand-drawn SA612 schematic with 344 gge references has zero duplicates.
A programmatically generated schematic that reuses gge IDs will cause:
- Wrong element selected when clicking in the editor
- Copy/paste and undo/redo corruption
- Silent data loss during PCB conversion

When generating schematics programmatically, use a single global counter:

```python
class GgeCounter:
    def __init__(self, start=1):
        self._n = start
    def next(self):
        gid = f"gge{self._n}"
        self._n += 1
        return gid

# One instance shared across ALL components, wires, flags, etc.
gge = GgeCounter(start=1)
```

Never reset the counter between components. Never derive gge IDs from pin numbers
or component indices — always increment.


## Pin Dot Coordinates and Wire Connections

This is critical for programmatic schematic generation. EasyEDA uses **absolute
canvas coordinates** for pin dots — they are NOT relative to the component origin.

### How pin dots work:

A pin inside a LIB component is defined with its pin dot at an absolute position:

```
P~show~0~1~505~-485~0~gge1234^^505~-485^^M 505 -485 h -20~...
```

Breaking this down:
- `505~-485` — The pin dot position (absolute canvas coordinates)
- `^^505~-485` — The connection point (same as pin dot)
- `M 505 -485 h -20` — SVG path: starts at pin dot, draws 20px stub leftward into the component body

If the component origin is at (465, -485), then this pin is offset 40px to the right of the origin.

### Wire connection rule:

Wire endpoints must land **exactly** on pin dot coordinates. Zero tolerance.

```
W~505 -485 510 -485~#008800~1~0~none~gge5678
```

This wire starts at (505, -485) — exactly matching the pin dot above — and extends
right to (510, -485). If the wire endpoint is off by even 1 pixel, EasyEDA will
NOT recognize the electrical connection.

### Coordinate math for programmatic generation:

When placing components programmatically, the workflow is:

1. **Decide component position** (x, y) on the canvas
2. **Calculate every pin dot** from that position using fixed offsets:
   - Standard pin spacing: 10px or 20px (matching the grid)
   - DIP-8 example: pins are spaced 20px apart vertically, two columns
3. **Route wires** to the exact pin dot coordinates
4. **Route net flags** — the flag's connection point must also land exactly on
   a pin dot or wire endpoint

### DIP-8 pin dot example (component at 465, -485):

For an SA612AN at position (465, -485), typical pin dots:
```
Pin 1 (IN_A):  (445, -485)   <- left column, top
Pin 2 (IN_B):  (445, -505)   <- left column, 20px down
Pin 3 (GND):   (445, -525)   <- left column, 20px down
Pin 4 (OSC_B): (445, -545)   <- left column, bottom
Pin 5 (OSC_A): (485, -545)   <- right column, bottom
Pin 6 (VCC):   (485, -525)   <- right column, up
Pin 7 (OUT_A): (485, -505)   <- right column, up
Pin 8 (OUT_B): (485, -485)   <- right column, top
```

Left-side pins have stubs pointing left (h -20), right-side pins have stubs
pointing right (h 20). The pin stub is purely visual — the connection point
is the pin dot, not the end of the stub.

### The Pin Registry Pattern (recommended for code generation):

The critical failure mode in programmatic generation is calculating pin positions
twice independently — once when building the LIB string, once when routing wires.
Even a 1px rounding difference means no connection.

The solution is a pin registry: calculate the pin dot once, store it, and reuse
the same variable for both the pin definition and the wire endpoint.

```python
pin_registry = {}

def register_pin(name: str, x: int, y: int):
    """Register a pin dot position. name format: 'U1.1', 'C5.2'"""
    pin_registry[name] = (x, y)

def pin(name: str) -> tuple:
    """Look up a registered pin dot position."""
    return pin_registry[name]

# When creating U1 at body position (500, 180):
# Pin 1 is at body_x(500) - stub_length(30) = 470, body_y(180) + offset(20) = 200
register_pin("U1.1", 470, 200)

# The LIB string uses (470, 200) for the pin dot:
# P~show~0~1~470~200~0~gge10^^470~200^^M 470 200 h 30~#880000^^...

# Later, the wire uses the SAME variable:
# add_wire([pin("C1.2"), pin("U1.1")])
# → W~330 200 470 200~#008800~1~0~none~gge99
```

Both the pin dot and the wire endpoint come from the same stored value.
They literally cannot mismatch.

### What happens when you move or rotate:

When a component moves or rotates, ALL pin dot coordinates change. This means
every wire connected to that component must also update. For programmatic
generation, always:
- Place all components first
- Calculate final pin dot positions (register them once)
- Then generate all wires and net flags using the registry


## Common UUID Examples (Through-Hole)

For reference, here are UUIDs for common TH packages we've verified:

| LCSC     | Package                              | puuid                            |
|----------|--------------------------------------|----------------------------------|
| C1620078 | CAP-TH_L4.0-W2.5-P2.50-D0.5-A      | f5f8fd4f693946708ecf1aabd745c3e6 |
| C1620174 | CAP-TH_L4.0-W2.6-P5.00-D0.5        | c9b58eb0e1c444beba8e0926fb66a522 |
| C3692215 | CAP-TH_L4.0-W2.5-P2.50-D0.5        | 67c07ce1d70240ac8f57ff13691eecc0 |
| C7236    | DIP-8_L9.6-W6.4-P2.54               | e0c08598662c4de4af4df4ac354c8345 |
| C34846   | RES-ADJ-TH_3296W                    | 5e404972447a403ca43a83aeb15e254e |
| C723553  | RES-TH_BD2.4-L6.3-P10.30-D0.6      | 2915f1f0a54941d7b912decfe617b47f |
| C2441441 | RES-TH_BD2.3-L6.0-P10.00-D0.4      | 58f38f333e594cdeb10fc32d698c0f42 |
| C6471243 | CAP-ADJ-TH_3P-BD10.0                | 9647d5b15250442b94a8af1c5ab47341 |
| C1329796 | IND-TH_BD2.8-L7.0-P11.00-D0.5      | 3777d2c18d9f47f2af890fbb86442f0d |
| C3350065 | IND-TH_BD4.0-L9.5-P13.50-D0.8      | 31ce7c33f87e4d4fadb764413cb887b2 |
| C3272842 | TO-92-2_L4.6-W3.5-P2.54-L           | 7710b76cffae405985e50988941a4d9c |


---

# Lessons Learned — What Breaks JSON-Imported Schematics

These are hard-won lessons from debugging footprint failures in programmatically
generated EasyEDA schematics. Every single one of these caused real breakage
and hours of debugging. They are encoded in `generate_easyeda_schematic.py`
but documented here so the reasoning is never lost.

## The FOUR Things That Break Footprint Resolution

### 1. uuid/puuid Field Ordering (Field 7 vs Field 8) — RESOLVED

The LIB header has 16 tilde-delimited fields. Fields 7 and 8 carry the
footprint and symbol UUIDs:

```
Field 7 = puuid (FOOTPRINT UUID, from API: head.puuid)
Field 8 = uuid  (SYMBOL UUID, from API: result.uuid)
```

**STATUS: CONFIRMED by v7 (working) vs v8 (broken) comparison.**

During SPICE refactoring the fields were accidentally swapped (v8), which
caused "Update from Library" to replace schematic symbols with PCB footprint
graphics. Restoring the correct order (v9) fixed the issue — all 43
components' field 7/8 values matched v7 exactly.

**Code location:** `generate_easyeda_schematic.py` → `build_lib_entry()` →
LIB header uses `~{puuid}~{uuid}~`.

### 2. gge ID Collisions

Every element in an EasyEDA schematic — every LIB, pin, line, arc, text label,
wire, net flag — has a `gge{N}` identifier. These MUST be globally unique across
the ENTIRE schematic.

The problem: When you fetch a symbol from the EasyEDA API, the returned shapes
contain gge IDs like `gge26`, `gge27`, `rep2`, `rep3`. If you place two copies
of the same LCSC part (or even cache and reuse API results), ALL copies share
the same internal gge IDs. A hand-drawn schematic has zero duplicates. Our
first programmatic attempt had 29 duplicates. EasyEDA silently fails — footprint
resolution breaks, components become unselectable, or the editor corrupts.

**Code fix:** `generate_easyeda_schematic.py` → `_rename_gge_ids()` replaces
every `gge{N}`, `rep{N}` pattern in offset shapes with a globally unique ID
from a monotonic counter. Called inside the `build_lib_entry()` offset loop.

### 3. Missing c_para Metadata

The `c_para` backtick string in the LIB header needs to contain:
- `uuid` and `puuid` — for Properties dialog and BOM round-trip
- `LcscPart` — for JLCPCB BOM export
- `Supplier` and `Supplier Part` — for supplier linkage
- `package` — for footprint name display
- `Manufacturer` and `Manufacturer Part` — for BOM completeness

Without these, the component appears to work but BOM export is empty,
Properties dialog shows blanks, and JLCPCB ordering breaks.

**Code fix:** `generate_easyeda_schematic.py` → `build_cpara_string()` injects
all metadata from the API response plus the LCSC part number.

### 4. Footprint Geometry Not Fetched on JSON Import — RESOLVED

**This was the hardest bug to find.** Even with correct field 7/8 ordering,
unique gge IDs, and complete c_para metadata, ALL components fail Footprint
Verification after JSON import. The Footprint Manager shows completely EMPTY
PAD information for every component.

**Root cause:** EasyEDA's JSON import (File → Open → EasyEDA Source) loads
symbol shapes from the file but does NOT auto-fetch footprint geometry from
the server. When you place a component manually from the library, EasyEDA
fetches the footprint automatically. JSON import skips this step entirely.

**Fix:** After importing the JSON, go to:
  Design → Update Components from Library
  → Check the box: "Check component latest version when open schematic"
  → Select All rows → check ONLY the "Footprint/Package" column
  → Click "Update" → Click "OK" on the warning dialog

**⚠ Do NOT check the "Symbol" column.** Updating symbols replaces schematic
symbols with PCB footprint graphics (black rectangles) for many LCSC parts
whose library entry uses the footprint as the primary shape.

This forces EasyEDA to fetch footprint data from the server for every
component. After this step, Footprint Verification shows PAD info populated
and pin-to-pad matching works.

**What did NOT work:**
- `callCommand('updatePackageUuid', [puuid])` — no effect despite working
  on a different project (SA612)
- `callCommand('updateJsonCache')` — no effect
- Patching DOM `puuid` attributes via JavaScript — no effect
- These JavaScript approaches may work in some contexts but are unreliable.
  The "Update from Library" dialog is the supported, reliable method.


## The Correct Pipeline

```
1. Design circuit → netlist.json (components + nets + LCSC part numbers)

2. generate_easyeda_schematic.py:
   a. Fetch symbols from EasyEDA API (uuid, puuid, shapes, pins)
   b. Place components on grid
   c. Generate LIB entries with correct field 7/8 and unique gge IDs
   d. Generate wires + net flags for all net connections
   e. Place NC markers on unconnected pins
   f. Output schematic JSON

3. In EasyEDA: File → Open → EasyEDA Source → import JSON
   (Symbol shapes load, but footprint geometry is NOT fetched yet)

4. ESSENTIAL: Design → Update Components from Library
   → Check the box: "Check component latest version when open schematic"
   → Select All rows → check ONLY the "Footprint/Package" column
   → Do NOT check the "Symbol" column (overwrites schematic symbols!)
   → Click "Update" → Click "OK" on the warning dialog
   This fetches footprint geometry from the server for ALL components.
   Without this step, Footprint Verification fails for every component
   because the PAD information is empty.

5. Design → Footprints Verification → Check Footprints
   (Should show 0 issues, or only parts with server-side problems)

6. Design → Convert Schematic to PCB
   (All footprints resolve, PCB layout ready)
```

**Why step 4 is needed:** EasyEDA's JSON import loads component symbol shapes
from the file but does NOT auto-fetch footprint geometry from the server.
When you place a component from the library manually, EasyEDA fetches the
footprint automatically. But JSON import skips that step. "Update from Library"
forces the same server fetch for all components at once.

### Two Paths Through the Maze:

**Path 1 — Manual (reliable, ~10 seconds):**
Steps 3-6 above. Import JSON, Update from Library, verify, convert to PCB.

**Path 2 — Pre-import validation (catches broken parts early):**
Run `python scripts/validate_footprints.py --netlist netlist.json` BEFORE
generating the schematic. This checks every LCSC part's footprint against
the EasyEDA API server. Parts with broken/missing footprints (like C1808
whose C0805 footprint was removed from the server) are flagged so you can
swap them out before wasting time on import.

**Why the JavaScript API is NOT a reliable path:**
The internal `callCommand` hooks (`updatePackageUuid`, `updatePackageAndPin`,
`fixedJsonCache`, etc.) crash on JSON-imported schematics because JSON import
doesn't initialize the internal data structures these commands depend on.
The "Update from Library" dialog uses a different, properly-initialized code
path. See `scripts/post_import_fix.js` for full documentation of what was
tried and why it failed.


## Pin Number Gotchas

### ESP32-WROOM-32E: GPIO numbers ≠ physical pin numbers

The ESP32 module has 39 physical pins (1-39). GPIO numbers (GPIO0, GPIO21, etc.)
do NOT correspond to physical pin numbers. Example:
- GPIO21 (I2C SDA) = physical pin 33 (NOT pin 21)
- GPIO22 (I2C SCL) = physical pin 36 (NOT pin 22)
- GPIO0 (BOOT)     = physical pin 25 (NOT pin 0)

Always cross-reference the LCSC datasheet or EasyEDA symbol to get PHYSICAL
pin numbers. The netlist must use physical pins (U2.33) not GPIO numbers (U2.21).

### AMS1117: Pin numbering varies by package

The SOT-223 package for AMS1117-3.3 has 4 pins:
- Pin 1 = GND (NOT VIN)
- Pin 2 = VOUT (NOT GND)
- Pin 3 = VIN (NOT VOUT)
- Pin 4 = VOUT (tab, same as pin 2)

Getting these wrong would literally fry the regulator (VIN and GND swapped).

### PAM8403: Nearly every pin is wrong if you guess

The MSOP-16 package has a complex pinout. Always verify against the LCSC symbol.


## NC (No Connect) Marker Format

Unconnected pins should have green X markers to indicate intentional no-connect.
The format is:

```
O~{x}~{y}~{gge}~M {x-4} {y-4} L {x+4} {y+4} M {x+4} {y-4} L {x-4} {y+4}~#33cc33~0
```

The `O~` prefix is the EasyEDA shape type for "polyline/path objects". The path
draws two diagonal lines forming an X centered on the pin endpoint. Color
`#33cc33` is the standard EasyEDA green for NC markers.


## Net Flag Wire Stub Pattern

Every net connection uses a 30px wire stub between the pin endpoint and the
net flag. The pattern is:

```
Pin endpoint (px, py)
  → Wire: W~px py ex ey~#008800~1~0~none~{gge}~0
  → Flag: F~part_netLabel_...~ex~ey~...
```

Where `(ex, ey)` is offset 30px from `(px, py)` in the direction the pin faces.
This is the `FLAG_OFFSET` constant in the generator (default: 30).

For nets with 3+ endpoints, flag labels use a `:N` suffix (e.g., `GND:34`,
`3V3:25`) to indicate the total endpoint count for that net.


## API Rate Limiting

The EasyEDA API (`https://easyeda.com/api/products/{LCSC}/components`) should
be called with a delay between requests (default: 0.5s). Cache results by LCSC
part number — the same part returns the same symbol data every time. Our
generator caches by LCSC number and only fetches unique parts.
