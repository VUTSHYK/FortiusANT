"""Independent wire-format regression based on elfrances/wahoo-fitness-tnp.

Uses raw TCP bytes, NOT WftnpClient or its frame encoder.
WFTNP header: version, opcode, sequence, status, big-endian uint16 length.
UUIDs: canonical 16-byte order; FTMS values: little-endian.
"""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))
try:
    from wftnp import WftnpServer
except ImportError:
    WftnpServer = None
from wftnpTransport import WftnpFTMSTransport

SERVICE = bytes.fromhex("0000182600001000800000805f9b34fb")
BIKE = bytes.fromhex("00002ad200001000800000805f9b34fb")
CONTROL = bytes.fromhex("00002ad900001000800000805f9b34fb")


def frame(opcode, sequence, payload=b""):
    return bytes((1, opcode, sequence, 0)) + len(payload).to_bytes(2, "big") + payload


async def receive(reader):
    header = await asyncio.wait_for(reader.readexactly(6), 3)
    payload = await asyncio.wait_for(reader.readexactly(int.from_bytes(header[4:6], "big")), 3)
    return header, payload


@unittest.skipUnless(WftnpServer is not None, "py-wftnp not installed")
class TestWftnpRawWire(unittest.IsolatedAsyncioTestCase):
    async def test_reference_frames_and_ftms_control(self):
        transport = WftnpFTMSTransport(port=0, interval=0.05)
        await transport.start()
        writer = None
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", transport.server.port)
            writer.write(bytes.fromhex("010107000000"))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes((1, 1, 7, 0)) + len(p).to_bytes(2, "big"))
            self.assertIn(SERVICE, [p[i:i+16] for i in range(0, len(p), 16)])

            writer.write(frame(2, 8, SERVICE))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes.fromhex("010208000032"))
            self.assertEqual(p[:16], SERVICE)
            records = {p[i:i+16]: p[i+16] for i in range(16, len(p), 17)}
            self.assertEqual(records[BIKE], 0x05)  # READ | NOTIFY
            self.assertEqual(records[CONTROL], 0x06)  # WRITE | NOTIFY

            writer.write(frame(5, 9, CONTROL + b"\x01"))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes.fromhex("010509000010"))
            self.assertEqual(p, CONTROL)

            writer.write(frame(4, 10, CONTROL + b"\x00"))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes.fromhex("01040a000010"))
            self.assertEqual(p, CONTROL)
            h, p = await receive(reader)
            self.assertEqual(h[:2], b"\x01\\x06")
            self.assertEqual(p, CONTROL + b"\x80\\x00\\x01")

            # 250 W is FA 00 (little-endian) inside FTMS, not 00 FA.
            writer.write(frame(4, 11, CONTROL + bytes.fromhex("05fa00")))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes.fromhex("01040b000010"))
            self.assertEqual(p, CONTROL)
            h, p = await receive(reader)
            self.assertEqual(h[:2], b"\x01\\x06")
            self.assertEqual(p, CONTROL + bytes.fromhex("800501"))
            command = transport.bridge.take_command()
            self.assertEqual(command.target_power_watts, 250)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await transport.stop()


if __name__ == "__main__":
    unittest.main()
