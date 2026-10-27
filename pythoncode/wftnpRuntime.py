"""Own a WFTNP asyncio server on a dedicated thread.

The FortiusANT trainer loop never performs network I/O.
"""
import asyncio
import threading

from ftmsWftnpAdapter import FTMSWftnpAdapter
from wftnpTransport import WftnpFTMSTransport


class WftnpRuntime:
    def __init__(self, *, host="0.0.0.0", port=36866, idle_timeout=3600):
        self.adapter = FTMSWftnpAdapter()
        self.transport = WftnpFTMSTransport(
            bridge=self.adapter.bridge, host=host, port=port,
            idle_timeout=idle_timeout,
        )
        self._thread = None
        self._loop = None
        self._stop = None
        self._ready = threading.Event()
        self._error = None

    def start(self, timeout=10):
        if self._thread is not None:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="wftnp-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
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
