"""
Barra laterale collassabile — lato destro della finestra principale.

  collapsed:  │▶│     ← strip 22px, clic espande
  expanded:   │◀│  ┌─ Sensore COM ──────────┐
              │ │  │ Porta: [COM3▼] [🔄]    │
              │ │  │ [Connetti] [Disconnetti]│
              │ │  ├─ Dati COM ─────────────┤
              │ │  │ Valore 1    12.34       │
              │ │  │ Valore 2     0.00       │
              │C│  │ Valore 3      N/A       │
              │O│  │ Valore 4      N/A       │
              │M│  └────────────────────────┘
"""
import math
import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports

_STRIP_W   = 22      # larghezza strip sempre visibile
_STRIP_BG  = '#d0d0d0'
_STRIP_HOV = '#b8b8b8'
_F_SMALL   = ('Helvetica', 7)
_F_NORMAL  = ('Helvetica', 9)


class CollapsibleSidebar(ttk.Frame):
    """Barra laterale destra collassabile con sezione COM."""

    def __init__(self, parent,
                 on_serial_connect,
                 on_serial_disconnect,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._cb_connect    = on_serial_connect
        self._cb_disconnect = on_serial_disconnect
        self._expanded      = False

        self.grid_columnconfigure(0, weight=0)  # strip
        self.grid_columnconfigure(1, weight=0)  # content
        self.grid_rowconfigure(0, weight=1)

        self._build_strip()
        self._build_content()

    # ── Strip toggle ──────────────────────────────────────────────────────────

    def _build_strip(self):
        strip = tk.Frame(self, bg=_STRIP_BG, width=_STRIP_W, cursor='hand2')
        strip.grid(row=0, column=0, sticky='nsew')
        strip.grid_propagate(False)
        strip.bind('<Button-1>', lambda e: self.toggle())
        strip.bind('<Enter>',    lambda e: strip.config(bg=_STRIP_HOV))
        strip.bind('<Leave>',    lambda e: strip.config(bg=_STRIP_BG))

        self._arrow = tk.Label(strip, text='◀', bg=_STRIP_BG,
                               fg='#444444', font=('Helvetica', 9, 'bold'),
                               cursor='hand2')
        self._arrow.place(relx=0.5, rely=0.12, anchor='n')
        self._arrow.bind('<Button-1>', lambda e: self.toggle())

        vtxt = tk.Label(strip, text='C\nO\nM', bg=_STRIP_BG,
                        fg='#666666', font=_F_SMALL, cursor='hand2')
        vtxt.place(relx=0.5, rely=0.5, anchor='center')
        vtxt.bind('<Button-1>', lambda e: self.toggle())

        self._strip = strip

    # ── Pannello contenuto ────────────────────────────────────────────────────

    def _build_content(self):
        outer = ttk.Frame(self)
        self._content = outer
        # Non griddato finché non espanso

        # ── COM connection ────────────────────────────────────────────────────
        com_f = ttk.LabelFrame(outer, text="Sensore COM")
        com_f.pack(fill='x', padx=(0, 6), pady=(8, 4))
        com_f.grid_columnconfigure(1, weight=1)

        ttk.Label(com_f, text="Porta:", font=_F_NORMAL).grid(
            row=0, column=0, sticky='e', padx=(6, 4), pady=(6, 2))
        self._com_combo = ttk.Combobox(com_f, width=10, font=_F_NORMAL)
        self._com_combo['values'] = self._get_ports()
        if self._com_combo['values']:
            self._com_combo.set(self._com_combo['values'][0])
        self._com_combo.grid(row=0, column=1, sticky='ew', padx=(0, 2), pady=(6, 2))
        tk.Button(com_f, text='🔄', command=self._refresh_ports,
                  font=('Segoe UI Emoji', 11), relief='flat', bd=1,
                  cursor='hand2', padx=2, pady=1
                  ).grid(row=0, column=2, padx=(0, 6), pady=(6, 2))

        rc = ttk.Frame(com_f)
        rc.grid(row=1, column=0, columnspan=3, sticky='ew', padx=6, pady=(2, 6))
        rc.grid_columnconfigure(0, weight=1)
        rc.grid_columnconfigure(1, weight=1)
        ttk.Button(rc, text='Connetti',
                   command=lambda: self._cb_connect(self._com_combo.get())
                   ).grid(row=0, column=0, sticky='ew', padx=(0, 2))
        ttk.Button(rc, text='Disconnetti',
                   command=self._cb_disconnect
                   ).grid(row=0, column=1, sticky='ew', padx=(2, 0))

        # ── Dati COM ──────────────────────────────────────────────────────────
        data_f = ttk.LabelFrame(outer, text="Dati COM")
        data_f.pack(fill='x', padx=(0, 6), pady=4)
        data_f.grid_columnconfigure(1, weight=1)

        self._com_vals = []
        for i in range(4):
            ttk.Label(data_f, text=f"Valore {i+1}", font=_F_NORMAL,
                      anchor='e', width=8).grid(
                row=i, column=0, sticky='e', padx=(8, 4), pady=3)
            e = ttk.Entry(data_f, state='readonly', justify='right',
                          width=10, font=_F_NORMAL)
            e.grid(row=i, column=1, sticky='ew', padx=(0, 8), pady=3)
            self._com_vals.append(e)

    # ── Toggle espansione ─────────────────────────────────────────────────────

    def toggle(self):
        top = self.winfo_toplevel()
        top.update_idletasks()
        win_w = top.winfo_width()
        win_h = top.winfo_height()

        self._expanded = not self._expanded
        if self._expanded:
            self._content.grid(row=0, column=1, sticky='nsew')
            self._arrow.config(text='▶')
            top.update_idletasks()
            delta = self._content.winfo_reqwidth()
            top.geometry(f"{win_w + delta}x{win_h}")
        else:
            top.update_idletasks()
            delta = self._content.winfo_width()
            self._content.grid_remove()
            self._arrow.config(text='◀')
            top.geometry(f"{max(win_w - delta, 400)}x{win_h}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def _refresh_ports(self):
        current = self._com_combo.get()
        ports = self._get_ports()
        self._com_combo['values'] = ports
        self._com_combo.set(
            current if current in ports else (ports[0] if ports else ''))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def update_serial(self, data: dict):
        for i, key in enumerate(['Valore1', 'Valore2', 'Valore3', 'Valore4']):
            v = data.get(key)
            text = f"{v:.2f}" if (v is not None and not math.isnan(v)) else 'N/A'
            e = self._com_vals[i]
            e.config(state='normal')
            e.delete(0, 'end')
            e.insert(0, text)
            e.config(state='readonly')

    def is_expanded(self) -> bool:
        return self._expanded