#!/usr/bin/env python3
"""Conservative, multi-window waveform alignment. Never changes original media."""
import json
import math
from pathlib import Path
import subprocess
import tempfile
import numpy as np
from scipy import signal
import opentimelineio as otio
from collect import save

RATE = 8000
FPS = 30


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True,timeout=60))


def audio(path, metadata):
    streams = [s for s in metadata['streams'] if s['codec_type']=='audio']
    if not streams:
        raise RuntimeError(f'No reference audio: {path.name}')
    # Use first audio stream, downmix to mono. Keep offset of its first sample
    # relative to the media origin: audio need not begin at video time zero.
    origin = float(streams[0].get('start_time',0))-float(metadata['format'].get('start_time',0))
    with tempfile.TemporaryDirectory(prefix='phone-sync-audio-') as temp:
        raw = Path(temp)/'audio.f32'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:a:0','-vn','-ac','1','-ar',str(RATE),'-f','f32le',str(raw)],check=True,timeout=1800)
        samples = np.fromfile(raw,dtype='<f4')
    if len(samples) < RATE*12 or not np.isfinite(samples).all():
        raise RuntimeError('Missing/too short/invalid audio; need at least 12 seconds')
    # Limit rumble/DC while preserving transient timing; zero-phase filter.
    samples = signal.sosfiltfilt(signal.butter(3,[180,3200],btype='bandpass',fs=RATE,output='sos'),samples).astype(np.float32)
    return samples, origin


def window_match(reference, target, start, seconds=8, max_offset=20, rate=RATE):
    t = int(start*rate); n = int(seconds*rate)
    y = target[t:t+n].astype(np.float64)
    left = max(0,t-int(max_offset*rate)); right = min(len(reference),t+n+int(max_offset*rate))
    x = reference[left:right].astype(np.float64)
    if len(y)!=n or len(x)<n:
        return {'accepted':False,'target_seconds':start,'reason':'insufficient overlap'}
    y -= y.mean(); energy = float(y@y)
    if math.sqrt(energy/n)<1e-5:
        return {'accepted':False,'target_seconds':start,'reason':'quiet audio'}
    numerator = signal.correlate(x,y,mode='valid',method='fft')
    sums = np.r_[0,np.cumsum(x)]; squares = np.r_[0,np.cumsum(x*x)]
    variance = np.maximum(squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n,0)
    scores = np.abs(numerator)/np.sqrt(np.maximum(variance*energy,1e-24))
    peak = int(np.argmax(scores)); best = float(scores[peak])
    competitors = scores.copy(); exclusion = int(.1*rate)
    competitors[max(0,peak-exclusion):peak+exclusion+1] = 0
    second = float(competitors.max(initial=0)); ratio = best/max(second,1e-9)
    return {'accepted':best>=.20 and ratio>=1.35,'target_seconds':start+seconds/2,
            'offset_seconds':(left+peak-t)/rate,'correlation':best,'peak_ratio':ratio}


def align_waveform(reference, target, max_offset=20):
    duration = min(len(reference),len(target))/RATE
    starts = np.linspace(1,max(1,duration-9),5)
    windows = [window_match(reference,target,float(t),max_offset=max_offset) for t in starts]
    good = [w for w in windows if w['accepted']]
    result = {'accepted':False,'windows':windows,'reason':'Need at least 3 confident windows spanning the take'}
    if len(good)<3 or good[-1]['target_seconds']-good[0]['target_seconds']<.5*(starts[-1]-starts[0]):
        return result
    offsets = np.array([w['offset_seconds'] for w in good]); times = np.array([w['target_seconds'] for w in good])
    slope, intercept = np.polyfit(times,offsets,1)
    residual = float(np.max(np.abs(offsets-(intercept+slope*times))))
    drift = float(slope*(len(target)/RATE))
    result.update(offset_seconds=float(np.median(offsets)),drift_seconds_over_take=drift,
                  residual_seconds=residual,offset_spread_seconds=float(np.ptp(offsets)))
    # No automatic stretching. Require observed and estimated drift below one
    # 30-fps frame, and mutually consistent window matches below half a frame.
    result['accepted'] = abs(drift)<=1/FPS and float(np.ptp(offsets))<=1/FPS and residual<=.5/FPS
    result['reason'] = 'Confident offset; drift within one frame' if result['accepted'] else 'Drift/inconsistent offsets: manual review required; no retiming applied'
    return result


def align(reference, target, max_offset=20):
    from spectral_sync import features, align_features
    return align_features(features(reference), features(target), max_offset)


