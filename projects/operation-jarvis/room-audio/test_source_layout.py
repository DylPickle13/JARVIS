"""Offline source-layout checks; no service imports, devices, or private state."""
import ast
from pathlib import Path
import unittest


ROOM = Path(__file__).resolve().parent
OPERATION = ROOM.parent
ROOT = OPERATION.parents[1]


def path_constants(script, names):
    """Evaluate only named path assignments, not module startup side effects."""
    namespace = {"Path": Path, "__file__": str(script)}
    for node in ast.parse(script.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in names:
                namespace[target.id] = eval(
                    compile(ast.Expression(node.value), str(script), "eval"), namespace
                )
    return namespace


class SourceLayoutTests(unittest.TestCase):
    def test_canonical_roots(self):
        for source in (ROOM,):
            for script in ("macos_room_audio_service.py", "camera_room_audio_service.py",
                           "room_session10_service.py"):
                with self.subTest(source=source, script=script):
                    values = path_constants(source / script, {"ROOM", "ROOT", "OPERATION", "SECURITY"})
                    self.assertEqual(values["ROOT"], ROOT)
            values = path_constants(source / "room_audio_camera.py", {"SECURITY"})
            self.assertEqual(values["SECURITY"], OPERATION / "security")

    def test_retired_files_removed(self):
        retired = OPERATION / "raspberry-pi"
        self.assertFalse(retired.exists())
        installer = ROOM / "scripts/install-macos-room-audio.sh"
        self.assertTrue(installer.is_file())
        self.assertEqual((installer.parent / "../../../..").resolve(), ROOT)


if __name__ == "__main__":
    unittest.main()
