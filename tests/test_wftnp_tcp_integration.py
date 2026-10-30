"""Real TCP regression for FortiusANT's WFTNP transport."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))
import debug

try:
    from wftnp import Endpoint, WftnpClient
except ImportError:
    Endpoint = WftnpClient = None
from ftmsBridge import TrainerMode
from wftnpTransport import CONTROL_POINT, INDOOR_BIKE_DATA, FTMS_SERVICE, WftnpFTMSTransport


@unittest.skipUnless(WftnpClient is not None, "py-wftnp not installed")
class TestWftnpTcpIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_diagnostics_over_real_tcp(self):
        """Verify connect, discovery, subscription and raw frames through the real server."""
        debug.activate(debug.WFTNP | debug.WFTNP_RAW | debug.Application)
        transport = WftnpFTMSTransport(port=0, interval=0.02)
        client = None
        try:
            with patch("wftnpTransport.logfile.Write") as write:
                await transport.start()
                client = WftnpClient(Endpoint("127.0.0.1", transport.server.port),
                                     heartbeat_interval=None)
                await client.start()
                await client.wait_ready(timeout=3)
                characteristics = await client.discover_characteristics(FTMS_SERVICE)
                self.assertTrue(characteristics)
                async with await client.subscribe(INDOOR_BIKE_DATA):
                    await asyncio.sleep(0.05)
                await client.stop()
                await asyncio.sleep(0.05)
                messages = [call.args[0] for call in write.call_args_list]
            self.assertTrue(any("client connected" in m for m in messages), messages)
            self.assertTrue(any("client disconnected" in m for m in messages), messages)
            self.assertTrue(any("[WFTNP] RX " in m for m in messages), messages)
            self.assertTrue(any("TX 01 02 " in m for m in messages), messages)
            self.assertTrue(any("subscribed " in m for m in messages), messages)
            self.assertTrue(any("[WFTNP] RX " in m for m in messages), messages)
            self.assertTrue(any("[WFTNP] TX " in m for m in messages), messages)
        finally:
            if client is not None:
                await client.stop()
            await transport.stop()
            debug.deactivate()

    async def test_ownership_and_telemetry(self):
        transport = WftnpFTMSTransport(port=0, interval=0.02)
        await transport.start()
        a = WftnpClient(Endpoint("127.0.0.1", transport.server.port),
                        heartbeat_interval=None)
        b = WftnpClient(Endpoint("127.0.0.1", transport.server.port),
                        heartbeat_interval=None)
        try:
            await a.start()
            await b.start()
            await a.wait_ready(timeout=3)
            await b.wait_ready(timeout=3)
            async with (
                await a.subscribe(CONTROL_POINT) as a_control,
                await b.subscribe(CONTROL_POINT) as b_control,
                await a.subscribe(INDOOR_BIKE_DATA) as a_bike,
                await b.subscribe(INDOOR_BIKE_DATA) as b_bike,
            ):
                transport.bridge.set_trainer_data(25, 90, 200)
                self.assertTrue((await asyncio.wait_for(anext(a_bike), 3)).value)
                self.assertTrue((await asyncio.wait_for(anext(b_bike), 3)).value)
                await a.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(a_control), 3)).value,
                                 b"\x80\x00\x01")
                await b.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x00\x05")
                await b.write_characteristic(CONTROL_POINT, b"\x05\xfa\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x05\x05")
                self.assertIsNone(transport.bridge.take_command())
                await a.write_characteristic(CONTROL_POINT, b"\x05\xfa\x00")
                self.assertEqual((await asyncio.wait_for(anext(a_control), 3)).value,
                                 b"\x80\x05\x01")
                command = transport.bridge.take_command()
                self.assertEqual(command.mode, TrainerMode.POWER)
                self.assertEqual(command.target_power_watts, 250)
                await a.stop()
                async with asyncio.timeout(3):
                    while transport.control_point.has_control:
                        await asyncio.sleep(0.01)
                await b.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x00\x01")
        finally:
            await a.stop()
            await b.stop()
            await transport.stop()
