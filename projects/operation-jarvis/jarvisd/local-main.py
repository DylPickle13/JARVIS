#!/usr/bin/env python3
"""Production CLI-first mode; no durable ownership activation or SDK fences."""
import jarvisd

if __name__ == '__main__':
    raise SystemExit(jarvisd.main(local_control=True))
