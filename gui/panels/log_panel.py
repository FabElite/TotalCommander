"""
Pannello log: Text widget con scrollbar, auto-scroll e toggle debug.
Legge i messaggi da una queue.Queue e li colora in base al livello.
"""
import tkinter as tk
from tkinter import ttk
import queue


class LogPanel(ttk.LabelFrame):
    """Row 3 della finestra principale."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="Log delle Attività", **kwargs)
        self.log_queue    = queue.Queue()
        self._autoscroll  = tk.BooleanVar(value=True)
        self._debug_mode  = tk.BooleanVar(value=False)
        self._debug_cb    = None
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

        # Barra inferiore
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, columnspan=2, sticky='w', padx=10, pady=(0, 5))

        ttk.Checkbutton(bar, text="Auto-scroll",
                        variable=self._autoscroll
                        ).grid(row=0, column=0, padx=(0, 16))

        ttk.Checkbutton(bar, text="Debug",
                        variable=self._debug_mode,
                        command=self._on_debug_toggle
                        ).grid(row=0, column=1)

        tk.Label(bar, text="(mostra messaggi interni delle librerie)",
                 font=('Helvetica', 7), fg='#888888'
                 ).grid(row=0, column=2, padx=(4, 0))

        # Tag colori
        self._text.tag_configure('DEBUG',    foreground='#888888')
        self._text.tag_configure('INFO',     foreground='#111111')
        self._text.tag_configure('WARNING',  foreground='#B86000')
        self._text.tag_configure('ERROR',    foreground='#CC0000')
        self._text.tag_configure('CRITICAL', foreground='#ffffff',
                                 background='#CC0000',
                                 font=('Helvetica', 9, 'bold'))

    def _on_debug_toggle(self):
        if self._debug_cb:
            self._debug_cb(self._debug_mode.get())

    def _poll(self):
        try:
            while True:
                record = self.log_queue.get_nowait()
                upper = record.upper()
                if   ' - CRITICAL - ' in upper: tag = 'CRITICAL'
                elif ' - ERROR - '    in upper: tag = 'ERROR'
                elif ' - WARNING - '  in upper: tag = 'WARNING'
                elif ' - DEBUG - '    in upper: tag = 'DEBUG'
                else:                           tag = 'INFO'

                self._text.config(state='normal')
                self._text.insert(tk.END, record + '\n', tag)
                self._text.config(state='disabled')
                if self._autoscroll.get():
                    self._text.yview(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def set_debug_callback(self, fn):
        """Chiamato da main.py dopo la creazione del handler GUI."""
        self._debug_cb = fn