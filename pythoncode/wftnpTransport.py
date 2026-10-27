"""Async WFTNP FTMS transport, independent of the FortiusANT trainer loop.

Requires the sibling py-wftnp package (pip install -e ../py-wftnp).
No trainer methods are called on the network event loop.
"""

import asyncio
import struct
from uuid import UUID

from ftmsBridge import FTMSBridge
from ftmsControlPoint import FTMSControlPoint

FTMS_SERVICE = UUID("00001826-0000-1000-8000-00805f9b34fb")
INDOOR_BIKE_DATA = UUID("00002ad2-0000-1000-8000-00805f9b34fb")
CONTROL_POINT = UUID("00002ad9-0000-1000-8000-00805f9b34fb")


def encode_indoor_bike_data(telemetry):
    """Speed (0.01 km/h), cadence (0.5 rpm), instantaneous power (W).

    Flags bit 2 enables cadence and bit 6 enables instantaneous power.
    Speed is present when bit 0 is clear.
    """
    speed = max(0, min(65535, round(telemetry.speed_kmh * 100)))
    cadence = max(0, min(65535, round(telemetry.cadence_rpm * 2)))
    power = max(-32768, min(32767, round(telemetry.power_watts)))
    return struct.pack("<HHHh", 0x0044, speed, cadence, power)


class WftnpFTMSTransport:
    """Serve FTMS characteristics; delegate control-point decoding to caller.

    This intentionally does not acknowledge control writes as successful trainer
    actions. The caller must validate control semantics before submitting them
    to the FTMSBridge mailbox.
    """

    def __init__(self, bridge=None, *, host="127.0.0.1", port=36866,
                 on_control_write=None, interval=0.25, idle_timeout=3600,\n                 max_connections=4):
        if idle_timeout <= 0:
            raise ValueError('idle_timeout must be positive')
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.bridge = bridge if bridge is not None else FTMSBridge()
        self.control_point = FTMSControlPoint(self.bridge)
        self.on_control_write = on_control_write
        self.host = host
        self.port = port
        self.interval = interval
        self.idle_timeout = idle_timeout
        self.max_connections = max_connections
        self.server = None
        self._publisher = None

    async def _handle_control_write(self, connection, data):
        """Send the FTMS result as a notification, not as a characteristic value.

        WFTNP WRITE acknowledgement confirms transport delivery only.
        """
        result = (self.on_control_write(data) if self.on_control_write is not None
                  else self.control_point.handle_connection(connection, data))
        if asyncio.iscoroutine(result):
            result = await result
        if not isinstance(result, bytes) or len(result) != 3 or result[0] != 0x80:
            raise ValueError("control handler must return an FTMS response")
        if self.server is not None:
            await self.server.notify_connection(connection, CONTROL_POINT, result)
        return None

    async def start(self):
        if self.server is not None:
            return
        from wftnp import CharacteristicProperties as Props
        from wftnp import CharacteristicSpec, ServiceSpec, WftnpServer

        bike = CharacteristicSpec(
            INDOOR_BIKE_DATA, properties=Props.READ | Props.NOTIFY,
            value=encode_indoor_bike_data(self.bridge.get_telemetry()),
        )
        control = CharacteristicSpec(
            CONTROL_POINT, properties=Props.WRITE | Props.NOTIFY,
            on_write_with_connection=self._handle_control_write,
        )
        server = WftnpServer(
            host=self.host, port=self.port,
            services=[ServiceSpec(FTMS_SERVICE, (bike, control))],
            max_connections=self.max_connections,
            idle_timeout=self.idle_timeout,
            on_disconnect_with_connection=self.control_point.release,
        )
        await server.start()
        self.server = server
        self._publisher = asyncio.create_task(self._publish_loop())

    async def _publish_loop(self):
        try:
            while True:
                await asyncio.sleep(self.interval)
                payload = encode_indoor_bike_data(self.bridge.get_telemetry())
                self.server.registry.characteristic_for(INDOOR_BIKE_DATA).value = payload
                await self.server.notify_characteristic(INDOOR_BIKE_DATA, payload)
        except asyncio.CancelledError:
            raise

    async def stop(self):
        publisher, self._publisher = self._publisher, None
        if publisher is not None:
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
        server, self.server = self.server, None
        if server is not None:
            await server.stop()
        self.control_point.release()
