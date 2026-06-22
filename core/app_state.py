"""
Contenitore thread-safe per l'ultimo set di dati acquisiti.

Sostituisce il vecchio dict `self._latest_data` di MainWindow, che veniva
scritto da almeno tre thread (loop asyncio BLE, worker dell'executor per il
PSU, main thread per i sensori in polling) e letto dal main thread senza alcun
lock. In CPython il GIL rendeva di fatto atomici update/copia di valori
semplici, ma non era una garanzia: questa classe formalizza l'accesso.
"""
import threading


class LatestData:
    """Dizionario protetto da lock con le sole operazioni che servono."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict = {}

    def update(self, values: dict) -> None:
        """Aggiorna in blocco con le chiavi di `values`."""
        with self._lock:
            self._data.update(values)

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def snapshot(self) -> dict:
        """Copia shallow coerente, da usare per scrivere su file o mediare."""
        with self._lock:
            return dict(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
