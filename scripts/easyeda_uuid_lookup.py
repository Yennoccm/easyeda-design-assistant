#!/usr/bin/env python3
"""
Fetch EasyEDA component UUIDs for one or more LCSC part numbers.

EasyEDA resolves footprints using three identifiers:
  - uuid      — schematic symbol ID
  - puuid     — footprint (package) ID  ← the critical one
  - pdatastrid — secondary package identifier

This script queries EasyEDA's public API and outputs JSON you can feed
into patch_easyeda_json.py.

Usage:
    python easyeda_uuid_lookup.py C1620078 C7236 C34846
    python easyeda_uuid_lookup.py --file parts_list.txt
    python easyeda_uuid_lookup.py C1620078 --output uuids.json

The parts_list.txt file should have one LCSC part number per line.

Rate limiting: EasyEDA throttles after ~10-12 rapid requests.
The script adds a 1-second delay between requests by default.
Use --delay to adjust.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

API_URL = "https://easyeda.com/api/products/{lcsc}/components"
DEFAULT_DELAY = 1.0  # seconds between API calls


def fetch_uuids(lcsc_part: str) -> dict:
    """
    Query the EasyEDA API for a single LCSC part number.

    Returns a dict with uuid, puuid, pdatastrid, package, and title,
    or an error dict if the lookup fails.
    """
    url = API_URL.format(lcsc=lcsc_part)
    req = urllib.request.Request(url, headers={
        "User-Agent": "easyeda-uuid-lookup/1.0",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "lcsc": lcsc_part}
    except urllib.error.URLError as e:
        return {"error": str(e.reason), "lcsc": lcsc_part}
    except json.JSONDecodeError:
        return {"error": "API returned non-JSON (possibly rate-limited)", "lcsc": lcsc_part}

    # The API returns: {"success": true, "result": [...]}
    if not data.get("success") or not data.get("result"):
        return {"error": "Part not found in EasyEDA library", "lcsc": lcsc_part}

    # result is a list; first entry is typically the schematic symbol
    components = data["result"]

    # Find the schematic symbol (type 1) vs footprint (type 4)
    # We want the schematic component which carries both uuid and puuid
    symbol = None
    for comp in components:
        comp_type = comp.get("dataStr", {}).get("head", {}).get("docType")
        if comp_type == "1" or comp_type == 1:
            symbol = comp
            break

    # Fallback: just use the first component
    if symbol is None:
        symbol = components[0]

    uuid = symbol.get("uuid", "")
    puuid = ""
    pdatastrid = ""
    package = ""
    title = symbol.get("title", "")

    # puuid can be in dataStr.head or at top level
    head = symbol.get("dataStr", {}).get("head", {})
    puuid = head.get("puuid", "") or symbol.get("puuid", "")
    pdatastrid = head.get("uuidPcbModify", "") or ""

    # Package name from c_para if available
    c_para = head.get("c_para", {})
    if isinstance(c_para, dict):
        package = c_para.get("package", "")
    elif isinstance(c_para, str):
        # Backtick-delimited string
        tokens = c_para.split("`")
        for i in range(0, len(tokens) - 1, 2):
            if tokens[i] == "package":
                package = tokens[i + 1]
                break

    # If puuid still empty, check the components list for a footprint entry
    if not puuid:
        for comp in components:
            comp_type = comp.get("dataStr", {}).get("head", {}).get("docType")
            if comp_type == "4" or comp_type == 4:
                puuid = comp.get("uuid", "")
                pdatastrid = comp.get("uuid", "")
                pkg_head = comp.get("dataStr", {}).get("head", {})
                if not package:
                    pkg_cpara = pkg_head.get("c_para", {})
                    if isinstance(pkg_cpara, dict):
                        package = pkg_cpara.get("package", comp.get("title", ""))
                break

    return {
        "uuid": uuid,
        "puuid": puuid,
        "pdatastrid": pdatastrid,
        "package": package,
        "title": title,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Fetch EasyEDA UUIDs for LCSC part numbers"
    )
    parser.add_argument(
        "parts", nargs="*",
        help="LCSC part numbers (e.g., C1620078 C7236)"
    )
    parser.add_argument(
        "--file", "-f",
        help="File with one LCSC part number per line"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file (default: stdout)"
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=DEFAULT_DELAY,
        help=f"Delay between API requests in seconds (default: {DEFAULT_DELAY})"
    )
    args = parser.parse_args()

    parts = list(args.parts or [])
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts.append(line)

    if not parts:
        parser.error("No LCSC part numbers provided. Use positional args or --file.")

    results = {}
    errors = []

    for i, lcsc in enumerate(parts):
        lcsc = lcsc.strip().upper()
        if not lcsc.startswith("C") or not lcsc[1:].isdigit():
            print(f"  SKIP  {lcsc} — doesn't look like an LCSC part number", file=sys.stderr)
            continue

        print(f"  [{i+1}/{len(parts)}] Looking up {lcsc}...", file=sys.stderr)
        result = fetch_uuids(lcsc)

        if "error" in result:
            print(f"  ERROR {lcsc}: {result['error']}", file=sys.stderr)
            errors.append(lcsc)
            results[lcsc] = result
        else:
            puuid_status = "✓" if result["puuid"] else "✗ NO PUUID"
            print(f"  OK    {lcsc}: {result['package']} {puuid_status}", file=sys.stderr)
            results[lcsc] = result

        # Rate limit delay (skip after last item)
        if i < len(parts) - 1 and args.delay > 0:
            time.sleep(args.delay)

    # Output
    output = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output + "\n")
        print(f"\nWrote {len(results)} results to {args.output}", file=sys.stderr)
    else:
        print(output)

    if errors:
        print(f"\n{len(errors)} part(s) had errors: {', '.join(errors)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
