"""Unit tests for the transport-neutral FTMS bridge."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from ftmsBridge import FTMSBridge, TrainerCommand, TrainerMode


class TestFTMSBridge(unittest.TestCase):
    def test_telemetry_keeps_heart_rate(self):
        bridge = FTMSBridge()
        bridge.set_athlete_data(142)
        bridge.set_trainer_data(36.5, 91, 250)
        self.assertEqual(bridge.telemetry.speed_kmh, 36.5)
        self.assertEqual(bridge.telemetry.cadence_rpm, 91)
        self.assertEqual(bridge.telemetry.power_watts, 250)
        self.assertEqual(bridge.telemetry.heart_rate_bpm, 142)

    def test_command_is_consumed_once(self):
        bridge = FTMSBridge()
        command = TrainerCommand(TrainerMode.POWER, target_power_watts=250)
        bridge.submit_command(command)
        self.assertEqual(bridge.take_command(), command)
        self.assertIsNone(bridge.take_command())

    def test_grade_command_preserves_environment(self):
        bridge = FTMSBridge()
        command = TrainerCommand(
            TrainerMode.GRADE,
            target_grade_percent=6.0,
            rolling_resistance=0.004,
            wind_resistance=0.51,
            wind_speed_mps=0.0,
        )
        bridge.submit_command(command)
        self.assertEqual(bridge.take_command(), command)

    def test_commands_keep_fifo_order(self):
        bridge = FTMSBridge()
        first = TrainerCommand(TrainerMode.POWER, target_power_watts=150)
        second = TrainerCommand(TrainerMode.POWER, target_power_watts=250)
        bridge.submit_command(first)
        bridge.submit_command(second)
        self.assertEqual(bridge.take_command(), first)
        self.assertEqual(bridge.take_command(), second)
        self.assertIsNone(bridge.take_command())

    def test_queue_is_bounded(self):
        bridge = FTMSBridge()
        command = TrainerCommand(TrainerMode.POWER, target_power_watts=100)
        for _ in range(64):
            bridge.submit_command(command)
        with self.assertRaises(OverflowError):
            bridge.submit_command(command)

    def test_telemetry_snapshot(self):
        bridge = FTMSBridge()
        bridge.set_athlete_data(130)
        bridge.set_trainer_data(25.0, 80.0, 180.0)
        self.assertEqual(bridge.get_telemetry(), bridge.telemetry)

    def test_invalid_command_rejected(self):
        with self.assertRaises(TypeError):
            FTMSBridge().submit_command("250 watts")


if __name__ == "__main__":
    unittest.main()
