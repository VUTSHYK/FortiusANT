"""Transport-independent FTMS bridge for FortiusANT.

This module deliberately has no BLE, WFTNP, ANT+ or asyncio dependencies.
It mirrors the telemetry and command fields consumed by FortiusAntBody.
Network I/O and lifecycle are the responsibility of a future WFTNP adapter.
"""

from dataclasses import dataclass
from enum import Enum


class TrainerMode(Enum):
    POWER = "power"
    GRADE = "grade"


@dataclass(frozen=True)
class TrainerTelemetry:
    speed_kmh: float
    cadence_rpm: float
    power_watts: float
    heart_rate_bpm: int = 0


@dataclass(frozen=True)
class TrainerCommand:
    mode: TrainerMode
    target_power_watts: int | None = None
    target_grade_percent: float | None = None
    rolling_resistance: float | None = None
    wind_resistance: float | None = None
    wind_speed_mps: float | None = None


class FTMSBridge:
    """Mailbox between the main trainer loop and a transport.

    Only the trainer loop should consume pending commands. Transport callbacks
    may publish a command; synchronization must be supplied by the adapter
    when those callbacks run on another thread.
    """

    def __init__(self):
        self.telemetry = TrainerTelemetry(0.0, 0.0, 0.0)
        self._pending_command = None

    def set_trainer_data(self, speed_kmh, cadence_rpm, power_watts):
        old = self.telemetry
        self.telemetry = TrainerTelemetry(
            speed_kmh, cadence_rpm, power_watts, old.heart_rate_bpm
        )

    def set_athlete_data(self, heart_rate_bpm):
        old = self.telemetry
        self.telemetry = TrainerTelemetry(
            old.speed_kmh, old.cadence_rpm, old.power_watts, heart_rate_bpm
        )

    def submit_command(self, command):
        if not isinstance(command, TrainerCommand):
            raise TypeError("command must be a TrainerCommand")
        self._pending_command = command

    def take_command(self):
        command = self._pending_command
        self._pending_command = None
        return command