def make_timeline(clips, offsets, output, name, reference=None):
    reference = reference or clips[0]['role']
    timeline = otio.schema.Timeline(name=name,global_start_time=otio.opentime.RationalTime(0,FPS))
    earliest = min(offsets.values())
    # Each camera keeps full source duration. Integer-frame starts on a 30-fps
    # timeline incur at most half a frame of rounding; originals stay VFR.
    for clip in clips:
        path = Path(clip['path']); role = clip['role']
        start = round((offsets[role]-earliest)*FPS)
        duration = math.floor(float(clip['metadata']['format']['duration'])*FPS)
        source = otio.opentime.TimeRange(otio.opentime.RationalTime(0,FPS),otio.opentime.RationalTime(duration,FPS))
        for kind in (otio.schema.TrackKind.Video,otio.schema.TrackKind.Audio):
            track = otio.schema.Track(name=f'{role} {kind}',kind=kind)
            if kind == otio.schema.TrackKind.Audio:
                track.enabled = role == reference
            if start:
                track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(otio.opentime.RationalTime(0,FPS),otio.opentime.RationalTime(start,FPS))))
            media = otio.schema.ExternalReference(target_url=str(path.resolve()),available_range=source)
            item = otio.schema.Clip(name=role,media_reference=media,source_range=source)
            item.metadata['phone_sync'] = {'original_path':str(path),'offset_seconds':offsets[role],'timeline_start_frame':start}
            track.append(item); timeline.tracks.append(track)
        clip['timeline_start_frame'] = start
    otio.adapters.write_to_file(timeline,str(output))
    # Deserialize immediately; invalid output must never count as successful.
    reread = otio.adapters.read_from_file(str(output))
    if len(reread.tracks)!=2*len(clips):
        raise RuntimeError('Timeline roundtrip failed')


def synchronize(folder, reference='samsung', max_offset=20):
    folder = Path(folder)
    manifest = json.loads((folder/'_verified-export.json').read_text())
    output = folder/'Resolve Sync'; output.mkdir(exist_ok=True)
    report = {'ok':False,'take_id':manifest['take_id'],'reference':reference,'fps':FPS,
              'notes':['Waveform alignment, not timecode/genlock.','No automatic drift correction or original-media re-encoding.','Variable-frame-rate source playback still needs a Resolve spot check.'], 'clips':[],'matches':{}}
    save(output/'sync-report.json',report)
    try:
        by_role = {}
        for relative in manifest['files']:
            role = Path(relative).parts[0]
            if role in by_role:
                raise RuntimeError('Multiple clips/proxies per camera are not yet supported; review required')
            path = folder/relative
            by_role[role] = {'role':role,'path':str(path.resolve()),'metadata':probe(path)}
        if len(by_role)<2 or reference not in by_role:
            raise RuntimeError('Need at least two cameras and the selected reference')
        report['clips'] = list(by_role.values())
        from spectral_sync import features, align_features
        from itertools import combinations
        feature_data = {}; origins = {}
        for role, clip in by_role.items():
            samples, origins[role] = audio(Path(clip['path']),clip['metadata'])
            feature_data[role] = features(samples)
        offsets = {reference:0.0}
        for role in by_role:
            if role == reference: continue
            match = align_features(feature_data[reference],feature_data[role],max_offset)
            match['reference_audio_origin_seconds'] = origins[reference]
            match['target_audio_origin_seconds'] = origins[role]
            report['matches'][role] = match
            if match['accepted']:
                offsets[role] = match['offset_seconds']+origins[reference]-origins[role]
            save(output/'sync-report.json',report)
        report['pair_cross_checks'] = {}
        cross_ok = True
        for left, right in combinations([r for r in by_role if r!=reference],2):
            check = align_features(feature_data[left],feature_data[right],max_offset*2)
            if check['accepted'] and left in offsets and right in offsets:
                measured = check['offset_seconds']+origins[left]-origins[right]
                check['cycle_error_seconds'] = measured-(offsets[right]-offsets[left])
                check['accepted'] = abs(check['cycle_error_seconds'])<=.5/FPS
            else:
                check['accepted'] = False
            cross_ok &= check['accepted']
            report['pair_cross_checks'][left+' -> '+right] = check
        report['ok'] = len(offsets)==len(by_role) and cross_ok
        if report['ok']:
            report['offsets_seconds'] = offsets
            timeline = output/'Synced.otio'
            make_timeline(report['clips'],offsets,timeline,'Phone Sync '+manifest['take_id'],reference)
            report['timeline'] = str(timeline)
            from resolve_import import write_lua_import
            report['resolve_menu_script'] = str(write_lua_import(report,output))
        else:
            report['error'] = 'Audio evidence insufficient or drift excessive. No aligned timeline generated.'
    except Exception as error:
        report['ok'] = False; report['error'] = str(error)[:1000]
    save(output/'sync-report.json',report)
    return report
