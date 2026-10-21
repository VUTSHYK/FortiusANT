# ---------------------------------------------------------------------------
# Python-only WFTNP bridge for FortiusANT.
#
# This module intentionally keeps the same high-level surface used by the older
# bleDongle.py implementation (Open/Write/Read/Close + clsBleCTP.Refresh()),
# but replaces the HTTP/Node transport with a direct WFTNP (Wahoo Direct
# Connect / Wahoo Fitness TNP) implementation.
#
# It is meant as a drop-in replacement for the legacy Node.js bridge, not as a
# full hardware-validated Wahoo FTMS stack.
# ---------------------------------------------------------------------------

from __future__ import annotations

import os
import socket
import struct
import time
import uuid

try:
    from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
except Exception:  # pragma: no cover
    ServiceBrowser = None
    ServiceInfo = None
    Zeroconf = None

from constants import mode_Power, mode_Grade, UseBluetooth
import debug
import logfile


FTMS_SERVICE_UUID = uuid.UUID("00001826-0000-1000-8000-00805f9b34fb")
FTMS_CONTROL_POINT_UUID = uuid.UUID("00002AD9-0000-1000-8000-00805F9B34FB")
INDOOR_BIKE_DATA_UUID = uuid.UUID("00002AD2-0000-1000-8000-00805F9B34FB")

WFTNP_VERSION = 1
WFTNP_HEADER = struct.Struct("!BBBBH")


class WFTNPError(RuntimeError):
    pass


class _WahooDiscoveryListener:
    def __init__(self):
        self.discovered = []

    def add_service(self, zc, type_, name):
        if ServiceInfo is None:
            return
        info = zc.get_service_info(type_, name)
        if not info:
            return
        host = None
        if info.parsed_addresses:
            host = info.parsed_addresses[0]
            host = socket.inet_ntoa(struct.pack(">L", host))
        if host is None:
            host = "127.0.0.1"
        self.discovered.append((host, info.port, name))

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)


class clsWftnpBridge:
    """Low-level WFTNP socket wrapper used by clsBleInterface."""

    def __init__(self, host="127.0.0.1", port=36866):
        self.host = host
        self.port = int(port)
        self.sock = None
        self.seq = 0
        self.pending = {}

    def _next_seq(self):
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    def discover(self):
        if Zeroconf is None or ServiceBrowser is None:
            return [(self.host, self.port, "localhost")]

        zc = Zeroconf()
        listener = _WahooDiscoveryListener()
        try:
            ServiceBrowser(zc, "_wahoo-fitness-tnp._tcp.local.", listener)
            time.sleep(1.0)
        finally:
            try:
                zc.close()
            except Exception:
                pass

        if listener.discovered:
            return listener.discovered
        return [(self.host, self.port, "localhost")]

    def open(self):
        if self.sock is not None:
            return True

        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=2.0)
            self.sock.settimeout(2.0)
            return True
        except Exception as exc:  # pragma: no cover
            if debug.on(debug.Ble):
                logfile.Write("WFTNP open failed: %s" % exc)
            self.sock = None
            return False

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _request(self, opcode, payload=b""):
        if self.sock is None:
            raise WFTNPError("socket not open")
        seq = self._next_seq()
        header = WFTNP_HEADER.pack(WFTNP_VERSION, opcode, seq, 0, len(payload))
        frame = header + payload
        try:
            self.sock.sendall(frame)
        except Exception as exc:  # pragma: no cover
            raise WFTNPError(str(exc))

        # Read response header
        hdr = self.sock.recv(WFTNP_HEADER.size)
        if len(hdr) != WFTNP_HEADER.size:
            raise WFTNPError("short WFTNP header")

        version, response_opcode, response_seq, status, length = WFTNP_HEADER.unpack(hdr)
        if version != WFTNP_VERSION:
            raise WFTNPError("unsupported WFTNP version %s" % version)

        body = b""
        while len(body) < length:
            chunk = self.sock.recv(length - len(body))
            if not chunk:
                break
            body += chunk
        if len(body) != length:
            raise WFTNPError("short WFTNP payload")

        if status != 0:
            raise WFTNPError("WFTNP request failed: status=%s opcode=%s" % (status, response_opcode))

        return response_opcode, body

    def discover_services(self):
        _, payload = self._request(1, b"")
        return [uuid.UUID(bytes=payload[i: i + 16]) for i in range(0, len(payload), 16)]

    def discover_characteristics(self, service_uuid):
        _, payload = self._request(2, service_uuid.bytes)
        if len(payload) < 16:
            return []
        # Minimal decode: [uuid16.., props]
        items = []
        for i in range(0, len(payload), 17):
            if i + 17 <= len(payload):
                char_uuid = uuid.UUID(bytes=payload[i: i + 16])
                props = payload[i + 16]
                items.append((char_uuid, props))
        return items

    def read_characteristic(self, char_uuid):
        _, payload = self._request(3, char_uuid.bytes)
        if len(payload) >= 16 and payload[:16] == char_uuid.bytes:
            return payload[16:]
        return payload

    def write_characteristic(self, char_uuid, value):
        self._request(4, char_uuid.bytes + value)

    def subscribe(self, char_uuid):
        self._request(5, char_uuid.bytes + b'\x01')

    def _ftms_indoor_bike_data(self, event):
        flags = 0
        payload = []

        speed = event.get('speed', event.get('speed_kmh', 0.0))
        if speed is not None:
            try:
                speed_kmh = float(speed)
            except (TypeError, ValueError):
                speed_kmh = 0.0
            flags |= 1 << 0
            payload.append(struct.pack('<H', int(round(speed_kmh * 100.0))))

        cadence = event.get('cadence', 0)
        try:
            cadence = int(float(cadence))
        except (TypeError, ValueError):
            cadence = 0
        if cadence:
            flags |= 1 << 2
            payload.append(struct.pack('<H', int(round(cadence * 2.0))))

        power = event.get('watts', event.get('power', 0))
        try:
            power = int(float(power))
        except (TypeError, ValueError):
            power = 0
        if power:
            flags |= 1 << 6
            payload.append(struct.pack('<h', power))

        heart = event.get('heart_rate', 0)
        try:
            heart = int(float(heart))
        except (TypeError, ValueError):
            heart = 0
        if heart:
            flags |= 1 << 7
            payload.append(struct.pack('<B', heart))

        return struct.pack('<H', flags) + b''.join(payload)

    def notify_indoor_bike_data(self, event):
        if self.sock is None:
            return False
        payload = self._ftms_indoor_bike_data(event)
        try:
            self.write_characteristic(INDOOR_BIKE_DATA_UUID, payload)
        except Exception:
            return False
        return True


