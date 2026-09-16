#!/usr/bin/env python3
"""Run real host prompt code with injected fixtures; no devices, Keychain, or network."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='jarvis-prompt-tests-') as temp:
    package = Path(temp)
    sources = package / 'Tests'
    sources.mkdir()
    for name in ['JARVISPromptRuntime.swift', 'JARVISTerminalConfigurationStore.swift']:
        shutil.copy2(root / 'HostAppIntents' / name, sources / name)
    shutil.copy2(Path(__file__).with_name('PromptRuntimeChecks.swift'), sources)
    kit = json.dumps(str(root / 'JARVISKit'))
    (package / 'Package.swift').write_text(f'''// swift-tools-version:5.9
import PackageDescription
let package = Package(name: "PromptRuntimeChecks", platforms: [.macOS(.v13)],
    dependencies: [.package(path: {kit})],
    targets: [.testTarget(name: "PromptRuntimeChecks", dependencies: [.product(name: "JARVISKit", package: "JARVISKit")], path: "Tests")])
''')
    subprocess.run(['swift', 'test', '--package-path', str(package)], check=True)
