"""Transport-independent FTMS bridge for FortiusANT.

This module deliberately has no BLE, WFTNP, ANT+ or asyncio dependencies.
It mirrors the telemetry and command fields consumed by FortiusAntBody.
Network I/O and lifecycle are the responsibility of a future WFTNP adapter.
"""

from dataclasses import dataclass
from enum import Enum
from queue import Empty, Full, Queue
from threading import Lock


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
    may publish a command from another thread. Commands are kept in a bounded
    FIFO queue, while telemetry snapshots are protected by a lock.
    """

    def __init__(self):
        self.telemetry = TrainerTelemetry(0.0, 0.0, 0.0)
        self._commands = Queue(maxsize=64)
        self._lock = Lock()

    def set_trainer_data(self, speed_kmh, cadence_rpm, power_watts):
        with self._lock:
            old = self.telemetry
            self.telemetry = TrainerTelemetry(
                speed_kmh, cadence_rpm, power_watts, old.heart_rate_bpm
            )

    def set_athlete_data(self, heart_rate_bpm):
        with self._lock:
            old = self.telemetry
            self.telemetry = TrainerTelemetry(
                old.speed_kmh, old.cadence_rpm, old.power_watts, heart_rate_bpm
            )

    def get_telemetry(self):
        with self._lock:
            return self.telemetry

    def submit_command(self, command):
        if not isinstance(command, TrainerCommand):
            raise TypeError("command must be a TrainerCommand")
        try:
            self._commands.put_nowait(command)
        except Full as exc:
            raise OverflowError("FTMS command queue is full") from exc

    def discard_commands(self):
        """Discard commands pending when control ownership is released."""
        with self._commands.mutex:
            self._commands.queue.clear()
            self._commands.not_full.notify_all()

    def take_command(self):
        try:
            return self._commands.get_nowait()
        except Empty:
            return None
