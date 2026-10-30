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


async def receive_control_exchange(reader, sequence, expected_result):
    """The WFTNP WRITE acknowledgement must precede FTMS NOTIFY."""
    ack = bytes((1, 4, sequence, 0, 0, 16))
    notice = bytes.fromhex("0106000000") + bytes((16 + len(expected_result),))
    frames = [await receive(reader), await receive(reader)]
    assert frames == [(ack, CONTROL), (notice, CONTROL + expected_result)], frames


@unittest.skipUnless(WftnpServer is not None, "py-wftnp not installed")
class TestWftnpRawWire(unittest.IsolatedAsyncioTestCase):
    async def test_trainingpeaks_legacy_and_zwift_explicit_subscribe(self):
        """Both observed WFTNP subscription formats receive FTMS telemetry."""
        transport = WftnpFTMSTransport(port=0, interval=0.02)
        await transport.start()
        clients = []
        try:
            for sequence, payload in ((0, BIKE), (5, BIKE + b"\\x01")):
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", transport.server.port
                )
                clients.append((reader, writer))
                writer.write(frame(5, sequence, payload))
                await writer.drain()
                header, response = await receive(reader)
                self.assertEqual(header, frame(5, sequence, BIKE)[:6])
                self.assertEqual(response, BIKE)

            transport.bridge.set_trainer_data(30, 90, 200)
            for reader, _writer in clients:
                header, data = await receive(reader)
                self.assertEqual(header[1], 6)
                self.assertEqual(data[:16], BIKE)
                self.assertTrue(any(byte != 0 for byte in data[16:]))

            # Explicit Zwift unsubscribe must not affect the legacy connection.
            zwift_reader, zwift_writer = clients[1]
            zwift_writer.write(frame(5, 6, BIKE + b"\\x00"))
            await zwift_writer.drain()
            header, response = await receive(zwift_reader)
            self.assertEqual(header, frame(5, 6, BIKE)[:6])
            self.assertEqual(response, BIKE)
            legacy_reader, _ = clients[0]
            header, data = await receive(legacy_reader)
            self.assertEqual(header[1], 6)
            self.assertEqual(data[:16], BIKE)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(zwift_reader.readexactly(6), 0.1)
        finally:
            for _reader, writer in clients:
                writer.close()
                await writer.wait_closed()
            await transport.stop()

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
            self.assertEqual(h, bytes((1, 2, 8, 0)) + len(p).to_bytes(2, "big"))
            self.assertEqual(len(p), 16 + 4 * 17)  # FTMS has four characteristics
            self.assertEqual(p[:16], SERVICE)
            records = {p[i:i+16]: p[i+16] for i in range(16, len(p), 17)}
            self.assertEqual(records[BIKE], 0x05)  # READ | NOTIFY
            self.assertEqual(records[CONTROL], 0x0a)  # WRITE | INDICATE

            writer.write(frame(5, 9, CONTROL + b"\x01"))
            await writer.drain()
            h, p = await receive(reader)
            self.assertEqual(h, bytes.fromhex("010509000010"))
            self.assertEqual(p, CONTROL)

            writer.write(frame(4, 10, CONTROL + b"\x00"))
            await writer.drain()
            await receive_control_exchange(reader, 10, bytes.fromhex("800001"))

            # 250 W is FA 00 (little-endian) inside FTMS, not 00 FA.
            writer.write(frame(4, 11, CONTROL + bytes.fromhex("05fa00")))
            await writer.drain()
            await receive_control_exchange(reader, 11, bytes.fromhex("800501"))
            command = transport.bridge.take_command()
            self.assertEqual(command.target_power_watts, 250)
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await transport.stop()


if __name__ == "__main__":
    unittest.main()
