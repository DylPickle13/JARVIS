#!/usr/bin/env python3
"""Build NEW, UNINSTALLED vendor package copies with mandatory SDK checkpoints.

No live files, credentials, dependencies, defaults or accepted certificates are
changed. Exact reviewed wrapper inputs only; drift requires deliberate re-review.
This is a build operation, never an automatic runtime upgrade/fallback.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

BASELINES = {
    # Audit: read-only status_all added; mutation paths unchanged, SDK no-replay
    # suite revalidated. Still fail closed on any subsequent source drift.
    'smart-plug/smart_plug/kasa_client.py': '1e2261422c228a2387a960135152b80aabb02fbdb9acfae01c8cbdc2c743c818',
    'air-purifier/air_purifier/write_safety.py': '50c2254b557aa0116d2489e5e01b8447e0b2e4abb4491a2edc49ce72e36d1e4f',
}
PATCHES = {
    'smart-plug/smart_plug/kasa_client.py': [
        ('from kasa import Discover\n', 'from kasa import Discover\nfrom . import vendor_fence as _ownership\n'),
        ('    async def save_discovery(self) -> dict[str, PlugStatus]:\n        statuses = await self.discover()\n',
         '    async def save_discovery(self) -> dict[str, PlugStatus]:\n        _ownership.reject_catalogue_change()\n        statuses = await self.discover()\n'),
        ('                               expected_host: str | None) -> PlugStatus:\n',
         '                               expected_host: str | None, *, intent: str | None = None) -> PlugStatus:\n'),
        ('        with _single_attempt_write(dev, on):\n',
         '''        intent = intent or ('plug-on' if on else 'plug-off')
        if (type(on) is not bool or intent not in ('plug-on', 'plug-off', 'plug-toggle')
                or intent != 'plug-toggle' and on is not (intent == 'plug-on')):
            raise _ownership.FenceError()
        observed = _safe_get(dev, 'host')
        if type(observed) is not str:
            raise _ownership.FenceError()
        call = {'cohort': 'plugs', 'target': observed.strip().lower(), 'method': intent,
                'args': [], 'kwargs': {}}
        with _ownership.permission(call, desired={'isOn': on}), _single_attempt_write(dev, on):
'''),
        ('            return await self._write_connected(dev, name, host, not current, expected_host)\n',
         '            return await self._write_connected(dev, name, host, not current, expected_host, intent="plug-toggle")\n'),
    ],
    'air-purifier/air_purifier/write_safety.py': [
        ('from typing import Any\n', 'from typing import Any\nfrom . import vendor_fence as _ownership\n'),
        ('    with ExitStack() as stack:\n        stack.enter_context(temporary_attribute(target, "manager", view))\n',
         '''    with ExitStack() as stack:
        call = {'cohort': 'purifier', 'target': target.cid, 'method': method,
                'args': list(args), 'kwargs': kwargs}
        stack.enter_context(_ownership.permission(call, desired={'method': operation, 'data': data}))
        stack.enter_context(temporary_attribute(target, "manager", view))
'''),
    ],
}


def stage(source, destination):
    source, destination = Path(source).resolve(strict=True), Path(destination).absolute()
    destination = destination.parent.resolve(strict=True) / destination.name
    if destination.exists() or destination.is_symlink() or destination.is_relative_to(source):
        raise ValueError('A new staging destination outside the live source tree is required')
    contents = {}
    for relative, expected in BASELINES.items():
        path = source / relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Reviewed vendor source drift; no automatic hash refresh')
        text = path.read_text()
        for old, new in PATCHES[relative]:
            if text.count(old) != 1:
                raise ValueError('Vendor patch context is not unique')
            text = text.replace(old, new, 1)
        compile(text, relative, 'exec')
        contents[relative] = text
    helper = Path(__file__).parent / 'jarvisd_core/vendor_fence.py'
    destination.mkdir(mode=0o700)  # Partial failure remains uninstalled for diagnosis.
    for package in ('smart-plug/smart_plug', 'air-purifier/air_purifier'):
        target = destination / package
        target.mkdir(parents=True)
        for path in (source / package).rglob('*.py'):
            if path.is_symlink():
                raise ValueError('Linked vendor source refused')
            copied = target / path.relative_to(source / package)
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copied)
        shutil.copy2(helper, target / 'vendor_fence.py')
    for relative, text in contents.items():
        (destination / relative).write_text(text)
    manifest = {str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(destination.rglob('*.py'))}
    (destination / 'staged-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: stage-fenced-vendors.py SOURCE_OPERATION_ROOT NEW_STAGING_ROOT')
    print(json.dumps(stage(sys.argv[1], sys.argv[2]), indent=2, sort_keys=True))
