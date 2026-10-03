#!/usr/bin/env python3
"""Local integration tests; no dependencies or network. Invokes the real model."""
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import time
import zlib

BIN = Path(__file__).resolve().parents[1] / 'bin/apple-model'

def run(*args, stdin='', ok=True):
    p = subprocess.run([str(BIN), *args], input=stdin, text=True,
                       capture_output=True, cwd='/tmp', timeout=120)
    assert (p.returncode == 0) == ok, (args, p.returncode, p.stdout, p.stderr)
    return p

def png(path, rgb):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = (b'\0' + bytes(rgb) * 256) * 256
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
        chunk(b'IHDR', struct.pack('>2I5B', 256, 256, 8, 2, 0, 0, 0)) +
        chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))

status = json.loads(run('status', '--json').stdout)
assert status['available'] and status['vision'] and status['localOnly'], status
assert status['variant'] == 'AFM 3 Core Advanced', status
print('PASS status:', status)
assert 'PONG' in json.loads(run('ask', '--json', '--max-tokens', '32', 'Reply exactly PONG').stdout)['text']
print('PASS text JSON')
assert 'ORCHID' in run('ask', 'Repeat the supplied word exactly.', stdin='ORCHID').stdout
print('PASS stdin')
events = [json.loads(line) for line in run('ask', '--json', '--stream', '--max-tokens', '32', 'Reply exactly PONG').stdout.splitlines()]
assert events[-1]['type'] == 'done'
assert ''.join(e['text'] for e in events if e['type'] == 'delta') == events[-1]['text']
print('PASS NDJSON stream')
assert 'PONG' in run('ask', '--stream', '--max-tokens', '32', 'Reply exactly PONG').stdout
print('PASS plain stream')
for args in [('ask', '--max-tokens', '0'), ('ask', '--image'), ('ask', '--audio', 'x'), ('ask',), ('bogus',)]:
    run(*args, ok=False)
print('PASS argument validation')
with tempfile.TemporaryDirectory(prefix='apple-model-test-') as directory:
    root = Path(directory)
    red, blue = root / 'red.png', root / 'blue.png'
    png(red, (255, 0, 0))
    png(blue, (0, 0, 255))
    result = run('ask', '--json', '--max-tokens', '80', '--image', str(red),
                 'What is the dominant color of this image? Answer with the color name only.')
    text = json.loads(result.stdout)['text']
    assert 'red' in text.lower(), text
    print('PASS image:', text)
    result = run('ask', '--json', '--max-tokens', '128', '--image', str(red), '--image', str(blue),
                 'Name the dominant color of image 1 and image 2, in that order.')
    text = json.loads(result.stdout)['text']
    assert 'red' in text.lower() and 'blue' in text.lower(), text
    print('PASS multiple images:', text)
    bad = root / 'bad.png'
    bad.write_text('not an image')
    run('ask', '--image', str(bad), ok=False)
    run('ask', '--image', str(root / 'missing.png'), ok=False)
print('PASS image validation')
p = run('ask', '--json', 'Summarize this.', stdin='ordinary token ' * 15000, ok=False)
error = json.loads(p.stderr)
assert error['type'] == 'error' and error['error'], p.stderr
print('PASS oversized-input error propagation (guardrails may reject before context check):', error['error'])
p = subprocess.Popen([str(BIN), 'ask', '--stream', 'Write a long essay about mathematics.'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(0.2)
assert p.poll() is None, 'Process exited before cancellation test'
p.send_signal(signal.SIGINT)
p.communicate(timeout=10)
assert p.returncode == -signal.SIGINT, p.returncode
print('PASS SIGINT cancellation')
print('All smoke tests passed.')
