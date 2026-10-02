#!/usr/bin/env python3
"""Idle-only Wi-Fi push/pull test of new diagnostic bytes, never camera media."""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import fcntl
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
import uuid
import pair_control as pair
from collect import save


def main():
    run=uuid.uuid4().hex
    folder=pair.ROOT/'.wifi-validation'/run
    folder.mkdir(parents=True,mode=0o700)
    report={'id':run,'recording_commands_sent':False,'camera_media_touched':False,'phones':{}}
    with (pair.ROOT/'.pair-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (pair.ROOT/'pending-take.json').exists():raise RuntimeError('Pending take; deferred')
        if any(v['mode']!='wifi' for v in pair.TRANSPORTS.values()):raise RuntimeError('Explicit Wi-Fi selection required')
        for role in pair.PHONES:
            if pair.status()!={'lg':'idle','samsung':'idle'}:raise RuntimeError('Both phones must be idle')
            source=folder/(role+'-source.bin');target=folder/(role+'-received.bin')
            source.write_bytes(secrets.token_bytes(8*1024*1024))
            sha=hashlib.sha256(source.read_bytes()).hexdigest()
            remote='/sdcard/Download/phone-recording-wifi-'+run+'-'+role+'.bin'
            pair.adb(role,'shell','test','!','-e',remote)
            start=time.monotonic()
            subprocess.run([pair.DEFAULT_ADB,'-s',pair.PHONES[role],'push',str(source),remote],check=True,capture_output=True,timeout=120)
            phone_sha=pair.adb(role,'shell','sha256sum',remote).split()[0]
            if phone_sha!=sha:raise RuntimeError('Diagnostic upload hash mismatch; fixture retained')
            subprocess.run([pair.DEFAULT_ADB,'-s',pair.PHONES[role],'pull',remote,str(target)],check=True,capture_output=True,timeout=120)
            if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise RuntimeError('Diagnostic download hash mismatch; fixture retained')
            if pair.adb(role,'shell','sha256sum',remote).split()[0]!=sha:raise RuntimeError('Diagnostic fixture changed')
            # Only the unique diagnostic file created above; never enumerate/delete camera media.
            pair.adb(role,'shell','rm',remote)
            pair.adb(role,'shell','test','!','-e',remote)
            report['phones'][role]={'ok':True,'bytes':source.stat().st_size,'sha256':sha,
                                   'endpoint':pair.PHONES[role],'roundtrip_seconds':round(time.monotonic()-start,3),
                                   'diagnostic_phone_file_removed':True}
            save(folder/'result.json',report)
        report['after']=pair.status()
        report['ok']=report['after']=={'lg':'idle','samsung':'idle'}
        save(folder/'result.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
