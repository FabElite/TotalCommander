"""
Controller BLE: incapsula il loop asyncio dedicato e l'istanza BLEManager.

Responsabilità limitata e a basso rischio: ciclo di vita del loop in un thread
daemon e ponte thread-safe verso le coroutine (run()). L'orchestrazione legata
ai widget (progress bar, LED, pannello live) resta nell'app, che chiama run()
e aggiorna la UI nei propri callback marshalati con after().
"""
import asyncio
import logging
import threading

from shared_lib.bluetooth_manager import BLEManager


class BleController:
    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.manager = BLEManager()
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def start(self) -> None:
        """Avvia il loop asyncio in un thread daemon e attende che sia pronto."""
        def _worker():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    if hasattr(self._loop, "shutdown_asyncgens"):
                        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_worker, name="BLE-Asyncio-Loop", daemon=True)
        self._thread.start()
        self._ready.wait()

    def run(self, coro):
        """Esegue una coroutine sul loop BLE e restituisce il concurrent.futures.Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def is_ready(self) -> bool:
        """True solo se il dispositivo è connesso E i servizi GATT sono pronti."""
        return self.manager.get_connection_status()

    def shutdown(self, join_timeout: float = 3.0) -> None:
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)
