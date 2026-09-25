#!/usr/bin/env python3
"""Compatibility installer for the optional Raspberry Pi fullscreen adapter."""
from install import install, remove_retired

if __name__ == '__main__':
    install('ssh', pi_desktop=True)
