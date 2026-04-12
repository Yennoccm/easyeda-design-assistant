# EasyEDA Design Assistant Plugin

End-to-end electronics design assistant for EasyEDA Standard — from circuit idea
through schematic generation, footprint linking, and PCB preparation.

## What It Does

This plugin gives Claude the knowledge and tools to help you design electronics
in EasyEDA Standard:

- **Circuit Designer** — Design circuits from a high-level idea, select real
  components with LCSC part numbers, and produce a structured netlist
- **Schematic Generator** — Programmatically generate EasyEDA-importable JSON
  from a netlist (no manual component placement needed)
- **Design Assistant** — Guide the full flow: part selection, SMD vs TH decisions,
  footprint linking, and the critical post-import steps that make PCB conversion work

## The Pipeline

```
1. Describe your circuit idea
2. Claude helps design it → netlist.json with LCSC parts
3. Python script generates EasyEDA schematic JSON
4. Import into EasyEDA: File → Open → EasyEDA Source
5. Link footprints: Design → Update Components from Library
6. Verify: Design → Footprints Verification
7. Convert: Design → Convert Schematic to PCB
```

## Included Scripts

- `scripts/generate_easyeda_schematic.py` — Main generator engine
- `scripts/validate_footprints.py` — Pre-import footprint validation
- `scripts/easyeda_uuid_lookup.py` — LCSC-to-UUID lookup utilities

## Hard-Won Lessons Baked In

This plugin encodes dozens of hours of debugging EasyEDA's internals:

- **LIB Field 7/8 ordering** — Field 7 = symbol UUID, Field 8 = footprint UUID
  (the DOM attribute names are misleading — don't trust them)
- **gge ID global uniqueness** — Every element ID must be unique across the
  entire schematic or things silently break
- **Post-import footprint fetch** — JSON import does NOT auto-fetch footprint
  geometry. You MUST run "Update Components from Library" after every import.
- **Pin number gotchas** — ESP32 GPIO numbers != physical pins, AMS1117 pinout
  varies by package, etc.

All of this is documented in `references/easyeda_json_format.md` and encoded
in the generator script so you never have to rediscover it.

## Optional MCP Integrations

Works well with these optional connectors (not required):

- **DigiKey MCP** — Search and lookup electronic components
- **Footprints MCP** — Download EasyEDA/KiCad footprints by LCSC number
