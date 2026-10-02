"""Explicit Android USB/Wi-Fi selection with identity checks; no transport fallback."""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
from inventory import DEFAULT_ADB

from camera_config import CAMERAS,ANDROID_ROLES
IDENTITIES={r:CAMERAS[r]['serial'] for r in ANDROID_ROLES}
from runtime_paths import ROOT


def config(root=ROOT):
    path=root/'android-transports.json'
    if not path.is_file(): raise RuntimeError('Wi-Fi camera configuration required; no USB fallback')
    value=json.loads(path.read_text())
    if set(value)!=set(IDENTITIES):raise ValueError('All enabled Android transport entries required')
    for role,item in value.items():
        if item.get('mode') != 'wifi':raise ValueError('Wi-Fi-only controller; USB is disabled')
        if item['mode']=='wifi':
            host=item.get('host','')
            if ipaddress.ip_address(host) not in ipaddress.ip_network('192.168.21.0/24'):raise ValueError('Wi-Fi host outside approved LAN')
            if not isinstance(item.get('port'),int) or not 1<=item['port']<=65535:raise ValueError('Invalid connection port')
            service=item.get('service')
            if service and (not CAMERAS[role].get('wireless_tls') or not re.fullmatch(r'adb-'+IDENTITIES[role]+r'-[A-Za-z0-9]+',service)):
                raise ValueError('Discovery service does not match camera identity')
    return value


def targets(settings):
    return {r:(IDENTITIES[r] if v['mode']=='usb' else f"{v['host']}:{v['port']}") for r,v in settings.items()}


def verify(role,target):
    actual=subprocess.check_output([DEFAULT_ADB,'-s',target,'shell','getprop','ro.serialno'],text=True,stderr=subprocess.PIPE,timeout=8).strip()
    if actual!=IDENTITIES[role]:raise RuntimeError('Android identity mismatch; no camera command sent')


def discover_port(service):
    p=subprocess.Popen(['/usr/bin/dns-sd','-L',service,'_adb-tls-connect._tcp','local.'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:out,_=p.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        p.terminate();out,_=p.communicate(timeout=3)
    # Resolve ONLY the previously paired device's service; never scan arbitrary ports.
    match=re.search(r'can be reached at [^\s]+:(\d+) \(',out)
    if not match:raise ConnectionError('Paired Samsung connection service not found')
    port=int(match[1])
    if not 1<=port<=65535:raise ValueError('Invalid discovered port')
    return port


def ensure(role,settings,selected):
    target=selected[role]
    try:verify(role,target);return target
    except (OSError,subprocess.SubprocessError):
        if settings[role]['mode']!='wifi':raise
    # A mismatch above raises RuntimeError and must NOT trigger discovery/fallback.
    item=settings[role]
    if item.get('service'):target=f"{item['host']}:{discover_port(item['service'])}"
    subprocess.run([DEFAULT_ADB,'connect',target],check=True,capture_output=True,text=True,timeout=12)
    verify(role,target);selected[role]=target
    return target


def describe(settings,selected):
    return {r:{'mode':item['mode'],'endpoint':selected[r],
               'security':'paired TLS' if item.get('service') else 'legacy unencrypted ADB' if item['mode']=='wifi' else 'USB'}
            for r,item in settings.items()}
