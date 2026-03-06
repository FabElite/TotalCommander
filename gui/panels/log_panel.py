"""
Pannello log: Text widget con scrollbar e auto-scroll opzionale.
Legge i messaggi da una queue.Queue e li colora in base al livello.
"""
import tkinter as tk
from tkinter import ttk
import queue


class LogPanel(ttk.LabelFrame):
    """Row 3 della finestra principale."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="Log delle Attività", **kwargs)
        self.log_queue = queue.Queue()
        self._autoscroll = tk.BooleanVar(value=True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build()
        self._poll()

    def _build(self):
        sb = ttk.Scrollbar(self, orient="vertical")
        sb.grid(row=0, column=1, sticky="ns", pady=6)

        self._text = tk.Text(self, state='disabled', height=8,
                             yscrollcommand=sb.set)
        self._text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        sb.config(command=self._text.yview)

        ttk.Checkbutton(self, text="Auto-scroll",
                        variable=self._autoscroll
                        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))

        self._text.tag_configure('DEBUG',    foreground='#888888')
        self._text.tag_configure('INFO',     foreground='#111111')
        self._text.tag_configure('WARNING',  foreground='#B86000')
        self._text.tag_configure('ERROR',    foreground='#CC0000')
        self._text.tag_configure('CRITICAL', foreground='#ffffff',
                                 background='#CC0000', font=('Helvetica', 9, 'bold'))

    def _poll(self):
        try:
            while True:
                record = self.log_queue.get_nowait()
                tag = 'INFO'
                upper = record.upper()
                if ' - CRITICAL - ' in upper:
                    tag = 'CRITICAL'
                elif ' - ERROR - ' in upper:
                    tag = 'ERROR'
                elif ' - WARNING - ' in upper:
                    tag = 'WARNING'
                elif ' - DEBUG - ' in upper:
                    tag = 'DEBUG'
                self._text.config(state='normal')
                self._text.insert(tk.END, record + '\n', tag)
                self._text.config(state='disabled')
                if self._autoscroll.get():
                    self._text.yview(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll)
