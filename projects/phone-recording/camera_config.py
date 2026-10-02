"""Shared, versioned camera registry. Enable only after deliberate onboarding.
Deploy the same JSON to both Macs; mismatched fingerprints block Start.
"""
import hashlib
import json
from pathlib import Path
import re


def load(path=None):
    value=json.loads((Path(path) if path else Path(__file__).with_name('camera-config.json')).read_text())
    if value.get('version')!=1 or not isinstance(value.get('cameras'),list):raise ValueError('Invalid camera registry')
    cameras={};serials=set()
    for item in value['cameras']:
        role=item.get('role','')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',role) or role in cameras:raise ValueError('Invalid/duplicate camera role')
        if item.get('platform') not in ('android','iphone'):raise ValueError('Unsupported camera platform')
        for key in ('enabled','onboarded','preview'):
            if type(item.get(key)) is not bool:raise ValueError('Camera flags must be booleans')
        if item['enabled'] and not item['onboarded']:raise ValueError('Cannot enable a camera before onboarding')
        for key in ('name','model','video_label'):
            if not isinstance(item.get(key),str) or not 1<=len(item[key])<=100:raise ValueError('Invalid camera label')
        if item['platform']=='android':
            serial=item.get('serial','')
            if not re.fullmatch(r'[A-Za-z0-9]{6,64}',serial) or serial in serials:raise ValueError('Invalid/duplicate hardware identity')
            serials.add(serial)
            if type(item.get('wireless_tls')) is not bool:raise ValueError('Android wireless security mode required')
        elif role!='iphone':raise ValueError('Only the bound iPhone is supported')
        cameras[role]=item
    if not cameras.get('iphone',{}).get('enabled'):raise ValueError('Current managed collector requires the bound iPhone')
    if not any(v['enabled'] and v['platform']=='android' for v in cameras.values()):raise ValueError('An Android camera is required')
    return cameras


def fingerprint(cameras):
    return hashlib.sha256(json.dumps(cameras,sort_keys=True,separators=(',',':')).encode()).hexdigest()


CAMERAS=load()
ROLES=tuple(r for r,c in CAMERAS.items() if c['enabled'])
ANDROID_ROLES=tuple(r for r in ROLES if CAMERAS[r]['platform']=='android')
PREVIEW_ROLES=tuple(r for r in ROLES if CAMERAS[r]['preview'])
IDLE={r:'idle' for r in ROLES}
UNKNOWN={r:'unknown' for r in ROLES}
CONFIG_ID=fingerprint(CAMERAS)


def public():
    return [{k:c[k] for k in ('role','name','platform','model','enabled','onboarded','video_label','preview')} for c in CAMERAS.values()]
