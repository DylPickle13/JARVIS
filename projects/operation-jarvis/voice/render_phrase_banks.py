"""Explicit offline build. Cached Piper only; no playback, downloads or activation.

Run with the Operation JARVIS voice Python environment. Output is a new private
staging directory. A manifest is published only after all 84 renders validate.
Duration/quality exceptions are reported, never auto-approved or time-stretched.
"""
from __future__ import annotations

import argparse
from array import array
import io
import json
import os
from pathlib import Path
import sys
import wave

from phrase_banks import catalogue, digest, encoded, wav_info, voice_settings


def sample_quality(data):
    with wave.open(io.BytesIO(data), 'rb') as wav:
        samples = array('h', wav.readframes(wav.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    peak = max(abs(sample) for sample in samples)
    if peak == 0:
        raise ValueError('silent_recording')
    return {'peak': peak, 'clipped_samples': sum(abs(sample) >= 32767 for sample in samples)}


def build(output):
    # Do not start VoicePipeline, its session, ASR, or warm-up paths.
    import config
    operation = Path(__file__).resolve().parent.parent
    for file in (operation.parents[1] / '.env', operation / '.env', operation / 'voice/.env'):
        config.load_project_env(file)
    from voice_pipeline import VoicePipelineConfig
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig
    settings = voice_settings(VoicePipelineConfig())
    if settings['tts_backend'] != 'piper' or settings['tts_piper_quality'] not in ('high', 'medium'):
        raise ValueError('unsupported_voice_settings')
    quality = settings['tts_piper_quality']
    file = f'en/en_GB/jarvis/{quality}/jarvis-{quality}.onnx'
    model = Path(hf_hub_download(settings['tts_piper_repo_id'], file, local_files_only=True))
    model_config = Path(hf_hub_download(settings['tts_piper_repo_id'], file + '.json', local_files_only=True))
    voice = PiperVoice.load(str(model), config_path=str(model_config))
    synthesis = SynthesisConfig(
        length_scale=settings['tts_piper_length_scale'] / settings['tts_speed'],
        volume=settings['tts_piper_volume'], noise_scale=settings['tts_piper_noise_scale'],
        noise_w_scale=settings['tts_piper_noise_w_scale'])
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = catalogue()
    recordings = {}
    for row in rows:
        path = output / (row['id'] + '.wav')
        with wave.open(str(path), 'wb') as wav:
            voice.synthesize_wav(row['text'], wav, syn_config=synthesis)
        path.chmod(0o600)
        data = path.read_bytes()
        info = wav_info(data)
        recordings[row['id']] = {'text': row['text'], 'file': path.name,
            'sha256': digest(data), 'audio': info, 'quality': sample_quality(data)}
    # Raw clips exclude output-route padding. Compare like with like; deployment
    # retains room padding and the doorbell's existing 1.5-second leading silence.
    baselines = {event: recordings[f'{event}-straight-01']['audio']['seconds']
                 for event in ('wake', 'processing', 'arrival', 'departure')}
    limits = {event: round(seconds + max(0.5, seconds * 0.25), 4)
              for event, seconds in baselines.items()}
    limits['departure'] = min(4.5, limits['departure'])
    issues = []
    for row in rows:
        entry = recordings[row['id']]
        seconds = entry['audio']['seconds']
        reasons = []
        if seconds > limits[row['event']]:
            reasons.append('longer_than_baseline_tolerance')
        if row['event'] == 'departure' and seconds > 4.5:
            reasons.append('exceeds_protected_4.5_second_limit')
        if entry['quality']['clipped_samples']:
            reasons.append('clipped_samples')
        if reasons:
            issues.append({'id': row['id'], 'text': row['text'], 'seconds': seconds, 'reasons': reasons})
    manifest = {'version': 1, 'reviewed': False, 'catalogue_sha256': digest(encoded(rows)),
        'settings': settings, 'settings_sha256': digest(encoded(settings)),
        'model_sha256': digest(model.read_bytes()), 'model_config_sha256': digest(model_config.read_bytes()),
        'limits_seconds': limits, 'recordings': recordings}
    report = {'recordings': len(rows), 'reviewed': False, 'playback_performed': False,
        'baseline_basis': 'same-settings offline canonical renders; not live cached room clips',
        'baselines_seconds': baselines, 'limits_seconds': limits, 'issues': issues,
        'automatic_checks_do_not_establish': ['pronunciation', 'naturalness', 'physical audibility',
                                             'phonetic truncation', 'live clip duration equivalence']}
    for name, value in (('manifest.json', manifest), ('duration-report.json', report)):
        (output / name).write_text(json.dumps(value, indent=2) + '\n')
        (output / name).chmod(0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new private staging directory')
    args = parser.parse_args()
    os.umask(0o077)
    report = build(args.output)
    print(json.dumps({'recordings': report['recordings'], 'duration_or_quality_flags': len(report['issues']),
                      'reviewed': False, 'playback_performed': False}))


if __name__ == '__main__':
    main()
