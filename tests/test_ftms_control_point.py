"""FTMS Control Point ownership and command validation tests."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from ftmsBridge import FTMSBridge, TrainerMode
from ftmsControlPoint import FTMSControlPoint


class TestFTMSControlPoint(unittest.TestCase):
    def setUp(self):
        self.bridge = FTMSBridge()
        self.control = FTMSControlPoint(self.bridge)

    def test_request_control_then_erg(self):
        self.assertEqual(self.control.handle(b"\x00"), b"\x80\x00\x01")
        self.assertEqual(self.control.handle(b"\x05" + struct.pack("<h", 225)), b"\x80\x05\x01")
        command = self.bridge.take_command()
        self.assertEqual(command.mode, TrainerMode.POWER)
        self.assertEqual(command.target_power_watts, 225)

    def test_ownership_required(self):
        self.assertEqual(self.control.handle(b"\x05" + struct.pack("<h", 225)), b"\x80\x05\x05")
        self.assertIsNone(self.bridge.take_command())

    def test_simulation_scaling(self):
        self.control.handle(b"\x00")
        request = b"\x11" + struct.pack("<hhBB", 1500, 625, 40, 50)
        self.assertEqual(self.control.handle(request), b"\x80\x11\x01")
        command = self.bridge.take_command()
        self.assertEqual(command.mode, TrainerMode.GRADE)
        self.assertEqual(command.target_grade_percent, 6.25)
        self.assertEqual(command.wind_speed_mps, 1.5)
        self.assertEqual(command.rolling_resistance, 0.004)
        self.assertEqual(command.wind_resistance, 0.5)

    def test_reset_revokes_control(self):
        self.control.handle(b"\x00")
        self.assertEqual(self.control.handle(b"\x01"), b"\x80\x01\x01")
        self.assertEqual(self.control.handle(b"\x05\x64\x00"), b"\x80\x05\x05")

    def test_two_connections_and_owner_disconnect(self):
        first, second = object(), object()
        self.assertEqual(self.control.handle_connection(first, b"\x00"), b"\x80\x00\x01")
        self.assertEqual(self.control.handle_connection(first, b"\x00"), b"\x80\x00\x01")
        self.assertEqual(self.control.handle_connection(second, b"\x00"), b"\x80\x00\x05")
        self.assertEqual(self.control.handle_connection(second, b"\x05\x64\x00"), b"\x80\x05\x05")
        self.assertIsNone(self.bridge.take_command())
        self.assertEqual(self.control.handle_connection(first, b"\x05\x64\x00"), b"\x80\x05\x01")
        self.control.release(second)
        self.assertEqual(self.control.handle_connection(second, b"\x00"), b"\x80\x00\x05")
        self.control.release(first)
        self.assertIsNone(self.bridge.take_command())
        self.assertEqual(self.control.handle_connection(second, b"\x00"), b"\x80\x00\x01")

    def test_invalid_requests(self):
        self.assertEqual(self.control.handle(b""), b"\x80\x00\x03")
        self.assertEqual(self.control.handle(b"\xff"), b"\x80\xff\x02")
        self.assertEqual(self.control.handle(b"\x00\x00"), b"\x80\x00\x03")


if __name__ == "__main__":
    unittest.main()
