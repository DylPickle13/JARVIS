#!/usr/bin/env python3
"""Capture the user-provided Playwright token locally; never print it."""
import os
import re
from pathlib import Path
import subprocess
import tempfile

TOKEN_PATH = Path.home() / '.jarvis' / 'playwright-extension.token'
PROMPT = '''
tell application "System Events"
    activate
    set response to display dialog "In Chrome, click the Playwright extension icon and copy the PLAYWRIGHT_MCP_EXTENSION_TOKEN value. Paste the token or the full PLAYWRIGHT_MCP_EXTENSION_TOKEN assignment below. It will be stored locally, not sent to chat." with title "JARVIS — Playwright connection" default answer "" with hidden answer buttons {"Cancel", "Save token"} default button "Save token" cancel button "Cancel" giving up after 600
    if gave up of response then error number -128
    return text returned of response
end tell
'''


def parse_token(value):
    value = value.strip()
    assignment = re.fullmatch(r'(?:export\s+)?[\"\']?PLAYWRIGHT_MCP_EXTENSION_TOKEN[\"\']?\s*[:=]\s*(.+?)\s*,?', value, re.DOTALL)
    if assignment:
        value = assignment.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
        value = value[1:-1]
    if not value or any(c.isspace() for c in value) or 'PLAYWRIGHT_MCP_EXTENSION_TOKEN' in value:
        raise ValueError('Invalid token format')
    return value


def main():
    result = subprocess.run(['osascript', '-e', PROMPT], capture_output=True, text=True)
    if result.returncode:
        print('Token setup cancelled or dialog unavailable. No token changed.')
        return 1
    try:
        token = parse_token(result.stdout)
    except ValueError:
        print('Invalid input: paste the token or its assignment line. No token changed.')
        return 1
    TOKEN_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.playwright-token-', dir=TOKEN_PATH.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(token + '\n')
        os.replace(temporary, TOKEN_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Playwright token saved locally with owner-only permissions. Connection not yet tested.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
