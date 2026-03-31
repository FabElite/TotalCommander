"""
Entry point dell'applicazione Total Commander IV.

Architettura logging:
  - Root logger:        DEBUG  → non scarta nulla; ogni handler decide
  - File (logs/app.log, rotativo):  DEBUG  → archivio diagnostico completo
  - Console (stdout):               INFO
  - Pannello GUI:                   INFO di default (filtro _LibraryFilter blocca tutti i DEBUG)
                                    Il toggle "Debug" nel pannello log rimuove il filtro
"""
import logging
import sys
import os
from logging.handlers import RotatingFileHandler

from gui.main_window import MainWindow


def resource_path(relative_path):
    """Percorso risorse compatibile con PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def _base_dir() -> str:
    """Cartella base dell'applicazione: accanto all'exe in produzione,
    cartella del progetto in sviluppo."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ── Handler GUI ───────────────────────────────────────────────────────────────

class _TextHandler(logging.Handler):
    """Invia i record formattati a una queue.Queue (letta dal pannello log)."""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class _LibraryFilter(logging.Filter):
    """
    Filtro applicato al solo handler GUI.
    - Modalità normale : blocca TUTTI i DEBUG; INFO e superiori passano sempre.
    - Modalità debug   : tutto passa (attivato dal checkbox nel pannello log).

    Il root logger è impostato a DEBUG in modo che file e console ricevano
    i messaggi secondo il proprio livello individuale, senza che il root
    li scarti in anticipo.
    """

    def __init__(self):
        super().__init__()
        self._debug = False

    def set_debug(self, enabled: bool):
        self._debug = enabled

    def filter(self, record: logging.LogRecord) -> bool:
        if self._debug:
            return True
        return record.levelno >= logging.INFO


_lib_filter: _LibraryFilter | None = None


def set_debug_mode(enabled: bool):
    """Chiamato da MainWindow.set_debug_mode → aggiorna filtro e livello root."""
    if _lib_filter is not None:
        _lib_filter.set_debug(enabled)


# ── Setup logging ─────────────────────────────────────────────────────────────

def _setup_logging():
    """
    Configura file handler (DEBUG) e console handler (INFO).
    Il GUI handler viene aggiunto dopo la creazione di MainWindow.
    """
    fmt_full  = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    fmt_short = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    root = logging.getLogger()
    # DEBUG: il root non scarta nulla; ogni handler applica il proprio livello.
    # Senza questa riga il file handler (impostato a DEBUG) non riceve mai
    # i messaggi DEBUG perché vengono bloccati qui prima di raggiungere qualsiasi handler.
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)

    # File → DEBUG sempre (archivio completo)
    logs_dir = os.path.join(_base_dir(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(logs_dir, "app.log"), maxBytes=5 * 1024 * 1024,
                              backupCount=3, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_full)
    root.addHandler(fh)

    # Console → INFO
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt_full)
    root.addHandler(ch)

    logging.info("Logging configurato — file: DEBUG, console: INFO, GUI: INFO (debug su richiesta).")


def _add_gui_handler(log_queue):
    """Aggiunge il TextHandler con filtro librerie al root logger."""
    global _lib_filter
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    handler = _TextHandler(log_queue)
    handler.setLevel(logging.DEBUG)   # il filtro fa la selezione
    handler.setFormatter(fmt)

    _lib_filter = _LibraryFilter()
    handler.addFilter(_lib_filter)

    logging.getLogger().addHandler(handler)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _setup_logging()
    logging.info("Avvio del programma...")

    app = MainWindow()

    try:
        app.iconbitmap(resource_path("justo.ico"))
    except Exception as e:
        logging.warning(f"Icona non caricata: {e}")

    _add_gui_handler(app.log_queue)
    app.log_panel.set_debug_callback(set_debug_mode)

    logging.info("Programma avviato.")
    app.mainloop()