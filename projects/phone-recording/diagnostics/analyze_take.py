#!/usr/bin/env python3
"""Read-only analysis of retained test videos; never delete media."""

# Permit direct execution from the diagnostics directory.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
from pathlib import Path
import subprocess
import sys


def inspect(path):
    metadata = json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height,avg_frame_rate','-of','json',str(path)],text=True,timeout=60))
    frames = json.loads(subprocess.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],text=True,timeout=90))['frames']
    pts = [float(f['best_effort_timestamp_time']) for f in frames if 'best_effort_timestamp_time' in f]
    gaps = [b-a for a,b in zip(pts,pts[1:])]
    decode = subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:v:0','-fps_mode','passthrough','-enc_time_base','1:1000000','-f','null','-'],capture_output=True,text=True,timeout=300)
    return {'path':str(path),'bytes':path.stat().st_size,'metadata':metadata,'frames':len(frames),
            'gaps_over_50ms':sum(g>.050001 for g in gaps),'max_gap_ms':max(gaps,default=0)*1000,
            'nonincreasing_pts':sum(g<=0 for g in gaps),'full_video_decode_ok':decode.returncode==0,
            'decode_errors':decode.stderr[:1000]}


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    paths = sorted(p for p in root.rglob('*') if p.suffix.lower() in ('.mov','.mp4') and p.stat().st_size>0)
    results = [inspect(p) for p in paths]
    (root/'video-analysis.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
