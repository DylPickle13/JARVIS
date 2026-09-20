"""Private-file Piper worker, using the existing local JARVIS voice environment.
No camera access, network downloads, playback, or voice-pipeline startup.
"""
from pathlib import Path
import os
import sys
import wave


def synthesize(text_path, output_path):
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / 'voice'))
    import config
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig

    # Read only synthesis preferences; never export the root credentials.
    values = {}
    for path in (root.parents[1] / '.env', root / '.env', root / 'voice/.env'):
        values.update({k: v for k, v in config.parse_dotenv_file(path).items()
                       if k.startswith('JARVIS_VOICE_TTS_')})
    values.update({k: v for k, v in os.environ.items() if k.startswith('JARVIS_VOICE_TTS_')})
    prefix = 'JARVIS_VOICE_TTS_'
    quality = values.get(prefix + 'PIPER_QUALITY', 'high')
    if quality not in ('high', 'medium'):
        raise ValueError('invalid_quality')
    repo = values.get(prefix + 'PIPER_REPO_ID', 'jgkawell/jarvis')
    filename = f'en/en_GB/jarvis/{quality}/jarvis-{quality}.onnx'
    model = hf_hub_download(repo, filename, local_files_only=True)
    config_path = hf_hub_download(repo, filename + '.json', local_files_only=True)
    voice = PiperVoice.load(model, config_path=config_path)
    def number(key, default):
        return float(values.get(prefix + key, default))
    syn = SynthesisConfig(
        length_scale=number('PIPER_LENGTH_SCALE', 1.15) / max(number('SPEED', 1.0), 0.01),
        volume=number('PIPER_VOLUME', 0.95),
        noise_scale=number('PIPER_NOISE_SCALE', 0.55),
        noise_w_scale=number('PIPER_NOISE_W_SCALE', 0.70))
    text = Path(text_path).read_text(encoding='utf-8')
    # Incremental chunks, no truncation or segment count limit.
    words = text.split()
    with wave.open(str(output_path), 'wb') as wav:
        for start in range(0, len(words), 60):
            voice.synthesize_wav(' '.join(words[start:start + 60]), wav, syn_config=syn,
                                 set_wav_format=(start == 0))


if __name__ == '__main__':
    try:
        synthesize(*sys.argv[1:])
    except Exception:
        print('jarvis_voice_unavailable', file=sys.stderr)
        raise SystemExit(2)
