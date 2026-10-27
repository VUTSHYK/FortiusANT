"""WFTNP diagnostics use the existing FortiusANT debug mask and logfile."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pythoncode"))
import debug
from wftnpTransport import _diagnostic


class DiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        debug.deactivate()

    def test_disabled_diagnostics_are_silent(self):
        debug.deactivate()
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("connected")
            _diagnostic("raw", raw=True)
        write.assert_not_called()

    def test_normal_diagnostics_use_central_logfile(self):
        debug.activate(debug.WFTNP)
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("connected")
            _diagnostic("raw", raw=True)
        write.assert_called_once_with("[WFTNP] connected")

    def test_raw_diagnostics_are_independent(self):
        debug.activate(debug.WFTNP_RAW)
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("connected")
            _diagnostic("05 01", raw=True)
        write.assert_called_once_with("[WFTNP] 05 01")


if __name__ == "__main__":
    unittest.main()
