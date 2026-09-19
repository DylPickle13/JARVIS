"""Explicit fenced worker candidate. Not selected by the installed daemon.

Reads use the existing adapter, stripped of delegation authority. Writes require
one durable worker checkpoint for their exact operation before vendor execution.
SDK-side checkpoints are separately required; this entry alone is NOT cutover.
"""
import json
import os
import subprocess
import sys

from . import device_worker as legacy, vendor_fence as fence
from .control_delegation import WRITES, worker_call
from .device_vendor import DeviceVendorAdapter


def execute(args, *, adapter, emit):
    if args.command not in WRITES:
        return legacy.execute(args, adapter=adapter, emit=emit)
    try:
        with fence.permission(worker_call(args), phase='worker'):
            return legacy.execute(args, adapter=adapter, emit=emit)
    except KeyboardInterrupt:
        code, error = 130, 'Cancelled; delivery may be unknown. No automatic retry.'
    except Exception:
        code, error = 1, 'Backend write permission unavailable; delivery may be unknown. No direct fallback or automatic retry.'
    emit('action.error', action=args.command, ok=False, summary=error, error=error)
    return code, {'ok': False, 'action': args.command, 'error': error}


def main(argv=None):
    args = legacy.build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    # Missing authority never comes from .env; read subprocesses get no token.
    env[fence.TOKEN_ENV] = os.environ.get(fence.TOKEN_ENV, '') if args.command in WRITES else ''
    legacy.load_environment(args.project_root, args.operation_root, env)
    adapter = DeviceVendorAdapter(operation_root=args.operation_root, project_root=args.project_root,
                                  env=env, run=subprocess.run)
    code, payload = execute(args, adapter=adapter, emit=legacy.LifecycleBridge(env))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code
