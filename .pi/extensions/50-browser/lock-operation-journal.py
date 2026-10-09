#!/usr/bin/env python3
"""Private locked atomic journal writer. No Chrome/networking or page data.
All writes occur in the SAME process that holds flock: losing this helper cannot
leave a controller writing without its lock. EOF releases the kernel lock, but
unresolved execution stays fenced by the separate journal.
"""
import fcntl
import json
import os
import stat
import sys
import tempfile


def main():
    journal = sys.argv[1]
    directory = os.path.dirname(journal)
    metadata = os.lstat(directory)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        return 3
    fd = os.open(journal + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            return 3
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 4
        print('locked', flush=True)
        last = 0
        while True:
            line = sys.stdin.buffer.readline(2 * 1024 * 1024)
            if not line:
                return 0
            if not line.endswith(b'\n'):
                return 3
            request = json.loads(line)
            sequence, body = request.get('sequence'), request.get('body')
            if type(sequence) is not int or sequence != last + 1 or not isinstance(body, str) or len(body.encode()) > 1024 * 1024:
                return 3
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=directory, prefix='.operation-', delete=False) as stream:
                    temporary = stream.name
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, journal)
                temporary = None
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary:
                    os.unlink(temporary)
            last = sequence
            print('written:' + str(sequence), flush=True)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        raise SystemExit(3)
