"""Exercise real simulated Tacx trainer through WFTNP TCP, without hardware."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

try:
    from wftnp import Endpoint, WftnpClient
except ImportError:
    Endpoint = WftnpClient = None

from constants import mode_Grade, mode_Power
from ftmsWftnpAdapter import FTMSWftnpAdapter
from wftnpRuntime import WftnpRuntime
from wftnpTransport import CONTROL_POINT, INDOOR_BIKE_DATA
try:
    from usbTrainer import clsSimulatedTrainer
except ImportError:
    clsSimulatedTrainer = None


@unittest.skipUnless(WftnpClient is not None and clsSimulatedTrainer is not None,
                     "py-wftnp or simulated trainer dependencies not installed")
class TestSimulatedTrainerWftnp(unittest.IsolatedAsyncioTestCase):
    async def test_simulated_trainer_erg_and_grade_over_tcp(self):
        # This tests the real simulated trainer and transport. The application
        # entry point and its ANT startup remain outside this test's scope.
        clv = SimpleNamespace(PowerFactor=1, Steering=None)
        trainer = clsSimulatedTrainer(clv)
        runtime = WftnpRuntime(host="127.0.0.1", port=0)
        runtime.start()
        client = WftnpClient(Endpoint("127.0.0.1", runtime.transport.server.port),
                             heartbeat_interval=None)
        try:
            await client.start()
            await client.wait_ready(timeout=3)
            async with (await client.subscribe(CONTROL_POINT) as control,
                        await client.subscribe(INDOOR_BIKE_DATA) as telemetry):
                await client.write_characteristic(CONTROL_POINT, b"\\x00")
                self.assertEqual((await asyncio.wait_for(anext(control), 3)).value,
                                 b"\\x80\\x00\\x01")
                for watts in (150, 250):
                    await client.write_characteristic(
                        CONTROL_POINT, bytes((0x05, watts & 0xff, watts >> 8)))
                    self.assertEqual((await asyncio.wait_for(anext(control), 3)).value,
                                     b"\\x80\\x05\\x01")
                    adapter = runtime.adapter
                    self.assertTrue(adapter.Refresh())
                    self.assertEqual(adapter.TargetMode, mode_Power)
                    trainer.SetPower(adapter.TargetPower)
                    self.assertEqual(trainer.TargetPowerProvided, watts)
                    trainer.Refresh(True, None)
                    adapter.SetTrainerData(trainer.SpeedKmh, trainer.Cadence,
                                           trainer.CurrentPower)
                    self.assertTrue((await asyncio.wait_for(anext(telemetry), 3)).value)
                # Simulation parameters are FTMS 0.01% signed grade.
                grade = 500
                await client.write_characteristic(
                    CONTROL_POINT, b"\\x11" + grade.to_bytes(2, "little", signed=True)
                    + b"\\x00\\x00\\x00\\x00")
                response = (await asyncio.wait_for(anext(control), 3)).value
                self.assertEqual(response[:2], b"\\x80\\x11")
                if response[2] == 1:
                    self.assertTrue(runtime.adapter.Refresh())
                    self.assertEqual(runtime.adapter.TargetMode, mode_Grade)
                    trainer.SetGrade(runtime.adapter.TargetGrade)
                    self.assertEqual(trainer.TargetMode, mode_Grade)
                    self.assertAlmostEqual(trainer.TargetGrade, 5.0)
        finally:
            await client.stop()
            runtime.stop()
