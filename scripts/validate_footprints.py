#!/usr/bin/env python3
"""
Pre-Import Footprint Validator for EasyEDA Schematics

This is the "second path through the maze" — validates that every LCSC
part in a netlist has a valid, fetchable footprint on EasyEDA's server
BEFORE you generate and import the schematic.

Catches problems like:
  - C1808 (22nF cap) → footprint C0805 → "Can't find on server"
  - Parts with docType 2 instead of 1 (unusual, may cause issues)
  - Parts whose footprint puuid doesn't match any server entry
  - API rate limiting / throttled parts

Usage:
    python validate_footprints.py --netlist netlist.json

    # With suggested replacements for broken parts:
    python validate_footprints.py --netlist netlist.json --suggest-fix

This does NOT modify any files. It only reads and reports.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

API_BASE = "https://easyeda.com/api/products"
DELAY = 1.0  # seconds between API calls


def fetch_component(lcsc: str) -> dict | None:
    """Fetch component data from EasyEDA API."""
    url = f"{API_BASE}/{lcsc}/components"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("success") and data.get("result"):
                return data["result"]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  ⚠ Rate limited on {lcsc}, waiting 10s...")
            time.sleep(10)
            return fetch_component(lcsc)  # retry once
        return None
    except Exception:
        return None
    return None


def validate_part(lcsc: str, value: str, prefix: str) -> dict:
    """Validate a single LCSC part's footprint availability."""
    result = {
        "prefix": prefix,
        "lcsc": lcsc,
        "value": value,
        "status": "unknown",
        "details": "",
    }

    comp = fetch_component(lcsc)
    if comp is None:
        result["status"] = "FAIL"
        result["details"] = "API returned no data (part may not exist)"
        return result

    # Handle array vs object response
    if isinstance(comp, list):
        # Find the schematic symbol (docType 1 or 2)
        symbol = None
        for entry in comp:
            if entry.get("docType") in (1, 2, "1", "2"):
                symbol = entry
                break
        if not symbol:
            result["status"] = "FAIL"
            result["details"] = f"No schematic symbol found in {len(comp)} results"
            return result
    else:
        symbol = comp

    doc_type = symbol.get("docType")
    uuid = symbol.get("uuid", "")
    head = symbol.get("dataStr", {}).get("head", {})
    puuid = head.get("puuid", "")
    cpara = head.get("c_para", {})
    package = cpara.get("package", "") if isinstance(cpara, dict) else ""

    result["uuid"] = uuid
    result["puuid"] = puuid
    result["package"] = package
    result["docType"] = doc_type

    # Check for issues
    issues = []

    if not uuid:
        issues.append("No symbol UUID")
    if not puuid:
        issues.append("No footprint puuid")
    if doc_type not in (1, "1"):
        issues.append(f"Unusual docType={doc_type} (expected 1)")

    # Try to fetch the footprint by puuid to verify it exists
    if puuid:
        fp_url = f"https://easyeda.com/api/components/{puuid}"
        try:
            req = urllib.request.Request(fp_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                fp_data = json.loads(resp.read().decode())
                if not fp_data.get("success"):
                    issues.append(f"Footprint puuid {puuid[:12]}... not found on server")
        except Exception as e:
            issues.append(f"Footprint fetch failed: {type(e).__name__}")

    if issues:
        result["status"] = "WARN" if len(issues) == 1 and "docType" in issues[0] else "FAIL"
        result["details"] = "; ".join(issues)
    else:
        result["status"] = "OK"
        result["details"] = f"{package} (puuid verified)"

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate EasyEDA footprints before import")
    parser.add_argument("--netlist", required=True, help="Path to netlist.json")
    parser.add_argument("--suggest-fix", action="store_true",
                        help="Suggest replacement LCSC parts for broken ones")
    args = parser.parse_args()

    with open(args.netlist) as f:
        netlist = json.load(f)

    components = netlist.get("components", {})
    print(f"Validating {len(components)} components from {args.netlist}\n")

    # Deduplicate by LCSC part number
    lcsc_to_prefixes: dict[str, list] = {}
    for prefix, info in sorted(components.items()):
        lcsc = info.get("lcsc", "")
        if lcsc not in lcsc_to_prefixes:
            lcsc_to_prefixes[lcsc] = []
        lcsc_to_prefixes[lcsc].append(prefix)

    print(f"Unique LCSC parts: {len(lcsc_to_prefixes)}\n")

    results = []
    ok_count = 0
    warn_count = 0
    fail_count = 0

    for lcsc, prefixes in sorted(lcsc_to_prefixes.items()):
        value = components[prefixes[0]].get("value", "")
        prefix_str = ", ".join(prefixes[:3])
        if len(prefixes) > 3:
            prefix_str += f" (+{len(prefixes) - 3} more)"

        print(f"  {lcsc:12s} {value:12s} ({prefix_str})...", end=" ", flush=True)

        result = validate_part(lcsc, value, prefix_str)
        results.append(result)

        if result["status"] == "OK":
            print(f"✓ {result['details']}")
            ok_count += len(prefixes)
        elif result["status"] == "WARN":
            print(f"⚠ {result['details']}")
            warn_count += len(prefixes)
        else:
            print(f"✗ {result['details']}")
            fail_count += len(prefixes)

        time.sleep(DELAY)

    print(f"\n{'=' * 60}")
    print(f"Results: {ok_count} OK, {warn_count} WARN, {fail_count} FAIL")
    print(f"{'=' * 60}")

    if fail_count > 0:
        print(f"\n⚠ {fail_count} component(s) have broken footprints.")
        print("These will show 'Can't find footprint on server' after import.")
        print("Fix: Replace the LCSC part number in netlist.json with a")
        print("working alternative, then regenerate the schematic.\n")

        for r in results:
            if r["status"] == "FAIL":
                print(f"  {r['prefix']:20s} {r['lcsc']:12s} {r['value']:12s} → {r['details']}")

    if fail_count == 0 and warn_count == 0:
        print("\n✓ All footprints validated! Safe to generate and import.")
        print("\nRemember after import:")
        print('  1. Design → Update Components from Library')
        print('  2. Check: "Check component latest version when open schematic"')
        print("  3. Select All → Update → OK on warning")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
