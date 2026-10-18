"""
DirCon server (async) for FortiusANT — adapted for repository integration.
Dependencies: zeroconf
"""

import asyncio
import struct
import logging
import socket
from typing import Dict, Tuple, Optional, Any
from zeroconf import ServiceInfo, Zeroconf

logger = logging.getLogger("dircon")


class DirconServer:
    SERVICE_TYPE = "_wahoo-fitness-tnp._tcp.local."

    def __init__(self, name: str, serial: str, mac: str, host: str = "0.0.0.0", port: int = 9999):
        self.name = name
        self.serial = serial
        self.mac = mac
        self.host = host
        self.port = int(port)

        self.zc = Zeroconf()
        self.service_info: Optional[ServiceInfo] = None

        self.server: Optional[asyncio.base_events.Server] = None
        self._serve_task: Optional[asyncio.Task] = None
        self._clients: Dict[asyncio.StreamWriter, Dict[str, Any]] = {}

        self._control_queue: asyncio.Queue = asyncio.Queue()
        self._send_lock = asyncio.Lock()

        self.ftms_uuid = "1826"
        self._running = False

    def _build_service_info(self) -> ServiceInfo:
        host_ip = self._get_local_ip()
        properties = {
            "serial-number": self.serial.encode("utf-8"),
            "mac-address": self.mac.encode("utf-8"),
            "ble-service-uuids": self.ftms_uuid.encode("utf-8"),
        }
        addr_bytes = socket.inet_aton(host_ip)
        service_name = f"{self.name} - {self.serial}._wahoo-fitness-tnp._tcp.local."
        info = ServiceInfo(
            type_=self.SERVICE_TYPE,
            name=service_name,
            addresses=[addr_bytes],
            port=self.port,
            properties=properties,
            server=socket.gethostname() + ".local.",
        )
        return info

    @staticmethod
    def _get_local_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    async def start(self):
        if self._running:
            return
        self._running = True
        self.service_info = self._build_service_info()
        self.zc.register_service(self.service_info)
        logger.info("Zeroconf service registered: %s", self.service_info.name)

        loop = asyncio.get_running_loop()
        self.server = await asyncio.start_server(self._handle_client, host=self.host, port=self.port)
        logger.info("TCP Dircon server listening on %s:%d", self.host, self.port)
        self._serve_task = loop.create_task(self._server_wait_closed())

    async def _server_wait_closed(self):
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        if not self._running:
            return
        self._running = False

        for writer in list(self._clients.keys()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

        if self.server:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:
                pass
            self.server = None

        if self.service_info:
            try:
                self.zc.unregister_service(self.service_info)
            except Exception:
                pass
            self.service_info = None
        try:
            self.zc.close()
        except Exception:
            pass

        if self._serve_task:
            self._serve_task.cancel()
            self._serve_task = None

        logger.info("DirconServer stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        client_id = f"{peer}"
        logger.info("Client connected: %s", client_id)
        self._clients[writer] = {"peer": peer, "subscriptions": set()}

        read_task = asyncio.create_task(self._client_reader(reader, writer))
        try:
            await read_task
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Client disconnected: %s", client_id)
            self._clients.pop(writer, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _client_reader(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        while not reader.at_eof():
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=300.0)
                if not line:
                    break
                line = line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                parts = line.split()
                cmd = parts[0].upper()
                if cmd == "SUBSCRIBE" and len(parts) >= 2:
                    char_uuid = parts[1].upper()
                    self._clients[writer]["subscriptions"].add(char_uuid)
                    writer.write(f"OK SUBSCRIBED {char_uuid}\n".encode("utf-8"))
                    await writer.drain()
                elif cmd == "UNSUBSCRIBE" and len(parts) >= 2:
                    char_uuid = parts[1].upper()
                    self._clients[writer]["subscriptions"].discard(char_uuid)
                    writer.write(f"OK UNSUBSCRIBED {char_uuid}\n".encode("utf-8"))
                    await writer.drain()
                elif cmd == "WRITE" and len(parts) >= 3:
                    char_uuid = parts[1].upper()
                    hexpayload = parts[2]
                    try:
                        payload = bytes.fromhex(hexpayload)
                    except Exception:
                        writer.write(b"ERR BADHEX\n")
                        await writer.drain()
                        continue
                    await self._control_queue.put((char_uuid, payload, {"peer": peer}))
                    writer.write(b"OK WRITE\n")
                    await writer.drain()
                    logger.info("WRITE from %s to %s: %s", peer, char_uuid, payload.hex())
                else:
                    writer.write(b"ERR UNKNOWN\n")
                    await writer.drain()
            except asyncio.TimeoutError:
                logger.debug("Client %s timed out", peer)
                break
            except Exception as e:
                logger.exception("Error reading from client %s: %s", peer, e)
                break

    async def notify_data(self, event: Dict[str, Any]):
        payload = self._pack_ftms_indoor_bike_data(event)
        char_uuid = "2AD2"
        coros = []
        async with self._send_lock:
            for writer, info in list(self._clients.items()):
                subs = info.get("subscriptions", set())
                if (char_uuid in subs) or ("ALL" in subs) or (len(subs) == 0):
                    coros.append(self._send_notify_to_client(writer, char_uuid, payload))
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    def _pack_ftms_indoor_bike_data(self, event: Dict[str, Any]) -> bytes:
        flags = 0
        parts = []
        speed_ms = None
        if "speed" in event:
            speed_ms = float(event["speed"])
        elif "speed_kmh" in event:
            speed_ms = float(event["speed_kmh"]) / 3.6
        if speed_ms is not None:
            flags |= (1 << 0)
            speed_raw = int(round(speed_ms * 100))
            parts.append(struct.pack("<H", speed_raw))
        if "cadence" in event:
            flags |= (1 << 2)
            cadence = int(round(float(event["cadence"])))
            parts.append(struct.pack("<B", max(0, min(255, cadence))))
        power = None
        if "watts" in event:
            power = int(round(event["watts"]))
        elif "power" in event:
            power = int(round(event["power"]))
        if power is not None:
            flags |= (1 << 3)
            parts.append(struct.pack("<h", int(power)))
        if "heart_rate" in event:
            flags |= (1 << 4)
            hr = int(round(event["heart_rate"]))
            parts.append(struct.pack("<B", max(0, min(255, hr))))
        payload = struct.pack("<H", flags) + b"".join(parts)
        logger.debug("Packed FTMS payload flags=0x%04x payload=%s", flags, payload.hex())
        return payload

    async def _send_notify_to_client(self, writer: asyncio.StreamWriter, char_uuid: str, payload: bytes):
        try:
            envelope = b"NOTIFY " + char_uuid.encode("ascii") + b" " + struct.pack("<H", len(payload)) + payload + b"\n"
            writer.write(envelope)
            await writer.drain()
            logger.debug("Sent notify to %s: %s", writer.get_extra_info("peername"), envelope[:80])
        except Exception as e:
            logger.exception("Failed to send notify to client: %s", e)

    async def get_control_command(self, timeout: Optional[float] = None) -> Optional[Tuple[str, bytes, Dict[str, Any]]]:
        try:
            if timeout is None:
                item = await self._control_queue.get()
                return item
            else:
                item = await asyncio.wait_for(self._control_queue.get(), timeout=timeout)
                return item
        except asyncio.TimeoutError:
            return None

    async def drain_control_queue(self) -> list:
        items = []
        while not self._control_queue.empty():
            items.append(self._control_queue.get_nowait())
        return items

    def connected_clients(self) -> int:
        return len(self._clients)

    def list_clients(self):
        res = []
        for w, info in self._clients.items():
            res.append((info.get("peer"), info.get("subscriptions")))
        return res
