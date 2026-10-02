#!/usr/bin/env python3
"""Bounded read-only handset player sampling; private numeric metadata, no video.

Android 6 dumpsys meminfo may request GC, so these are not unbiased leak profiles.
Does not change screen, playback, presence, network, app configuration or services.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--samples', type=int, choices=range(1,61), default=11)
    p.add_argument('--interval', type=int, choices=range(5,301), default=60)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if root == output or root in output.parents:
        raise SystemExit('Observation metadata must remain outside the project.')
    os.umask(0o077)
    output.parent.mkdir(parents=True, exist_ok=True)

    def adb(*parts):
        r = subprocess.run(['adb','-s',args.serial,*parts], capture_output=True, text=True, timeout=15)
        if r.returncode:
            raise RuntimeError('ADB unavailable')
        return r.stdout

    with output.open('x') as stream:
        for index in range(args.samples):
            row = {'time': datetime.datetime.now().astimezone().isoformat(), 'sample': index}
            try:
                state = adb('shell','dumpsys','activity','local.jarvis.monitor/.ViewerActivity')
                for key in ('decoded','displayed','opens','releases','glFrames','presented','audioRendered',
                            'voiceSamples','voiceOutput','voiceCpuUs'):
                    match = re.search(r'\b'+key+r'=(\d+)',state)
                    row[key] = int(match[1]) if match else None
                row['voiceFocus'] = 'voiceFocus=true' in state
                row['voiceSupported'] = 'voiceSupported=true' in state
                row['active'] = 'activePlayer=true' in state
                row['resumed'] = 'viewer resumed=true' in state
                row['retryPending'] = 'retryPending=true' in state
                row['glActive'] = 'glActive=true' in state
                row['lensFallback'] = 'lensFallback=true' in state
                lens = re.search(r'viewer lens=(original|mild|medium|strong)\b', state)
                row['lens'] = lens[1] if lens else None
                battery = adb('shell','dumpsys','battery')
                temperature = re.search(r'^\s*temperature:\s*(\d+)', battery, re.M)
                row['battery_celsius'] = int(temperature[1]) / 10 if temperature else None
                mem = adb('shell','dumpsys','meminfo','local.jarvis.monitor:video')
                match = re.search(r'MEMINFO in pid (\d+)',mem)
                row['pid'] = int(match[1]) if match else None
                for label, key in [('Dalvik Heap','java'),('Native Heap','native')]:
                    match = re.search(r'^\s*'+label+r'\s+(\d+(?:\s+\d+){6})\s*$',mem,re.M)
                    if match:
                        values = list(map(int,match[1].split()))
                        row[key+'_allocated_kib'] = values[5]
                match = re.search(r'^\s*TOTAL\s+(\d+)',mem,re.M)
                row['pss_kib'] = int(match[1]) if match else None
            except Exception:
                row['error'] = 'unavailable' # No raw command/exception text.
            stream.write(json.dumps(row)+'\n'); stream.flush()
            print(json.dumps(row), flush=True)
            if index+1 < args.samples:
                time.sleep(args.interval)


if __name__ == '__main__':
    main()
