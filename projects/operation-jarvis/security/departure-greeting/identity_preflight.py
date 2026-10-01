"""Short-lived identity evidence only; never grants playback or stores credentials."""
import hashlib
import json
import math
import time
import runtime

MAX_AGE = 10


def binding(entry, env_file):
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode() + b'\0' +
                          env_file.read_bytes()).hexdigest()


def evidence(entry, env_file):
    return {'binding': binding(entry, env_file), 'checked_at': time.time(),
            'tick': time.monotonic()}


def fresh(value, entry, env_file):
    if type(value) is not dict or set(value) != {'binding', 'checked_at', 'tick'}:
        return False
    if any(type(value[k]) not in (int, float) or not math.isfinite(value[k])
           for k in ('checked_at', 'tick')):
        return False
    wall, mono = time.time()-value['checked_at'], time.monotonic()-value['tick']
    return (0 <= wall <= MAX_AGE and 0 <= mono <= MAX_AGE and abs(wall-mono) <= 2
            and value['binding'] == binding(entry, env_file))


def ticket(root, value, attempt, expires, entry, env_file):
    clear(root)
    if fresh(value, entry, env_file):
        runtime.save_json(root/'identity-ticket.json', {'version': 1, 'attempt': attempt,
            'expires': expires, 'evidence': value})


def valid(root, attempt, expires, entry, env_file):
    value = runtime.read_json(root/'identity-ticket.json')
    return (type(value) is dict and set(value) == {'version', 'attempt', 'expires', 'evidence'}
            and type(value['version']) is int and value['version'] == 1
            and value['attempt'] == attempt and value['expires'] == expires
            and fresh(value['evidence'], entry, env_file))


def clear(root):
    (root/'identity-ticket.json').unlink(missing_ok=True)
