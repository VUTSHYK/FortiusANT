"""mDNS lifecycle and actual ANT+ identity propagation."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from wftnpTransport import WftnpFTMSTransport, FTMS_SERVICE
from wftnpRuntime import WftnpRuntime, lan_address

try:
    from wftnp.advertisement import ServerAdvertisement
except ImportError:
    ServerAdvertisement = None


@unittest.skipUnless(ServerAdvertisement is not None, "py-wftnp not installed")
class TestWftnpMdns(unittest.IsolatedAsyncioTestCase):
    async def test_advertisement_after_tcp_and_rename_without_tcp_restart(self):
        with patch.object(ServerAdvertisement, "start", new_callable=AsyncMock) as start, \
             patch.object(ServerAdvertisement, "stop", new_callable=AsyncMock) as stop:
            transport = WftnpFTMSTransport(
                host="127.0.0.1", port=0, mdns_address="192.168.1.20")
            await transport.start()
            try:
                server = transport.server
                self.assertGreater(server.port, 0)
                self.assertEqual(transport._advertisement.name, "Tacx Vortex")
                self.assertEqual(transport._advertisement.port, server.port)
                self.assertEqual(transport._advertisement.service_uuids, (FTMS_SERVICE,))
                self.assertEqual(start.await_count, 1)
                await transport.update_mdns_name("Tacx Vortex 12345")
                self.assertIs(transport.server, server)
                self.assertEqual(transport._advertisement.name, "Tacx Vortex 12345")
                self.assertEqual(start.await_count, 2)
                self.assertEqual(stop.await_count, 1)
                await transport.update_mdns_name("Tacx Vortex 12345")
                self.assertEqual(start.await_count, 2)
            finally:
                await transport.stop()
            self.assertEqual(stop.await_count, 2)

    async def test_failed_advertisement_closes_tcp(self):
        with patch.object(ServerAdvertisement, "start", new_callable=AsyncMock,
                          side_effect=RuntimeError("mDNS failed")):
            transport = WftnpFTMSTransport(
                host="127.0.0.1", port=0, mdns_address="192.168.1.20")
            with self.assertRaisesRegex(RuntimeError, "mDNS failed"):
                await transport.start()
            self.assertIsNone(transport.server)


class TestMdnsAddress(unittest.TestCase):
    def test_loopback_disables_advertisement(self):
        self.assertIsNone(lan_address("127.0.0.1"))
        self.assertIsNone(WftnpRuntime(host="127.0.0.1", port=0).transport.mdns_address)

    def test_explicit_lan_address(self):
        self.assertEqual(lan_address("192.168.1.20"), "192.168.1.20")


if __name__ == "__main__":
    unittest.main()
