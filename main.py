import logging
from logging.handlers import RotatingFileHandler
from gui.main_window import MainWindow
import sys
import os

def resource_path(relative_path):
    """Trova il percorso delle risorse, compatibile con PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class TextHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        msg = self.format(record)
        self.log_queue.put(msg)

def setup_initial_logging():
    log_filename = "app.log"
    log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    file_handler = RotatingFileHandler(log_filename, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
    logger.info("Logging iniziale configurato (file e console).")

def add_gui_logging_handler(log_queue):
    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    text_handler = TextHandler(log_queue)
    text_handler.setFormatter(log_formatter)
    logging.getLogger().addHandler(text_handler)

if __name__ == "__main__":
    setup_initial_logging()
    logging.info("Avvio del programma...")
    app = MainWindow()

    # ✅ Imposta l'icona sulla barra del titolo e taskbar
    try:
        app.iconbitmap(resource_path("justo.ico"))
    except Exception as e:
        logging.warning(f"Icona non caricata: {e}")

    add_gui_logging_handler(app.log_queue)
    logging.getLogger().info("Programma avviato")
    app.mainloop()