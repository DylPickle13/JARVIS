"""Opt-in approved farewell bundle. No synthesis, device calls or retry.

The existing journal/proof/identity/playback path remains authoritative. This
adapter only supplies a validated recording after that attempt is authorized.
"""
from pathlib import Path
import sys

import runtime

VOICE_ROOT = Path(__file__).resolve().parents[2] / 'voice'
if str(VOICE_ROOT) not in sys.path:
    sys.path.append(str(VOICE_ROOT))
import phrase_banks


def select(root, attempt, expires):
    pin = runtime.read_json(root / 'phrase-bank.json')
    if pin is None:
        return None  # Legacy exact-phrase/hash path remains the default.
    if (set(pin) != {'version', 'bundle', 'manifest_sha256'} or pin['version'] != 1
            or not isinstance(pin['bundle'], str) or not Path(pin['bundle']).is_absolute()):
        raise runtime.TrialError('invalid_phrase_bank_pin')
    bundle = phrase_banks.Bundle(pin['bundle'], pin['manifest_sha256'], events=('departure',))
    # Same DB as both room servers. Durably consuming this attempt before dispatch
    # means a crash or repeated worker can never reselect/replay its recording.
    clip = phrase_banks.Selector().reserve(bundle, 'departure', attempt)
    if clip is None:
        raise runtime.TrialError('duplicate_phrase_bank_attempt')
    runtime.save_json(root / 'phrase-selection.json', {
        'attempt': attempt, 'expires': expires, 'phrase_id': clip.id,
        'phrase': clip.text, 'sha256': clip.sha256, 'manifest_sha256': bundle.manifest_hash})
    return clip
