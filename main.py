import logging
from logging.handlers import RotatingFileHandler
from gui.main_window import MainWindow
import tkinter as tk
import sys
import queue

class TextHandler(logging.Handler):
    """Custom logging handler that sends log messages to a thread-safe queue."""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        msg = self.format(record)
        self.log_queue.put(msg)

def setup_initial_logging():
    """Configura il logging per file e console. Da chiamare all'avvio."""
    LOG_FILENAME = "app.log"
    log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Ottieni il root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Imposta il livello di logging globale

    # Pulisci eventuali handler preesistenti per evitare duplicati
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Handler per file rotativo
    file_handler = RotatingFileHandler(LOG_FILENAME, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    # Handler per la console
    console_handler = logging.StreamHandler(sys.stdout) # Usa sys.stdout
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    logger.info("Logging iniziale configurato (file e console).")


def add_gui_logging_handler(log_queue): # <-- Accetta la coda
    """Aggiunge l'handler per il widget di testo della GUI al logger esistente."""
    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s") # Formato più breve per la GUI
    text_handler = TextHandler(log_queue)
    text_handler.setFormatter(log_formatter)
    logging.getLogger().addHandler(text_handler)
    logging.getLogger().info("Handler della GUI (via coda) aggiunto al logger.")


if __name__ == "__main__":
    setup_initial_logging()
    logging.info("Avvio del programma...")
    app = MainWindow()
    # Passa la coda dell'app, non il widget
    add_gui_logging_handler(app.log_queue)
    app.mainloop()