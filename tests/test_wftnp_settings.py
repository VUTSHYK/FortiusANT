"""Read actual FortiusAntSettings.json through the production settings loader."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))
import settings


class TestWftnpSettings(unittest.TestCase):
    def test_saved_wftnp_selection_and_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "FortiusAntSettings.json"
            path.write_text(json.dumps({
                "version": settings.Version,
                "bluetooth": {
                    "nodejs": False,
                    "bless": False,
                    "wftnp": True,
                    "wftnp host": "127.0.0.1",
                    "wftnp port": 36867,
                    "wftnp idle timeout": 120,
                },
            }), encoding="utf-8")
            args = SimpleNamespace(
                debug=None, antDeviceID=None, factor=None, TacxType=False,
                Steering=None, GradeAdjust=False, Runoff=False,
                ble=False, bless=False, wftnp=False,
                wftnp_host="0.0.0.0", wftnp_port=36866,
                wftnpIdleTimeout=3600,
            )
            with patch.object(settings, "JsonFileName", return_value=str(path)):
                self.assertTrue(settings.ReadJsonFile(args))
            self.assertTrue(args.wftnp)
            self.assertFalse(args.ble)
            self.assertFalse(args.bless)
            self.assertEqual(args.wftnp_host, "127.0.0.1")
            self.assertEqual(args.wftnp_port, 36867)
            self.assertEqual(args.wftnpIdleTimeout, 120)


if __name__ == "__main__":
    unittest.main()
