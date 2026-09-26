"""Private scheduled jobs and notification delivery, owned by Operation JARVIS.

The CLI/launchd worker runs independently of the jarvisd HTTP process.
Importing this package does not open databases or start workers.
"""
