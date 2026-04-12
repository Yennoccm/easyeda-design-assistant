# Si4735 Schematic V3 — Verification Findings

## UUID Verification (April 12, 2026)

Compared schematic_v3.json fields 7 (uuid) and 8 (puuid) against live EasyEDA API responses.

### Result: All UUIDs are REAL and CORRECT

Verified parts against API:
- U1 (C1526089 Si4735-D60-GU): uuid MATCH, puuid MATCH → SSOP-24
- U2 (C701341 ESP32-WROOM-32E): uuid MATCH, puuid MATCH → WIFI-SMD
- U3 (C5122557 PAM8403): uuid MATCH, puuid MATCH → SOP-16
- U4 (C6186 AMS1117-3.3): uuid MATCH, puuid MATCH → SOT-223
- X1 (C130253 32.768kHz): uuid MATCH, puuid MATCH → OSC-SMD_2P
- C1 (C1808 22nF): uuid MATCH, puuid MATCH → C0805
- R4-R12,R17-R19 (C17414 10kΩ): ALL uuid MATCH, ALL puuid MATCH → R0805

The generate_easyeda_schematic.py script correctly fetches real UUIDs from the
EasyEDA API and places them in LIB tilde-fields 7 and 8.

### Gap Found: c_para missing metadata

All 43 components have uuid/puuid in fields 7/8 (correct for footprint resolution)
but the c_para backtick string is MISSING:
- `uuid` — not in c_para
- `puuid` — not in c_para
- `LcscPart` — not in c_para
- `SupplierPart` — not in c_para
- `Manufacturer` — not in c_para
- `ManufacturerPart` — not in c_para

### Impact of missing c_para fields:
1. Properties dialog won't show LCSC/supplier info when clicking a component
2. BOM export won't include LCSC part numbers (critical for JLCPCB ordering)
3. If JSON is exported and re-imported, the c_para won't carry linkage data
4. Footprints WILL still resolve (fields 7/8 are what the engine reads)

### Recommendation for generate_easyeda_schematic.py:
When building the c_para string, also inject:
```
uuid`{uuid_value}`puuid`{puuid_value}`LcscPart`{lcsc}`Supplier`LCSC`SupplierPart`{lcsc}`
```
This makes the data visible in EasyEDA's UI and survives round-trip export/import.

### Verified API response format:
```
GET https://easyeda.com/api/products/{LCSC}/components

Response (single object, NOT array):
{
  "success": true,
  "result": {
    "uuid": "d4a844d81a8421ba55bf9bbe0176c427",
    "title": "0805W8F1002T5E",
    "dataStr": {
      "head": {
        "puuid": "b60f399a7a7e41848b2be1eb49c79141",
        "c_para": { "package": "R0805", ... }  // c_para is an OBJECT here, not backtick string
      }
    }
  }
}
```

Note: The API returns `result` as a single object (not array) for standard parts.
The `c_para` in the API response is a JSON object, not the backtick-delimited string
used in schematic JSON files.

## gge ID Collision Bug

**CRITICAL:** The `generate_easyeda_schematic.py` produces duplicate gge IDs across
components. EasyEDA uses gge IDs as unique element identifiers — every shape, pin,
text label, and component header needs a globally unique gge number.

### Evidence:
- SA612 v11 (real, hand-drawn schematic): **344 gge refs, 344 unique, 0 duplicates**
- Si4735 v3 (generated): **312 gge refs, 218 unique, 29 duplicated across components**

Worst offender: `gge26` is shared by U1, U2, X1, C4, C9, C15, C17, C18, C19.
`gge2` is shared by U1, U3, U4, C10, C12, C13, C14, C16.

### Why this matters:
EasyEDA's editor uses gge IDs to identify, select, and manipulate individual elements.
Duplicate IDs cause:
- Wrong element selected when clicking
- Copy/paste corruption
- Undo/redo targeting wrong elements
- Potential crashes or silent data loss during PCB conversion

### Fix:
The script must maintain a **single global gge counter** across all components,
not reset per component. Every `gge{N}` in the output must be unique.

```python
class GgeCounter:
    def __init__(self, start=1):
        self._n = start
    def next(self):
        gid = f"gge{self._n}"
        self._n += 1
        return gid

# One instance, shared across ALL components
gge = GgeCounter(start=1)
```

### Rate limiting note:
EasyEDA API rate-limits aggressively after ~19 rapid requests (even with 1s delays).
Returns HTML instead of JSON when throttled. Recovery time appears to be 5+ minutes.
The generate script should cache results and batch with 2-3s delays.


---

## Schematic V5 — Import Test Results (April 12, 2026)

v5 used field 7 = puuid (footprint), field 8 = uuid (symbol) based on DOM inspection.

**Import result:** Footprint package NAMES resolved correctly (R0805, C0402, SSOP-24, etc.)
BUT **41/43 components failed pin-to-pad verification** — "symbol pin number(s) does not
match the associated footprint pad number(s)".

**Root cause:** The v5 field 7/8 ordering was WRONG. DOM attribute names are misleading —
field 7's DOM attribute is named "puuid" but should contain the symbol uuid, and field 8's
DOM attribute is named "uuid" but should contain the footprint puuid.

---

## Schematic V6 — Field 7/8 Corrected (April 12, 2026)

### Fixes applied to generate_easyeda_schematic.py:

1. **Field 7/8 ordering CORRECTED** — LIB header now uses `~{uuid}~{puuid}~`
   (field 7 = symbol UUID, field 8 = footprint UUID). This matches the real
   schematic.json exported from EasyEDA. Verified: all 43 components' field 7/8
   values match the real schematic exactly.

