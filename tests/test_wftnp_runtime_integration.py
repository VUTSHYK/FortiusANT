"""Exercise the threaded runtime using a real TCP client (py-wftnp required)."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from wftnpRuntime import WftnpRuntime
from wftnpTransport import CONTROL_POINT, INDOOR_BIKE_DATA

try:
    from wftnp import Endpoint, WftnpClient
except ImportError:
    Endpoint = WftnpClient = None


@unittest.skipUnless(WftnpClient is not None, "py-wftnp not installed")
class TestWftnpRuntime(unittest.TestCase):
    def test_threaded_start_telemetry_control_and_stop(self):
        runtime = WftnpRuntime(host="127.0.0.1", port=0, idle_timeout=30)
        runtime.start()
        try:
            self.assertTrue(runtime._thread.is_alive())
            self.assertIsNotNone(runtime.transport.server)
            port = runtime.transport.server.port
            self.assertGreater(port, 0)
            runtime.adapter.SetAthleteData(145)
            runtime.adapter.SetTrainerData(27.5, 88, 215)

            async def exercise():
                client = WftnpClient(Endpoint("127.0.0.1", port),
                                     heartbeat_interval=None)
                try:
                    await client.start()
                    await client.wait_ready(timeout=3)
                    async with (
                        await client.subscribe(INDOOR_BIKE_DATA) as bike,
                        await client.subscribe(CONTROL_POINT) as control,
                    ):
                        sample = await asyncio.wait_for(anext(bike), 3)
                        self.assertTrue(sample.value)
                        await client.write_characteristic(CONTROL_POINT, b"\x00")
                        self.assertEqual(
                            (await asyncio.wait_for(anext(control), 3)).value,
                            b"\x80\x00\x01",
                        )
                        await client.write_characteristic(CONTROL_POINT, b"\x05\xc8\x00")
                        self.assertEqual(
                            (await asyncio.wait_for(anext(control), 3)).value,
                            b"\x80\x05\x01",
                        )
                        # Consume while the owner is connected: disconnect
                        # intentionally discards any unconsumed commands.
                        self.assertTrue(runtime.adapter.Refresh())
                        self.assertEqual(runtime.adapter.TargetPower, 200)
                finally:
                    await client.stop()

            asyncio.run(exercise())
        finally:
            runtime.stop()
        self.assertIsNone(runtime._thread)
        self.assertIsNone(runtime.transport.server)

    def test_startup_failure_is_reported(self):
        runtime = WftnpRuntime(host="not a valid bind address!", port=36866)
        with self.assertRaises(RuntimeError):
            runtime.start(timeout=5)
        self.assertIsNone(runtime._thread)


if __name__ == "__main__":
    unittest.main()
