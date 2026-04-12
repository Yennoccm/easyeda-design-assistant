/**
 * Post-Import Footprint Fix for EasyEDA Standard
 *
 * STATUS: The JavaScript API approach (updatePackageUuid) does NOT work
 * reliably for JSON-imported schematics. The internal state structures
 * that these commands depend on are not initialized by JSON import.
 *
 * ============================================================
 * THE WORKING FIX IS MANUAL (takes ~10 seconds):
 *   1. Design → Update Components from Library
 *   2. Check the box: "Check component latest version when open schematic"
 *   3. Select All → Click "Update" → Click "OK" on the warning
 * ============================================================
 *
 * This script is retained as a DIAGNOSTIC tool only — it can inspect
 * the DOM state of components after import to verify that uuid/puuid
 * attributes are correctly populated.
 *
 * WHAT WENT WRONG WITH THE API APPROACH:
 * - callCommand('updatePackageUuid', [puuid]) crashes with:
 *   "Cannot set properties of undefined (setting 'hasIdFlag')"
 * - callCommand('updatePackageAndPin') crashes with:
 *   "Cannot read properties of undefined (reading 'pin')"
 * - callCommand('fixedJsonCache') crashes with:
 *   "Cannot set properties of undefined (setting 'ggeXXXXX')"
 * - These all fail because JSON import doesn't populate the internal
 *   data structures that these commands expect.
 * - The "Update from Library" dialog uses a DIFFERENT code path that
 *   properly initializes everything.
 *
 * HOOKS EXPLORED (229 total in schematic editor iframe):
 *   updatePackageUuid, updatePackageAndPin, updateJsonCache,
 *   fixedJsonCache, checkJsonCache, recoverLibMd5Id, importPart,
 *   getPackage, getPadsByFootprintId, updateDeviceDomIdAndJsonCache,
 *   jsonMgr_updateOne, findComponent, getComponents, select
 *
 * Of these, only findComponent('C2') and checkJsonCache worked.
 * All update/fix commands crashed due to uninitialized internal state.
 */

// ==================== DIAGNOSTIC SCRIPT ====================
// Run in F12 console to inspect component DOM state after import

(function() {
    // Find the active schematic iframe (visible one)
    const iframes = document.querySelectorAll('iframe[id^="frame_"]');
    let activeFrame = null;
    for (const f of iframes) {
        try {
            if (f.offsetWidth > 0 && f.style.display !== 'none') {
                activeFrame = f;
                break;
            }
        } catch(e) {}
    }

    if (!activeFrame) {
        console.error('No visible schematic frame found');
        return;
    }

    console.log(`Active frame: ${activeFrame.id}`);
    const win = activeFrame.contentWindow;

    // Use findComponent to check components
    const prefixes = [];
    // Try C1-C20, R1-R20, U1-U10, X1-X5, F1-F5
    for (let i = 1; i <= 20; i++) {
        for (const pre of ['C', 'R']) {
            const el = win.callCommand('findComponent', [`${pre}${i}`]);
            if (el) prefixes.push(`${pre}${i}`);
        }
    }
    for (let i = 1; i <= 10; i++) {
        for (const pre of ['U', 'X', 'F', 'L', 'D', 'Q']) {
            const el = win.callCommand('findComponent', [`${pre}${i}`]);
            if (el) prefixes.push(`${pre}${i}`);
        }
    }

    console.log(`Found ${prefixes.length} components: ${prefixes.join(', ')}`);

    // Check each component's uuid/puuid state
    let ok = 0, missing = 0;
    for (const pre of prefixes) {
        const el = win.callCommand('findComponent', [pre]);
        const cpara = el.getAttribute('c_para') || '';
        const puuid = cpara.match(/puuid`([^`]+)/)?.[1] || '';
        const uuid = cpara.match(/uuid`([^`]+)/)?.[1] || '';
        const pkg = cpara.match(/package`([^`]+)/)?.[1] || '';

        if (puuid && uuid) {
            ok++;
        } else {
            missing++;
            console.warn(`${pre}: MISSING - uuid=${uuid ? 'OK' : 'EMPTY'}, puuid=${puuid ? 'OK' : 'EMPTY'}`);
        }
    }

    console.log(`\nResults: ${ok}/${prefixes.length} components have uuid+puuid in c_para`);
    if (missing > 0) {
        console.warn(`${missing} components are missing uuid or puuid metadata`);
    }

    console.log('\n=== TO FIX FOOTPRINTS ===');
    console.log('1. Design → Update Components from Library');
    console.log('2. Check: "Check component latest version when open schematic"');
    console.log('3. Select All → Update → OK on warning');
})();
