"""Regression checks for removal of the legacy Node.js / TCP transport.

These checks are deliberately dependency-free: they can run on GitHub Actions
without Bluetooth hardware, wxPython, or ANT dongles.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "pythoncode"


class TransportCleanupTests(unittest.TestCase):
    def test_all_python_modules_compile(self):
        for path in PYTHON.rglob("*.py"):
            with self.subTest(path=str(path.relative_to(ROOT))):
                compile(path.read_bytes(), str(path), "exec")

    def test_legacy_transport_modules_removed(self):
        for name in ("bleDongle.py", "dircon_server.py"):
            with self.subTest(name=name):
                self.assertFalse((PYTHON / name).exists())

    def test_runtime_uses_bless_not_legacy_transport(self):
        body = (PYTHON / "FortiusAntBody.py").read_text(encoding="utf-8")
        main = (PYTHON / "FortiusAnt.py").read_text(encoding="utf-8")
        self.assertNotIn("bleDongle", body + main)
        self.assertNotIn("dircon_server", body + main)
        self.assertIn("bleBless.clsFTMS_bless(True)", body)
        self.assertIn("if clv.ble:", body)
        self.assertNotIn("clv.bless", body)

    def test_bless_uses_python_library_not_node(self):
        for name in ("bleBless.py", "bleBlessClass.py"):
            with self.subTest(name=name):
                tree = ast.parse((PYTHON / name).read_text(encoding="utf-8"))
                modules = {
                    alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names
                } | {
                    node.module for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                }
                self.assertIn("bless", modules)
                self.assertNotIn("subprocess", modules)
                self.assertNotIn("bleDongle", modules)


if __name__ == "__main__":
    unittest.main()
