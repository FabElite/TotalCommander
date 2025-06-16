import logging
from logging.handlers import RotatingFileHandler
from gui.main_window import MainWindow
import tkinter as tk

class TextHandler(logging.Handler):
    """Custom logging handler that sends log messages to a Tkinter Text widget."""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.config(state='normal')
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.config(state='disabled')
        self.text_widget.yview(tk.END)

def setup_logging(text_widget):
    LOG_FILENAME = "app.log"
    log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Handler per file rotativo
    file_handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(log_formatter)

    # Handler per la console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    # Handler per il Text widget
    text_handler = TextHandler(text_widget)
    text_handler.setFormatter(log_formatter)

    # Creazione del logger principale
    logger = logging.getLogger()  # Ottieni il root logger
    logger.setLevel(logging.INFO)  # Imposta il livello di logging
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.addHandler(text_handler)

    # Esempio di log nel main
    logger.info("Avvio del programma...")

if __name__ == "__main__":
    app = MainWindow()
    setup_logging(app.log_text)
    app.mainloop()