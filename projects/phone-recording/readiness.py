"""Bounded idle-only health observations and conservative Start gates.
No recordings, app-setting writes, AFC/media sessions or continuous monitoring.
Battery temperature is not sensor/GPU temperature or proof against throttling.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import math
from pathlib import Path
import re
import shutil
from camera_config import CAMERAS,ROLES,IDLE,CONFIG_ID

MIN_BATTERY=20
WARN_BATTERY=40
MIN_PHONE_FREE=2*1024**3
WARN_PHONE_FREE=5*1024**3
MIN_MAC_FREE=5*1024**3
WARN_TEMP=40
MAX_TEMP=45
MAX_AGE=120


def now():return datetime.datetime.now().astimezone().isoformat()


def fresh(value):
    try:
        age=(datetime.datetime.now().astimezone()-datetime.datetime.fromisoformat(value)).total_seconds()
        return -5<=age<=MAX_AGE
    except (TypeError,ValueError):return False


def number(value,lo,hi):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and lo<=value<=hi


def assess(metrics):
    metrics=dict(metrics)
    for key,lo,hi in [('battery_percent',0,100),('free_bytes',0,10**16),('battery_temperature_c',-20,100),('thermal_status',0,6)]:
        if not number(metrics.get(key),lo,hi):metrics[key]=None
    blocks=[];warnings=[]
    battery=metrics.get('battery_percent');free=metrics.get('free_bytes');temp=metrics.get('battery_temperature_c')
    if not number(battery,0,100):blocks.append('Battery level unavailable')
    elif battery<MIN_BATTERY:blocks.append(f'Battery below {MIN_BATTERY}%')
    elif battery<WARN_BATTERY:warnings.append(f'Battery below {WARN_BATTERY}%')
    if not number(free,0,10**16):blocks.append('Free storage unavailable')
    elif free<MIN_PHONE_FREE:blocks.append('Less than 2 GiB free on phone')
    elif free<WARN_PHONE_FREE:warnings.append('Less than 5 GiB free on phone')
    if metrics.get('external_power') is False:warnings.append('Running on battery')
    elif metrics.get('external_power') is None:warnings.append('External power status unavailable')
    if not number(temp,-20,100):warnings.append('Battery temperature unavailable; check phone manually')
    elif temp>=MAX_TEMP:blocks.append(f'Battery temperature at least {MAX_TEMP}°C')
    elif temp>=WARN_TEMP:warnings.append(f'Battery temperature at least {WARN_TEMP}°C')
    severity=metrics.get('thermal_status')
    if number(severity,0,6) and severity>=3:blocks.append('Android reports severe-or-higher thermal status')
    elif number(severity,0,6) and severity>=2:warnings.append('Android reports moderate thermal status')
    return {'ok':not blocks,'metrics':metrics,'blockers':blocks,'warnings':warnings}


def parse_android(battery,disk,thermal):
    values={}
    for line in battery.splitlines():
        if ':' in line:
            key,value=line.split(':',1);values[key.strip()]=value.strip()
    def numeric(key):
        try:return float(values[key])
        except (KeyError,ValueError):return None
    level=numeric('level');scale=numeric('scale')
    percent=100*level/scale if number(level,0,10000) and number(scale,1,10000) else None
    temp=numeric('temperature');temp=temp/10 if temp is not None else None
    powered=[values.get(k) for k in ('AC powered','USB powered','Wireless powered')]
    external=True if 'true' in powered else False if all(p=='false' for p in powered) else None
    free=None
    # df -k: explicitly identify Available/Avail header, do not guess an arbitrary numeric field.
    lines=[line.split() for line in disk.splitlines() if line.strip()]
    if len(lines)>=2:
        index=next((i for i,key in enumerate(lines[0]) if key.lower() in ('available','avail')),None)
        if index is not None:
            try:free=int(lines[-1][index])*1024
            except (ValueError,IndexError):pass
    match=re.search(r'Thermal Status:\s*([0-6])\b',thermal)
    return {'battery_percent':percent,'external_power':external,'battery_temperature_c':temp,
            'free_bytes':free,'thermal_status':int(match[1]) if match else None}


def android_metrics(role):
    from pair_control import adb
    battery=adb(role,'shell','dumpsys','battery')
    disk=adb(role,'shell','df','-k','/sdcard')
    try:thermal=adb(role,'shell','dumpsys','thermalservice')
    except Exception:thermal=''
    return parse_android(battery,disk,thermal)


async def iphone_metrics():
    from pymobiledevice3.lockdown import create_using_usbmux
    from iphone_network import identity
    expected=identity()
    async with await create_using_usbmux(serial=expected,autopair=False,connection_type='Network') as client:
        if client.udid!=expected or client.product_type!='iPhone12,1' or client.service.mux_device.connection_type!='Network':
            raise RuntimeError('iPhone identity/Network transport mismatch')
        async def value(domain,key):
            try:return await client.get_value(domain=domain,key=key)
            except Exception:return None
        battery=await value('com.apple.mobile.battery','BatteryCurrentCapacity')
        powered=await value('com.apple.mobile.battery','ExternalConnected')
        charging=await value('com.apple.mobile.battery','BatteryIsCharging')
        free=await value('com.apple.disk_usage','AmountDataAvailable')
        return {'battery_percent':battery,'external_power':powered if type(powered) is bool else True if charging is True else None,
                'charging':charging if type(charging) is bool else None,'free_bytes':free,
                'battery_temperature_c':None,'thermal_status':None}


async def bounded_iphone():return await asyncio.wait_for(iphone_metrics(),25)


def probe(role):
    try:
        metrics=android_metrics(role) if CAMERAS[role]['platform']=='android' else asyncio.run(bounded_iphone())
        return assess(metrics)
    except Exception as e:return {'ok':False,'metrics':{},'blockers':['Health check unavailable: '+type(e).__name__],'warnings':[]}


def local_storage():
    try:
        free=shutil.disk_usage(Path.home()/'Movies').free
        return {'ok':free>=MIN_MAC_FREE,'free_bytes':free,'minimum_bytes':MIN_MAC_FREE}
    except OSError:return {'ok':False,'free_bytes':None,'minimum_bytes':MIN_MAC_FREE}


def check(states):
    # Do not open even metadata sessions during capture, pending collection, or unknown states.
    # Known-idle cameras can be checked when another camera is offline, but never if any records.
    recording=any(v=='recording' for v in states.values())
    targets=[r for r in ROLES if states.get(r)=='idle' and not recording]
    with ThreadPoolExecutor(max_workers=max(1,len(targets))) as pool:
        phones=dict(zip(targets,pool.map(probe,targets)))
    for role in ROLES:
        if role not in phones:phones[role]={'ok':False,'metrics':{},'blockers':['Health check deferred: recording or camera not verified idle'],'warnings':[]}
    storage=local_storage()
    return {'ok':states==IDLE and all(p['ok'] for p in phones.values()) and storage['ok'],
            'checked_at':now(),'config_id':CONFIG_ID,'phones':phones,'collection_storage':storage}


def approved(report):
    if not isinstance(report,dict) or not fresh(report.get('checked_at')) or report.get('config_id')!=CONFIG_ID:return False
    phones=report.get('phones',{})
    storage=report.get('collection_storage',{})
    if not isinstance(phones,dict) or not isinstance(storage,dict) or any(not isinstance(p,dict) or not isinstance(p.get('metrics'),dict) for p in phones.values()):return False
    return report.get('ok') is True and set(phones)==set(ROLES) and all(p.get('ok') is True and assess(p.get('metrics',{}))['ok'] for p in phones.values()) and storage.get('ok') is True and number(storage.get('free_bytes'),MIN_MAC_FREE,10**16)
