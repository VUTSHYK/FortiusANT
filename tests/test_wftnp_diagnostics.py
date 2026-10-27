"""WFTNP diagnostics use the existing FortiusANT debug mask and logfile."""
import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pythoncode"))
import debug
import logfile
from wftnpTransport import WftnpFTMSTransport
from wftnpTransport import _diagnostic


class DiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        debug.deactivate()

    def test_wftnp_log_is_written_to_real_file(self):
        """Verify disk output, not just that a mocked logger was called."""
        with tempfile.TemporaryDirectory() as directory:
            with patch("logfile.datetime") as clock:
                from datetime import datetime
                clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
                with patch("logfile.UsePythonLogging", False), patch("logfile.LogfileCreated", False):
                    debug.activate(debug.WFTNP)
                    prefix = str(Path(directory) / "FortiusAnt-test")
                    logfile.Open(prefix=prefix)
                    try:
                        _diagnostic("TCP listening on 127.0.0.1:36866")
                    finally:
                        logfile.fLogfile.close()
                    contents = Path(prefix + ".2026-01-02 03-04-05.log").read_text()
                    self.assertIn("[WFTNP] TCP listening on 127.0.0.1:36866", contents)

    def test_ftms_control_write_emits_diagnostics(self):
        """Exercise the transport's real control-write path with a fake server."""
        import asyncio
        from unittest.mock import AsyncMock

        async def exercise():
            transport = WftnpFTMSTransport(on_control_write=lambda data: bytes([0x80, data[0], 0x01]))
            transport.server = type("Server", (), {"notify_connection": AsyncMock()})()
            connection = object()
            await transport._handle_control_write(connection, bytes([0x00]))
            transport.server.notify_connection.assert_awaited_once()
        debug.activate(debug.WFTNP | debug.WFTNP_RAW)
        with patch("wftnpTransport.logfile.Write") as write:
            asyncio.run(exercise())
        messages = [call.args[0] for call in write.call_args_list]
        self.assertIn("[WFTNP] FTMS control write: 00", messages)
        self.assertIn("[WFTNP] FTMS control opcode: 0x00", messages)
        self.assertIn("[WFTNP] FTMS response: 80 00 01", messages)

    def test_other_debug_category_does_not_enable_wftnp(self):
        debug.activate(debug.Application | debug.Function)
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("connected")
            _diagnostic("raw", raw=True)
        write.assert_not_called()

    def test_combined_debug_bits_keep_wftnp_and_other_categories(self):
        """WFTNP must work alongside unrelated FortiusANT debug flags."""
        mask = debug.WFTNP | debug.WFTNP_RAW | debug.Application | debug.Ble | debug.Performance
        self.assertEqual(mask, 24769)
        debug.activate(mask)
        for flag in (debug.WFTNP, debug.WFTNP_RAW, debug.Application, debug.Ble, debug.Performance):
            self.assertTrue(debug.on(flag))
        self.assertFalse(debug.on(debug.Data1))
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("connected")
            _diagnostic("01 02", raw=True)
        self.assertEqual([c.args[0] for c in write.call_args_list],
                         ["[WFTNP] connected", "[WFTNP] 01 02"])

    def test_all_debug_bits_enable_both_wftnp_modes(self):
        debug.activate(debug.All)
        self.assertEqual(debug.All, 65535)
        with patch("wftnpTransport.logfile.Write") as write:
            _diagnostic("all enabled")
            _diagnostic("ff", raw=True)
        self.assertEqual([c.args[0] for c in write.call_args_list],
                         ["[WFTNP] all enabled", "[WFTNP] ff"])

    def test_wftnp_logfile_with_combined_mask(self):
        """Combined debug bits must still write a real WFTNP log record."""
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            with patch("logfile.datetime") as clock:
                clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
                with patch("logfile.UsePythonLogging", False), patch("logfile.LogfileCreated", False):
                    debug.activate(debug.WFTNP | debug.Application | debug.Ble)
                    prefix = str(Path(directory) / "combined")
                    logfile.Open(prefix=prefix)
                    try:
                        _diagnostic("combined categories")
                    finally:
                        logfile.fLogfile.close()
                    contents = Path(prefix + ".2026-01-02 03-04-05.log").read_text()
                    self.assertIn("[WFTNP] combined categories", contents)

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
