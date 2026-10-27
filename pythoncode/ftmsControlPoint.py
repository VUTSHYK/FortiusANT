"""FTMS Control Point validation and trainer mailbox dispatch.

The transport's WRITE acknowledgement is distinct from the FTMS result
notification. Commands reach the trainer only through FTMSBridge.
"""

import struct
from threading import RLock

from ftmsBridge import TrainerCommand, TrainerMode


class FTMSControlPoint:
    REQUEST_CONTROL = 0x00
    RESET = 0x01
    SET_TARGET_POWER = 0x05
    SET_SIMULATION = 0x11

    SUCCESS = 0x01
    NOT_SUPPORTED = 0x02
    INVALID_PARAMETER = 0x03
    OPERATION_FAILED = 0x04
    CONTROL_NOT_PERMITTED = 0x05

    def __init__(self, bridge):
        self.bridge = bridge
        self.has_control = False
        self.controller_connection = None
        self._lock = RLock()

    def release(self, connection=None):
        with self._lock:
            if connection is None or connection is self.controller_connection:
                self.has_control = False
                self.controller_connection = None
                self.bridge.discard_commands()

    def handle_connection(self, connection, request):
        with self._lock:
            opcode = request[0] if request else 0
            result = self._apply(request, connection)
            return bytes((0x80, opcode, result))

    def handle(self, request):
        """Return FTMS response bytes; queue only accepted trainer commands."""
        return self.handle_connection(None, request)

    def _apply(self, request, connection):
        if not request:
            return self.INVALID_PARAMETER
        opcode = request[0]
        sizes = {
            self.REQUEST_CONTROL: 1,
            self.RESET: 1,
            self.SET_TARGET_POWER: 3,
            self.SET_SIMULATION: 7,
        }
        if opcode not in sizes:
            return self.NOT_SUPPORTED
        if len(request) != sizes[opcode]:
            return self.INVALID_PARAMETER
        if opcode == self.REQUEST_CONTROL:
            if self.has_control and connection is not self.controller_connection:
                return self.CONTROL_NOT_PERMITTED
            self.has_control = True
            self.controller_connection = connection
            return self.SUCCESS
        if not self.has_control or connection is not self.controller_connection:
            return self.CONTROL_NOT_PERMITTED
        if opcode == self.RESET:
            self.release()
            return self.SUCCESS
        if opcode == self.SET_TARGET_POWER:
            power = struct.unpack_from("<h", request, 1)[0]
            if power < 0:
                return self.INVALID_PARAMETER
            command = TrainerCommand(TrainerMode.POWER, target_power_watts=power)
        else:
            wind, grade, rolling, resistance = struct.unpack_from("<hhBB", request, 1)
            command = TrainerCommand(
                TrainerMode.GRADE,
                target_grade_percent=grade / 100,
                wind_speed_mps=wind / 1000,
                rolling_resistance=rolling / 10000,
                wind_resistance=resistance / 100,
            )
        try:
            self.bridge.submit_command(command)
        except OverflowError:
            return self.OPERATION_FAILED
        return self.SUCCESS
