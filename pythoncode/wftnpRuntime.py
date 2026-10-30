"""Own a WFTNP asyncio server on a dedicated thread.

The FortiusANT trainer loop never performs network I/O.
"""
import asyncio
import socket
import threading

from ftmsWftnpAdapter import FTMSWftnpAdapter
from wftnpTransport import WftnpFTMSTransport


def lan_address(host):
    """Find the IPv4 address used for outbound LAN traffic without sending data."""
    if host not in ("0.0.0.0", "::"):
        return None if host.startswith("127.") or host == "::1" else host
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 80))
        address = sock.getsockname()[0]
    if address.startswith("127.") or address == "0.0.0.0":
        raise OSError("No LAN IPv4 address available for WFTNP mDNS")
    return address


class WftnpRuntime:
    def __init__(self, *, host="0.0.0.0", port=36866, idle_timeout=3600):
        # Loopback tests remain TCP-only; LAN startup must have a routable address.
        address = lan_address(host)
        self.adapter = FTMSWftnpAdapter()
        self.transport = WftnpFTMSTransport(
            bridge=self.adapter.bridge, host=host, port=port,
            idle_timeout=idle_timeout, mdns_address=address,
        )
        self._thread = None
        self._loop = None
        self._stop = None
        self._ready = threading.Event()
        self._error = None
        self._mdns_name = "Tacx Vortex"

    def set_trainer_identity(self, name):
        """Called from FortiusANT's ANT+ trainer loop, never blocking on mDNS."""
        if not name or name == self._mdns_name:
            return
        self._mdns_name = name
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self.transport.update_mdns_name(name), loop
            )
            def report_error(done):
                try:
                    done.result()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("WFTNP mDNS name update failed")
            future.add_done_callback(report_error)

    def start(self, timeout=10):
        if self._thread is not None:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="wftnp-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            # Startup may still be blocked; do not claim the thread stopped.
            raise TimeoutError("WFTNP server startup timed out")
        if self._error is not None:
            error = self._error
            self.stop()
            raise RuntimeError("WFTNP server failed to start") from error

    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def serve():
            self._stop = asyncio.Event()
            try:
                await self.transport.start()
            except BaseException as exc:
                self._error = exc
                self._ready.set()
                return
            self._ready.set()
            try:
                await self._stop.wait()
            finally:
                await self.transport.stop()

        try:
            loop.run_until_complete(serve())
        except BaseException as exc:
            self._error = exc
            self._ready.set()
        finally:
            # Zeroconf can schedule broadcasts that outlive unregister/close.
            # Drain remaining tasks before closing the dedicated event loop.
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                self._loop = None

    def stop(self, timeout=10):
        thread = self._thread
        if thread is None:
            return
        loop, event = self._loop, self._stop
        if loop is not None and event is not None and loop.is_running():
            loop.call_soon_threadsafe(event.set)
        if thread is not threading.current_thread():
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError("WFTNP server did not stop")
        self._thread = None
