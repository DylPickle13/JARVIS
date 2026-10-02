"""Verify playable media before releasing phone originals. Never modifies media."""
import json
import math
import subprocess

FFPROBE = '/opt/homebrew/bin/ffprobe'
FFMPEG = '/opt/homebrew/bin/ffmpeg'


def verify_video(path, dimensions=None):
    probe = subprocess.run(
        [FFPROBE, '-v', 'error', '-show_entries',
         'format=duration:stream=codec_type,width,height,avg_frame_rate',
         '-of', 'json', str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    metadata = json.loads(probe.stdout)
    duration = float(metadata['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('Invalid video duration')
    video = [s for s in metadata.get('streams', []) if s.get('codec_type') == 'video']
    if not video or not any(s.get('width', 0) > 0 and s.get('height', 0) > 0 for s in video):
        raise RuntimeError('No valid video stream')
    if dimensions and not any((s.get('width'), s.get('height')) == dimensions for s in video):
        raise RuntimeError('Unexpected video dimensions')
    subprocess.run(
        [FFMPEG, '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
         '-map', '0:v:0', '-map', '0:a?', '-fps_mode', 'passthrough',
         '-enc_time_base', '1:1000000', '-f', 'null', '-'],
        capture_output=True, check=True, timeout=max(3600, min(21600, math.ceil(duration * 4))),
    )
    return metadata