2. **gge ID uniqueness** — `_rename_gge_ids()` function replaces all `gge{N}` and `rep{N}`
   patterns in API-fetched shapes with globally unique IDs from a monotonic counter.

3. **c_para metadata** — `build_cpara_string()` now injects uuid, puuid, LcscPart,
   Supplier, and Supplier Part into the backtick string for BOM export and Properties dialog.

4. **NC markers** — `make_nc_marker()` places green X marks on all 42 unconnected pins.

5. **Netlist pin corrections** — All four ICs (ESP32, Si4735, PAM8403, AMS1117) use correct
   physical pin numbers (not GPIO numbers or function-guessed numbers).

### Verification results (programmatic):

```
Field 7/8 Ordering: 43/43 match real schematic (uuid in field 7, puuid in field 8)
gge ID Uniqueness:  1056 total, 1056 unique, 0 duplicates
c_para Metadata:    All 43 components have uuid, puuid, LcscPart, Supplier, Supplier Part
```

### FIELD 7/8 ORDERING — RESOLVED

**Correct ordering (confirmed by real schematic comparison + v5 failure analysis):**
- Field 7 = uuid  (symbol UUID, from API `result.uuid`)
- Field 8 = puuid (footprint UUID, from API `result.dataStr.head.puuid`)

**Why DOM inspection was misleading:** EasyEDA's DOM maps field 7 to an attribute
called `puuid` and field 8 to an attribute called `uuid`. The attribute NAMES are
opposite of what they semantically contain. Trusting the DOM names caused v5's
41/43 pin-to-pad failures.

**Evidence chain:**
1. Real schematic.json (generated with old script) has field 7 = uuid, field 8 = puuid
2. v5 swapped them based on DOM names → 41/43 pin-to-pad failures
3. v6 restores original ordering → field 7/8 matches real schematic exactly
4. Awaiting end-to-end import verification of v6


---

## BREAKTHROUGH — Pipeline Working (April 12, 2026)

### The Missing Step: "Update from Library" After JSON Import

When EasyEDA imports a schematic JSON via File → Open → EasyEDA Source, it loads
the symbol shapes (pins, lines, text) but does NOT fetch footprint geometry from
the server. This causes ALL components to fail Footprint Verification — the PAD
information column is completely empty.

**The fix:** After importing the JSON, run:
  Design → Update Components from Library → Select All rows → check ONLY
  the "Footprint/Package" column → Update → OK

**⚠ Do NOT check the "Symbol" column.** Updating symbols replaces schematic
symbols with PCB footprint graphics (black rectangles) for many LCSC parts.

This triggers EasyEDA to fetch footprint data from its server for every
component, populating the footprint geometry that JSON import skips.

### Results:
- **Before "Update from Library":** 41/43 pin-to-pad verification failures
- **After "Update from Library":** 1/43 failures (only C1)

The one remaining failure is C1 (LCSC C1808, 22nF, footprint C0805). The EasyEDA
server returns "Can't find this footprint on the server, please re-associate it."
This is a server-side issue: C1808's API response has `docType: 2` (unusual) and
its footprint puuid `2ee8eb13a0124a108e622ce40c0c25a8` points to a deprecated or
missing package on EasyEDA's server.

**Fix for C1:** Replace C1808 with a different 22nF 0805 capacitor in the netlist
that has a valid footprint, or manually re-associate the footprint in EasyEDA.

### What We Tried That Did NOT Work:
1. `callCommand('updatePackageUuid', [puuid])` — JavaScript API call that worked
   for SA612 project but had no effect here. All calls returned `undefined` (no
   error) but footprint PAD info remained empty.
2. `callCommand('updateJsonCache')` — ran without error but didn't help.
3. Patching DOM `puuid` attributes via JavaScript — attributes updated correctly
   but didn't trigger footprint fetch.
4. `easyeda.extension.doCommand()` / `exec()` / `quickScript()` — explored but
   not tested (Update from Library solved it first).

### What DID Work:
- **"Update from Library" dialog** (Design menu) — batch fetches ALL footprints
  from the server in one operation. This is the reliable, supported approach.

### The Complete Working Pipeline:

```
1. Design circuit → netlist.json (components + nets + LCSC part numbers)

2. Run: python scripts/generate_easyeda_schematic.py
   → Fetches symbols from EasyEDA API
   → Places components on grid with correct field 7/8 (uuid/puuid)
   → Generates wires + net flags for all connections
   → Outputs schematic JSON

3. In EasyEDA Standard: File → Open → EasyEDA Source → select JSON file
   → Schematic loads with all symbols, wires, net flags visible
   → BUT footprint geometry is NOT loaded yet

4. CRITICAL STEP: Design → Update Components from Library
   → Check the box: "Check component latest version when open schematic"
   → Check "Select All" to select all component rows
   → Check ONLY the "Footprint/Package" column (NOT "Symbol")
   → Click "Update" → Click "OK" on warning
   → EasyEDA fetches footprint geometry from server for ALL components
   → Footprint PAD information now populated
   ⚠ If you also check "Symbol," EasyEDA replaces schematic symbols with
   PCB footprint graphics for parts that use footprint as primary shape

5. Verify: Design → Footprints Verification → Check Footprints
   → Should show 0 issues (or only parts with server-side problems)

6. Convert: Design → Convert Schematic to PCB
   → All footprints resolve, PCB layout ready
```

### Why This Works:
EasyEDA's JSON import loads component shapes from the file but treats footprint
references as "stale" — it doesn't auto-fetch from the server. The "Update from
Library" dialog forces a fresh fetch of both symbol and footprint data, linking
everything correctly. This is essentially what happens when you place a component
from the library manually (it auto-fetches), but JSON import skips that step.