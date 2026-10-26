"""FortiusANT-facing adapter for the transport-independent FTMS mailbox.

A WFTNP server can publish TrainerCommand objects and read telemetry via
the bridge. The synchronous trainer loop uses familiar bleBless-style
methods without importing asyncio or networking libraries.
"""

from constants import mode_Grade, mode_Power
from ftmsBridge import FTMSBridge, TrainerMode


class FTMSWftnpAdapter:
    def __init__(self, bridge=None):
        self.bridge = bridge if bridge is not None else FTMSBridge()
        self.TargetMode = None
        self.TargetPower = 0
        self.TargetGrade = 0.0
        self.WindResistance = 0.0
        self.WindSpeed = 0.0
        self.DraftingFactor = 0.0
        self.RollingResistance = 0.0
        self.SteeringAngle = None

    def SetAthleteData(self, heart_rate):
        self.bridge.set_athlete_data(heart_rate)

    def SetTrainerData(self, speed_kmh, cadence, power):
        self.bridge.set_trainer_data(speed_kmh, cadence, power)

    def SetSteeringAngle(self, angle):
        self.SteeringAngle = angle

    def Refresh(self):
        """Apply at most one pending command; True only when one was received."""
        command = self.bridge.take_command()
        if command is None:
            return False

        if command.mode is TrainerMode.POWER:
            if command.target_power_watts is None:
                raise ValueError("POWER command requires target_power_watts")
            self.TargetMode = mode_Power
            self.TargetPower = command.target_power_watts
        elif command.mode is TrainerMode.GRADE:
            if command.target_grade_percent is None:
                raise ValueError("GRADE command requires target_grade_percent")
            self.TargetMode = mode_Grade
            self.TargetGrade = command.target_grade_percent
        else:
            raise ValueError("Unsupported trainer mode")

        if command.rolling_resistance is not None:
            self.RollingResistance = command.rolling_resistance
        if command.wind_resistance is not None:
            self.WindResistance = command.wind_resistance
        if command.wind_speed_mps is not None:
            self.WindSpeed = command.wind_speed_mps
        return True