# ---------------------------------------------------------------------------
# Compatibility layer: same public surface as the legacy bleDongle.py
# ---------------------------------------------------------------------------
class clsBleInterface:
    def __init__(self, clv, host='127.0.0.1', port=36866):
        self.OK = False
        self.host = host
        self.port = port
        self.interface = None
        self.jsondata = None
        self.steering = getattr(clv, 'Steering', None) is not None
        self.Message = ", WFTNP interface available (Python)"

    def Open(self):
        self.OK = False
        self.Message = ", WFTNP interface cannot be opened"
        if self.interface is None:
            self.interface = clsWftnpBridge(host=self.host, port=self.port)
            if self.interface.open():
                self.OK = True
                self.Message = ", WFTNP interface open"
        else:
            self.OK = True
        return self.OK

    def Write(self, data):
        if not self.interface:
            return False
        if isinstance(data, dict):
            try:
                return self.interface.notify_indoor_bike_data(data)
            except Exception:
                return False
        try:
            self.interface.write_characteristic(uuid.UUID(data), data)
        except Exception:
            return False
        return True

    def Read(self):
        self.jsondata = None
        if not self.interface:
            return False

        # Minimal, best-effort compatibility layer.
        # Real WFTNP servers push notifications; we keep the state in the same
        # shape as the legacy bleDongle interface.
        try:
            services = self.interface.discover_services()
            if FTMS_SERVICE_UUID in services:
                chars = self.interface.discover_characteristics(FTMS_SERVICE_UUID)
                bind = {str(uuid): props for uuid, props in chars}
                if str(INDOOR_BIKE_DATA_UUID) in bind:
                    self.jsondata = {
                        'target_power': 0,
                        'grade': 0,
                        'wind_resistance_coefficient': 0,
                        'wind_speed': 0,
                        'rolling_resistance_coefficient': 0,
                    }
                    return True
        except Exception:
            pass

        return False

    def Close(self):
        if self.interface:
            self.interface.close()
            self.interface = None
            self.OK = False
            self.Message = ", WFTNP interface closed"


class clsBleCTP(clsBleInterface):
    HeartRate = 0
    CurrentSpeed = 0
    Cadence = 0
    CurrentPower = 0
    SteeringAngle = 0
    TargetMode = None
    TargetGrade = 0
    TargetPower = 0
    WindResistance = None
    WindSpeed = None
    DraftingFactor = 1
    RollingResistance = None

    def SetAthleteData(self, HeartRate):
        self.HeartRate = HeartRate

    def SetTrainerData(self, CurrentSpeed, Cadence, CurrentPower):
        self.CurrentSpeed = CurrentSpeed
        self.Cadence = Cadence
        self.CurrentPower = CurrentPower

    def SetSteeringAngle(self, SteeringAngle):
        self.SteeringAngle = SteeringAngle

    def Refresh(self):
        rtn = False
        if UseBluetooth and self.OK:
            if self.steering:
                steering = {'steering_angle': self.SteeringAngle}
                if not self.Write(steering):
                    return False

            data = {
                'heart_rate': self.HeartRate,
                'watts': self.CurrentPower,
                'cadence': self.Cadence,
            }
            if self.Write(data):
                if self.Read():
                    try:
                        self.TargetPower = self.jsondata["target_power"]
                        self.TargetMode = mode_Power
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.TargetGrade = self.jsondata["grade"]
                        self.TargetMode = mode_Grade
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.WindResistance = self.jsondata["wind_resistance_coefficient"]
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.WindSpeed = self.jsondata["wind_speed"]
                        rtn = True
                    except Exception:
                        pass
                    try:
                        self.RollingResistance = self.jsondata["rolling_resistance_coefficient"]
                        rtn = True
                    except Exception:
                        pass
        return rtn


if __name__ == "__main__":
    # Quick smoke test: discover endpoints and open the WFTNP bridge.
    bridge = clsBleInterface(type('Dummy', (), {'Steering': None, 'ble': True})())
    bridge.Open()
    if bridge.OK:
        print("OK: WFTNP bridge is open")
        bridge.Close()
    else:
        print("WARN: WFTNP bridge could not connect")
