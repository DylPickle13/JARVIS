"""Compile-only IOKit feasibility and cross-language encoder tests. No HID calls."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import ajazz

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang++'), 'macOS compiler required')
class PrototypeTests(unittest.TestCase):
    def test_bridge_journal_and_requests(self):
        vendor = ROOT / 'karabiner/upstream/vendor/vendor/include'
        if not (vendor / 'nlohmann/json.hpp').exists():
            self.skipTest('Pinned upstream checkout required for bridge C++ tests')
        with tempfile.TemporaryDirectory() as directory:
            executable = pathlib.Path(directory) / 'test_bridge'
            subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-g', '-I', str(vendor),
                            str(ROOT / 'karabiner/prototype/test_bridge.cpp'),
                            '-framework', 'IOKit', '-framework', 'CoreFoundation',
                            '-o', str(executable)], check=True, capture_output=True, timeout=60)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=15)

    def test_async_lifecycle_with_fake_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = pathlib.Path(directory) / 'test_async'
            subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-g',
                            str(ROOT / 'karabiner/prototype/test_async.cpp'),
                            '-framework', 'IOKit', '-framework', 'CoreFoundation',
                            '-o', str(executable)], check=True, capture_output=True, timeout=60)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)

    def test_cpp_matches_python_and_rejects_invalid_settings(self):
        source = r'''
#include "ak820_lighting.hpp"
#include <cstdio>
int main() {
  using namespace jarvis::ak820;
  for (int effect = 1; effect <= 18; ++effect) {
    if (effect == 6) continue;
    for (int b = 0; b < 5; ++b)
      for (int s = 0; s < 5; ++s)
        for (int d = 0; d < 2; ++d)
          for (int rainbow = 0; rainbow < 2; ++rainbow) {
            auto r = encode({effect, b, s, d, bool(rainbow), {0x99, 0x33, 0xff}});
            if (!r) return 1;
            for (auto byte : *r) std::printf("%02x", byte);
            std::puts("");
          }
  }
  for (auto s : {settings{6,0,0,0,false,{}}, settings{0,0,0,0,false,{}},
                 settings{19,0,0,0,false,{}}, settings{1,-1,0,0,false,{}},
                 settings{1,5,0,0,false,{}}, settings{1,0,-1,0,false,{}},
                 settings{1,0,5,0,false,{}}, settings{1,0,0,-1,false,{}},
                 settings{1,0,0,2,false,{}}}) {
    if (encode(s)) return 2;
  }
  // Null-device rejection must not invoke IOKit writes.
  if (send_on_owned_device(nullptr, {1,0,0,0,false,{}}).status != outcome::rejected) return 3;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'test.cpp').write_text(source)
            subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'karabiner/prototype'), str(path / 'test.cpp'),
                            '-framework', 'IOKit', '-framework', 'CoreFoundation',
                            '-o', str(path / 'test')], check=True, capture_output=True, timeout=60)
            actual = subprocess.run([str(path / 'test')], check=True, capture_output=True,
                                    text=True, timeout=10).stdout.splitlines()
        expected = [ajazz.report(dict(effect=e, brightness=b, speed=s, direction=d,
                                      color='rainbow' if rainbow else '#9933FF')).hex()
                    for e in ajazz.EFFECTS for b in ajazz.BRIGHTNESS for s in ajazz.SPEED
                    for d in ajazz.DIRECTION for rainbow in (False, True)]
        self.assertEqual(actual, expected)
