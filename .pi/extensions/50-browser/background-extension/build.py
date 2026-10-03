#!/usr/bin/env python3
"""Build a reviewable unpacked extension; NEVER install/register it in Chrome."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tempfile
import zipfile

CRX_SHA256 = 'e012b45f6170f627d275588ca1a37dffe5919c2635bbac512f11b74930e63835'
BACKGROUND_SHA256 = 'e77f9014417f5107332b80b8f5d4cfce2d83a7e269a85b0aa771576e045737ac'
EXTENSION = 'mmlmfjhmonkocbjadbfplnigmagldckm'
FOCUS = 'await Promise.all([chrome.tabs.update(tab.id, { active: true }), chrome.windows.update(tab.windowId, { focused: true })]).catch(() => {});'
REPLACEMENT = '// JARVIS_BACKGROUND_HANDSHAKE_V1: intentionally no tab/window activation.'
GROUP_PATCHES = (
    ('\t\tthis._connection = connection;', '\t\tthis._connection = connection;\n\t\tthis._jarvisWindowId = selectedTab.windowId;'),
    ('\t\t\tawait retryOnDrag(async () => {\n\t\t\t\tif (this._groupId === null)',
     '\t\t\tawait retryOnDrag(async () => {\n'
     '\t\t\t\t// JARVIS_BACKGROUND_GROUP_WINDOW_V1: never adopt the foreground window.\n'
     '\t\t\t\tconst tab = await chrome.tabs.get(tabId);\n'
     '\t\t\t\tif (tab.windowId !== this._jarvisWindowId) throw new Error("Automation tab left its window");\n'
     '\t\t\t\tif (this._groupId === null)'),
    ('chrome.tabs.group({ tabIds: [tabId] })',
     'chrome.tabs.group({ tabIds: [tabId], createProperties: { windowId: this._jarvisWindowId } })'),
)
SOURCE = Path(__file__).resolve().parent


def patch_background(source, addon):
    if hashlib.sha256(source.encode()).hexdigest() != BACKGROUND_SHA256 or source.count(FOCUS) != 1:
        raise ValueError('Unreviewed upstream background worker; refusing patch')
    patched = source.replace(FOCUS, REPLACEMENT)
    for old, new in GROUP_PATCHES:
        if patched.count(old) != 1:
            raise ValueError('Unreviewed upstream grouping operation; refusing patch')
        patched = patched.replace(old, new)
    if 'chrome.windows.update' in patched or 'focused: true' in patched:
        raise ValueError('Unexpected foreground operation remains')
    return patched + '\n' + addon


def build(crx, output):
    output = output.resolve()
    if output.exists():
        raise ValueError('Output already exists; never overwrite a potentially installed build')
    data = crx.read_bytes()
    if hashlib.sha256(data).hexdigest() != CRX_SHA256:
        raise ValueError('Unreviewed Chrome Web Store artifact; SHA256 mismatch')
    if data[:4] != b'Cr24' or struct.unpack('<I', data[4:8])[0] != 3:
        raise ValueError('Expected CRX3')
    header_size = struct.unpack('<I', data[8:12])[0]
    archive = zipfile.ZipFile(io.BytesIO(data[12 + header_size:]))
    manifest = json.loads(archive.read('manifest.json'))
    keyhash = hashlib.sha256(base64.b64decode(manifest['key'], validate=True)).hexdigest()[:32]
    extension_id = ''.join(chr(ord('a') + int(c, 16)) for c in keyhash)
    if extension_id != EXTENSION or manifest['version'] != '0.4.0' or manifest['background'] != {'service_worker': 'lib/background.mjs', 'type': 'module'}:
        raise ValueError('Unexpected extension identity/version/worker')
    if manifest['permissions'] != ['debugger', 'activeTab', 'tabs', 'tabGroups'] or manifest['host_permissions'] != ['<all_urls>']:
        raise ValueError('Unreviewed upstream permissions')
    addon = (SOURCE / 'native-addon.js').read_text()
    worker = patch_background(archive.read('lib/background.mjs').decode(), addon)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='jarvis-extension-build-', dir=output.parent))
    try:
        if sum(info.file_size for info in archive.infolist()) > 8 * 1024 * 1024:
            raise ValueError('Archive too large')
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe archive member')
            if not name.parts or name.parts[0] == '_metadata' or info.is_dir():
                continue
            target = temporary.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
        manifest['name'] = 'JARVIS Playwright — Background Only'
        manifest['description'] = 'Local JARVIS adaptation of Playwright: background-only connections in the existing Chrome profile. Not an official Microsoft release.'
        manifest['version_name'] = '0.4.0-jarvis-background-2'
        manifest['permissions'].append('nativeMessaging')
        manifest.pop('update_url', None)
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (temporary / 'lib/background.mjs').write_text(worker)
        shutil.copyfile(SOURCE / 'native_host.py', temporary / 'native_host.py')
        shutil.copyfile(SOURCE / 'LICENSE', temporary / 'LICENSE')
        entry = temporary / 'native-host'
        entry.write_text(f'#!{sys.executable}\nimport runpy\nrunpy.run_path({str(output / "native_host.py")!r}, run_name="__main__")\n')
        entry.chmod(0o700)
        host = {'name': 'com.jarvis.browser_background', 'description': 'JARVIS background-only Playwright connection host',
                'path': str(output / 'native-host'), 'type': 'stdio', 'allowed_origins': [f'chrome-extension://{EXTENSION}/']}
        (temporary / 'native-host-manifest.json').write_text(json.dumps(host, indent=2) + '\n')
        (temporary / 'JARVIS-NOTICE.txt').write_text('Local modification of Microsoft Playwright Extension 0.4.0, Apache-2.0.\n'
            'Original copyright notices retained. Removed connection-time focus; pinned tab groups to their original window; added background native-messaging transport.\n'
            'Unpacked developer build, not a Chrome Web Store release. Same public key/ID retained for existing bridge compatibility.\n'
            'Additional permission: nativeMessaging. No additional web-host permissions. No automatic upstream updates.\n')
        receipt = {'upstreamCRXSha256': CRX_SHA256, 'upstreamWorkerSha256': BACKGROUND_SHA256,
                   'builtWorkerSha256': hashlib.sha256(worker.encode()).hexdigest(), 'extensionId': EXTENSION,
                   'mode': 'jarvis-background-native-v1', 'installed': False}
        (temporary / 'build-review.json').write_text(json.dumps(receipt, indent=2) + '\n')
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crx', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.crx, args.output))
