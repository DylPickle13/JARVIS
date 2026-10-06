"""Bounded Minecraft save-pause/checkpoint; never hold autosave off during upload."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class MinecraftCheckpoint:
    def __init__(self, source, state, settings, deadline, lock_fd=None):
        self.source = Path(source).resolve()
        self.relative = Path(settings['relative_path'])
        if self.relative.is_absolute() or '..' in self.relative.parts:
            raise ValueError('Minecraft source must be a relative child of JARVIS')
        self.root = self.source / self.relative
        self.stage = Path(state) / 'minecraft'
        self.marker = Path(state) / 'minecraft-autosave-pending.json'
        self.settings = settings
        self.deadline = deadline
        self.parent_lock_fds = () if lock_fd is None else (lock_fd,)
        self.lock_fds = self.parent_lock_fds
        self.restoring = False
        self.world_relative = self.relative / 'server/world'
        self.world = self.root / 'server/world'

    def validate(self):
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise RuntimeError('Minecraft must be the real in-tree directory, not an external symlink')
        required = ['server/paper.jar', 'server/server.properties', 'server/whitelist.json',
                    'server/plugins/floodgate/key.pem', 'server/world/level.dat']
        for dimension in ['overworld', 'the_nether', 'the_end']:
            required += [f'server/world/dimensions/minecraft/{dimension}/region',
                         f'server/world/dimensions/minecraft/{dimension}/data/minecraft/world_gen_settings.dat']
        for rel in required:
            if not (self.root / rel).exists():
                raise RuntimeError(f'Required Minecraft source missing: {rel}')
        properties = dict(line.split('=', 1) for line in
                          (self.root / 'server/server.properties').read_text().splitlines()
                          if '=' in line and not line.startswith('#'))
        expected = {'server-port': str(self.settings['java_port']),
                    'server-ip': self.settings['java_host'], 'online-mode': 'false',
                    'white-list': 'true', 'enforce-whitelist': 'true'}
        mismatches = [f'{key}: expected {value!r}, found {properties.get(key)!r}'
                      for key, value in expected.items() if properties.get(key) != value]
        if mismatches:
            raise RuntimeError('Minecraft source/endpoint/security settings do not match the approved server: '
                               + '; '.join(mismatches))
        if self.marker.exists():
            raise RuntimeError('An interrupted Minecraft checkpoint requires autosave-state review before another backup')

    def running_info(self):
        listing = subprocess.run(['screen', '-list'], capture_output=True, text=True).stdout
        name = re.escape(self.settings['screen_session'])
        sessions = re.findall(r'(\d+\.' + name + r')\s', listing)
        result = subprocess.run(['lsof', '-t', '-nP',
                                 f'-iTCP:{self.settings["java_port"]}', '-sTCP:LISTEN'],
                                capture_output=True, text=True)
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot establish Minecraft listener ownership')
        pids = set(result.stdout.split())
        if not sessions and not pids:
            # Refuse the startup/shutdown interval rather than declaring it stopped.
            for line in subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True).splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and Path(parts[1]).name == 'java':
                    cwd = subprocess.run(['lsof', '-a', '-p', parts[0], '-d', 'cwd', '-Fn'],
                                         capture_output=True, text=True).stdout.splitlines()
                    if 'n' + str(self.root / 'server') in cwd:
                        raise RuntimeError('Minecraft is changing state; no stopped checkpoint permitted')
            return None
        if len(sessions) != 1 or len(pids) != 1:
            raise RuntimeError('Minecraft session/listener ownership is ambiguous')
        pid = next(iter(pids))
        # Process titles may become simply 'java'; prove the actual mapped binary.
        executable = subprocess.check_output(['lsof', '-a', '-p', pid, '-d', 'txt', '-Fn'], text=True).splitlines()
        expected = 'n' + str((self.root / 'java/current/bin/java').resolve())
        cwd = subprocess.check_output(['lsof', '-a', '-p', pid, '-d', 'cwd', '-Fn'], text=True).splitlines()
        if expected not in executable or 'n' + str(self.root / 'server') not in cwd:
            raise RuntimeError('Minecraft listener belongs to another process or directory')
        started = subprocess.check_output(['ps', '-p', pid, '-o', 'lstart='], text=True).strip()
        return {'pid': pid, 'session': sessions[0], 'started': started}

    def command(self, owner, command, success, timeout=30):
        current = self.running_info()
        if current != owner:
            raise RuntimeError('Minecraft process identity changed; refusing console write')
        log = self.root / 'server/logs/latest.log'
        before = log.stat()
        offset = before.st_size
        subprocess.run(['screen', '-S', owner['session'], '-p', '0', '-X', 'stuff', command + '\r'],
                       check=True, capture_output=True, text=True, timeout=5)
        # Acceptance by screen is not execution. Require a fresh server acknowledgement.
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if log.stat().st_ino != before.st_ino:
                raise RuntimeError('Minecraft log rotated during checkpoint; state is unknown')
            with log.open() as f:
                f.seek(offset)
                fresh = f.read()
            for marker in success:
                # Match exact server replies, not player chat containing the same words.
                pattern = (r'^\[\d{2}:\d{2}:\d{2}(?: INFO)?\](?: \[Server thread/INFO\])?: '
                           + re.escape(marker) + r'\.?\s*$')
                if re.search(pattern, fresh, re.IGNORECASE | re.MULTILINE):
                    return marker
            time.sleep(0.1)
        raise RuntimeError(f'Minecraft did not acknowledge {command}; no command replay performed')

    @contextmanager
    def interruptible(self):
        previous = {}
        def interrupted(signum, frame):
            if self.restoring:
                return  # defer further interrupts until the bounded save-on acknowledgement
            raise InterruptedError('Minecraft checkpoint interrupted; restoring autosave')
        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, interrupted)
            yield
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def clone_world(self):
        for p in self.world.rglob('*'):
            if p.is_symlink():
                raise RuntimeError('Unreviewed symlink in Minecraft world; refusing incomplete checkpoint')
        destination = self.stage / self.world_relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        remaining = min(60, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError('No budget remaining for Minecraft checkpoint')
        subprocess.run(['cp', '-cR', str(self.world), str(destination)],
                       check=True, capture_output=True, text=True, timeout=remaining, pass_fds=self.lock_fds)

    def samples(self):
        world = self.stage / self.world_relative
        files = [world / 'level.dat']
        files += sorted((world / 'players/data').glob('*.dat'))
        for dimension in ['overworld', 'the_nether', 'the_end']:
            base = world / 'dimensions/minecraft' / dimension
            files.append(base / 'data/minecraft/world_gen_settings.dat')
            regions = sorted((base / 'region').glob('*.mca'))
            if not regions:
                raise RuntimeError('Minecraft checkpoint contains an empty dimension region set')
            files.append(regions[int(time.time() // 86400) % len(regions)])
        return [{'relative_path': str(f.relative_to(self.stage)), 'sha256': sha256(f)} for f in files]

    def create(self):
        self.validate()
        lock_path = self.root / 'backups/world-checkpoint.lock'
        lock_path.parent.mkdir(exist_ok=True, mode=0o700)
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another Minecraft checkpoint is active')
            self.lock_fds = tuple(set((*self.parent_lock_fds, lock.fileno())))
            owner = self.running_info()
            restore_saves = False
            # This stage is disposable; it is protected by the outer backup lock.
            if self.stage.exists():
                import shutil
                shutil.rmtree(self.stage)
            self.stage.mkdir(mode=0o700)
            with self.interruptible():
                try:
                    if owner:
                        # Persist intent before the write so hard termination is detectable.
                        self.marker.write_text(json.dumps({'owner': owner, 'source': str(self.root)}) + '\n')
                        self.marker.chmod(0o600)
                        restore_saves = True
                        reply = self.command(owner, 'save-off',
                                             ['Automatic saving is now disabled', 'Saving is already turned off'])
                        if reply == 'Saving is already turned off':
                            restore_saves = False
                            self.marker.unlink()
                            raise RuntimeError('Autosave was already disabled; respecting the existing operation')
                        self.command(owner, 'save-all flush', ['Saved the game'], timeout=45)
                    self.clone_world()
                finally:
                    if restore_saves:
                        self.restoring = True
                        # Restore before SQLite staging, upload, verification, or maintenance.
                        self.command(owner, 'save-on',
                                     ['Automatic saving is now enabled', 'Saving is already turned on'])
                        self.marker.unlink()
                        self.restoring = False
            manifest = {'version': 1, 'source_relative': str(self.relative),
                        'world_relative': str(self.world_relative),
                        'mode': 'save-paused-apfs-clone' if owner else 'stopped-apfs-clone',
                        'samples': self.samples()}
            (self.stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print('Minecraft checkpoint: ' + ('save/flush acknowledged; autosave restored.' if owner else 'stopped world copied.'))
            return manifest
