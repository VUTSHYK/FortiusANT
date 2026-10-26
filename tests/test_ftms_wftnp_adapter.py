"""Tests for the FortiusANT-facing FTMS WFTNP adapter."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from constants import mode_Grade, mode_Power
from ftmsBridge import TrainerCommand, TrainerMode
from ftmsWftnpAdapter import FTMSWftnpAdapter


class TestFTMSWftnpAdapter(unittest.TestCase):
    def test_telemetry_is_forwarded(self):
        adapter = FTMSWftnpAdapter()
        adapter.SetAthleteData(145)
        adapter.SetTrainerData(30.5, 85, 210)
        snapshot = adapter.bridge.get_telemetry()
        self.assertEqual((snapshot.heart_rate_bpm, snapshot.power_watts), (145, 210))

    def test_no_command_means_no_refresh(self):
        self.assertFalse(FTMSWftnpAdapter().Refresh())

    def test_erg_command(self):
        adapter = FTMSWftnpAdapter()
        adapter.bridge.submit_command(TrainerCommand(TrainerMode.POWER, target_power_watts=230))
        self.assertTrue(adapter.Refresh())
        self.assertEqual(adapter.TargetMode, mode_Power)
        self.assertEqual(adapter.TargetPower, 230)
        self.assertFalse(adapter.Refresh())

    def test_grade_command(self):
        adapter = FTMSWftnpAdapter()
        adapter.bridge.submit_command(TrainerCommand(
            TrainerMode.GRADE, target_grade_percent=5.5, rolling_resistance=0.004
        ))
        self.assertTrue(adapter.Refresh())
        self.assertEqual(adapter.TargetMode, mode_Grade)
        self.assertEqual(adapter.TargetGrade, 5.5)
        self.assertEqual(adapter.RollingResistance, 0.004)

    def test_missing_target_rejected(self):
        adapter = FTMSWftnpAdapter()
        adapter.bridge.submit_command(TrainerCommand(TrainerMode.POWER))
        with self.assertRaises(ValueError):
            adapter.Refresh()


if __name__ == "__main__":
    unittest.main()
