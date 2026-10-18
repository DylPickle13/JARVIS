"""Stage approved arrival replacements without changing live code, pins or state.

Copies validated existing recordings for other events. Output is unreviewed;
activation still requires catalogue policy/state migration and duration approval.
No playback, downloads, or service changes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import wave

from phrase_banks import Bundle, catalogue, digest, encoded, read_private, wav_info
from render_phrase_banks import sample_quality


def build(source: Path, output: Path, proposal: Path):
    old_raw = read_private(source / 'manifest.json')
    old = json.loads(old_raw)
    bundle = Bundle(source, digest(old_raw))
    replacement = json.loads(proposal.read_text())
    texts = replacement['phrases']
    if (replacement['event'] != 'arrival' or replacement['style'] != 'dry'
            or len(texts) != 12 or len(set(texts)) != 12
            or any(not isinstance(text, str) or not text.strip() for text in texts)):
        raise ValueError('invalid_arrival_proposal')
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig
    settings = old['settings']
    quality = settings['tts_piper_quality']
    filename = f'en/en_GB/jarvis/{quality}/jarvis-{quality}.onnx'
    model = Path(hf_hub_download(settings['tts_piper_repo_id'], filename, local_files_only=True))
    config = Path(hf_hub_download(settings['tts_piper_repo_id'], filename + '.json', local_files_only=True))
    if (digest(model.read_bytes()) != old['model_sha256']
            or digest(config.read_bytes()) != old['model_config_sha256']):
        raise ValueError('cached_model_provenance_mismatch')
    voice = PiperVoice.load(str(model), config_path=str(config))
    synthesis = SynthesisConfig(
        length_scale=settings['tts_piper_length_scale'] / settings['tts_speed'],
        volume=settings['tts_piper_volume'], noise_scale=settings['tts_piper_noise_scale'],
        noise_w_scale=settings['tts_piper_noise_w_scale'])
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows = catalogue()
    arrivals = iter(texts)
    recordings = {}
    report = []
    for row in rows:
        path = output / (row['id'] + '.wav')
        if row['event'] == 'arrival':
            row['text'] = next(arrivals)
            # Preserve stable IDs for an explicit, separately reviewed migration.
            row['style'] = 'dry'
            with wave.open(str(path), 'wb') as wav:
                voice.synthesize_wav(row['text'], wav, syn_config=synthesis)
        else:
            path.write_bytes(bundle.clips[row['id']].audio)
        path.chmod(0o600)
        data = path.read_bytes()
        info = wav_info(data)
        quality_result = sample_quality(data)
        recordings[row['id']] = dict(text=row['text'], file=path.name,
            sha256=digest(data), audio=info, quality=quality_result)
        if row['event'] == 'arrival':
            report.append(dict(id=row['id'], text=row['text'], seconds=info['seconds'],
                exceeds_existing_limit=info['seconds'] > old['limits_seconds']['arrival'],
                **quality_result))
    manifest = dict(old, reviewed=False, catalogue_sha256=digest(encoded(rows)), recordings=recordings)
    result = dict(reviewed=False, playback_performed=False,
        existing_arrival_limit_seconds=old['limits_seconds']['arrival'], recordings=report,
        unchanged_other_recordings=True,
        requires=['duration approval', 'all-dry catalogue policy',
                  'reviewed selector-state migration', 'coordinated pinned deployment'])
    for name, value in [('manifest.json', manifest), ('catalogue.json', {'version': 1, 'phrases': rows}),
                        ('duration-report.json', result)]:
        path = output / name
        path.write_text(json.dumps(value, indent=2) + '\n')
        path.chmod(0o600)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--proposal', type=Path, default=Path(__file__).with_name('arrival-phrases-v2.json'))
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(build(args.source, args.output, args.proposal), indent=2))
