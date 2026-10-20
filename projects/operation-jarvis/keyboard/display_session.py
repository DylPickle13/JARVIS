#!/usr/bin/env python3
"""Bounded child helper. Never unlocks, types credentials, or sleeps the computer.

SACLockScreenImmediate is a private macOS API: verify the resulting session lock
before display sleep, and fail closed if a macOS update removes it.
"""
import ctypes as C
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time


def locked():
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cg.CGSessionCopyCurrentDictionary.restype = C.c_void_p
    cf.CFStringCreateWithCString.argtypes = [C.c_void_p, C.c_char_p, C.c_uint32]
    cf.CFStringCreateWithCString.restype = C.c_void_p
    cf.CFDictionaryGetValue.argtypes = [C.c_void_p, C.c_void_p]
    cf.CFDictionaryGetValue.restype = C.c_void_p
    cf.CFBooleanGetValue.argtypes = [C.c_void_p]
    cf.CFBooleanGetValue.restype = C.c_bool
    cf.CFRelease.argtypes = [C.c_void_p]
    session = cg.CGSessionCopyCurrentDictionary()
    key = cf.CFStringCreateWithCString(None, b'CGSSessionScreenIsLocked', 0x08000100)
    try:
        if not session or not key:
            raise RuntimeError('Session unavailable')
        value = cf.CFDictionaryGetValue(session, key)
        return bool(value and cf.CFBooleanGetValue(value))
    finally:
        if key:
            cf.CFRelease(key)
        if session:
            cf.CFRelease(session)


def observe():
    """Read actual online-display power and session lock; never wake a display."""
    cg = C.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cg.CGGetOnlineDisplayList.argtypes = [C.c_uint32, C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)]
    cg.CGGetOnlineDisplayList.restype = C.c_int
    cg.CGDisplayIsAsleep.argtypes = [C.c_uint32]
    cg.CGDisplayIsAsleep.restype = C.c_uint32
    displays = (C.c_uint32 * 32)(); count = C.c_uint32()
    if cg.CGGetOnlineDisplayList(32, displays, C.byref(count)) or not 0 < count.value < 32:
        raise RuntimeError('Display observation unavailable')
    sleeping = all(bool(cg.CGDisplayIsAsleep(displays[i])) for i in range(count.value))
    return {'locked': locked(), 'all_asleep': sleeping, 'idle': True}


@contextlib.contextmanager
def action_lock():
    import cycle
    store = cycle.Store(cycle.RUNTIME)
    fd = store.open_private('display-action.lock', os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def perform(action):
    if action == 'lock-sleep':
        if not locked():
            login = C.CDLL('/System/Library/PrivateFrameworks/login.framework/Versions/Current/login')
            login.SACLockScreenImmediate.argtypes = []
            login.SACLockScreenImmediate.restype = None
            login.SACLockScreenImmediate()
        for _ in range(20):
            if locked():
                subprocess.run(['/usr/bin/pmset', 'displaysleepnow'], check=True,
                               capture_output=True, timeout=3)
                return
            time.sleep(0.1)
        raise RuntimeError('Lock not confirmed; display sleep withheld')
    if action == 'wake':
        cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        io = C.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        cf.CFStringCreateWithCString.argtypes = [C.c_void_p, C.c_char_p, C.c_uint32]
        cf.CFStringCreateWithCString.restype = C.c_void_p
        cf.CFRelease.argtypes = [C.c_void_p]
        io.IOPMAssertionDeclareUserActivity.argtypes = [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)]
        io.IOPMAssertionDeclareUserActivity.restype = C.c_int
        reason = cf.CFStringCreateWithCString(None, b'JARVIS basement arrival', 0x08000100)
        if not reason:
            raise RuntimeError('Wake reason unavailable')
        try:
            assertion = C.c_uint32(0)
            if io.IOPMAssertionDeclareUserActivity(reason, 0, C.byref(assertion)) != 0:
                raise RuntimeError('Display wake rejected')
        finally:
            cf.CFRelease(reason)
        return
    raise ValueError('Unknown action')


if __name__ == '__main__':
    try:
        with action_lock():
            if len(sys.argv) == 2 and sys.argv[1] == 'status':
                print('locked' if locked() else 'unlocked')
            elif len(sys.argv) == 2 and sys.argv[1] == 'observe':
                print(json.dumps(observe()))
            else:
                perform(sys.argv[1])
    except Exception:
        print('Display session operation unavailable; reconcile actual state before another action.', file=sys.stderr)
        sys.exit(1)
