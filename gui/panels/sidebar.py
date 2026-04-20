"""
Barra laterale collassabile — lato destro della finestra principale.

  collapsed:  │▶│     ← strip 22px, clic espande
  expanded:   │◀│  ┌─ Sensore COM ──────────┐
              │ │  │ Porta: [COM3▼] [🔄]    │
              │ │  │ [Connetti] [Disconnetti]│
              │ │  ├─ Dati COM ─────────────┤
              │ │  │ Valore 1    12.34       │
              │C│  ├─ Alimentatore PSU ──────┤
              │O│  │ Porta: [COM12▼] [🔄]   │
              │M│  │ [Connetti] [Disconnetti]│
              │+│  ├─ Misure PSU ────────────┤
              │P│  │ Tensione    12.340 V     │
              │S│  │ Corrente     1.234 A     │
              │U│  │ Potenza     15.230 W     │
              │ │  │ [⚙ Impostazioni PSU...] │
              │ │  └────────────────────────┘
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

_LED_COLORS = {'ok': '#00cc44', 'err': '#cc2222', 'warn': '#cc8800', 'off': '#555555'}


class CollapsibleSidebar(ttk.Frame):
    """Barra laterale destra collapsabile con sezione COM e PSU."""

    def __init__(self, parent,
                 on_serial_connect,
                 on_serial_disconnect,
                 on_psu_connect,
                 on_psu_disconnect,
                 on_psu_settings,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._cb_connect      = on_serial_connect
        self._cb_disconnect   = on_serial_disconnect
        self._cb_psu_connect  = on_psu_connect
        self._cb_psu_disconnect = on_psu_disconnect
        self._cb_psu_settings = on_psu_settings
        self._expanded        = False

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

        vtxt = tk.Label(strip, text='E\nX\nT\nR\nA', bg=_STRIP_BG,
                        fg='#666666', font=_F_SMALL, cursor='hand2')
        vtxt.place(relx=0.5, rely=0.5, anchor='center')
        vtxt.bind('<Button-1>', lambda e: self.toggle())

        self._strip = strip

    # ── Pannello contenuto ────────────────────────────────────────────────────

    def _build_content(self):
        outer = ttk.Frame(self)
        self._content = outer
        # Non griddato finché non espanso

        # ── LED di stato COM e PSU ────────────────────────────────────────────
        # --- LED status bar (altezza allineata alla StatusBar) ---

        led_f = tk.Frame(
            outer,
            bg='#1e1e2e'
        )
        led_f.pack(fill='x', padx=(0, 6), pady=5)


        def _led_pair(parent, col, label, attr):
            g = tk.Frame(parent, bg='#1e1e2e')
            g.grid(row=0, column=col, padx=10)
            led = tk.Label(g, text='●', bg='#1e1e2e', fg='#555555',
                           font=('Helvetica', 25))
            led.grid(row=0, column=0, padx=(0, 3))
            tk.Label(g, text=label, bg='#1e1e2e', fg='#aaaacc',
                     font=('Helvetica', 8)).grid(row=0, column=1)
            # Riga vuota row=1: pareggia l'altezza della StatusBar che ha label su row=1
            tk.Label(g, text='', bg='#1e1e2e',
                     font=('Helvetica', 8)).grid(row=1, column=0, columnspan=2, pady=(0, 1))
            setattr(self, attr, led)

        _led_pair(led_f, 0, 'COM', '_led_com')
        _led_pair(led_f, 1, 'PSU', '_led_psu')

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

        # ── Alimentatore PSU ──────────────────────────────────────────────────
        self._build_psu_section(outer)

    def _build_psu_section(self, outer):
        """Sezione connessione e misure alimentatore SCPI."""
        # ── Connessione ───────────────────────────────────────────────────────
        psu_f = ttk.LabelFrame(outer, text="Alimentatore PSU")
        psu_f.pack(fill='x', padx=(0, 6), pady=(8, 4))
        psu_f.grid_columnconfigure(1, weight=1)

        ttk.Label(psu_f, text="Porta:", font=_F_NORMAL).grid(
            row=0, column=0, sticky='e', padx=(6, 4), pady=(6, 2))
        self._psu_combo = ttk.Combobox(psu_f, width=10, font=_F_NORMAL)
        self._psu_combo['values'] = self._get_ports()
        if self._psu_combo['values']:
            self._psu_combo.set(self._psu_combo['values'][0])
        self._psu_combo.grid(row=0, column=1, sticky='ew', padx=(0, 2), pady=(6, 2))
        tk.Button(psu_f, text='🔄', command=self._refresh_psu_ports,
                  font=('Segoe UI Emoji', 11), relief='flat', bd=1,
                  cursor='hand2', padx=2, pady=1
                  ).grid(row=0, column=2, padx=(0, 6), pady=(6, 2))

        rc = ttk.Frame(psu_f)
        rc.grid(row=1, column=0, columnspan=3, sticky='ew', padx=6, pady=(2, 4))
        rc.grid_columnconfigure(0, weight=1)
        rc.grid_columnconfigure(1, weight=1)
        ttk.Button(rc, text='Connetti',
                   command=lambda: self._cb_psu_connect(self._psu_combo.get())
                   ).grid(row=0, column=0, sticky='ew', padx=(0, 2))
        ttk.Button(rc, text='Disconnetti',
                   command=self._cb_psu_disconnect
                   ).grid(row=0, column=1, sticky='ew', padx=(2, 0))

        # ── Misure PSU ────────────────────────────────────────────────────────
        meas_f = ttk.LabelFrame(outer, text="Misure PSU")
        meas_f.pack(fill='x', padx=(0, 6), pady=4)
        meas_f.grid_columnconfigure(1, weight=1)

        self._psu_vals = {}
        _rows = [
            ('tensione', 'Tensione', 'V'),
            ('corrente', 'Corrente', 'A'),
            ('potenza',  'Potenza',  'W'),
        ]
        for i, (key, label, unit) in enumerate(_rows):
            ttk.Label(meas_f, text=label, font=_F_NORMAL,
                      anchor='e', width=8).grid(
                row=i, column=0, sticky='e', padx=(8, 4), pady=3)
            e = ttk.Entry(meas_f, state='readonly', justify='right',
                          width=10, font=_F_NORMAL)
            e.grid(row=i, column=1, sticky='ew', padx=(0, 2), pady=3)
            ttk.Label(meas_f, text=unit, font=_F_NORMAL, width=2).grid(
                row=i, column=2, sticky='w', padx=(0, 6), pady=3)
            self._psu_vals[key] = e

        ttk.Button(meas_f, text='⚙  Impostazioni PSU…',
                   command=self._cb_psu_settings
                   ).grid(row=3, column=0, columnspan=3,
                          sticky='ew', padx=6, pady=(4, 8))

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

    def _refresh_psu_ports(self):
        current = self._psu_combo.get()
        ports = self._get_ports()
        self._psu_combo['values'] = ports
        self._psu_combo.set(
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

    def update_psu(self, tensione, corrente, potenza):
        """Aggiorna i campi di misura PSU. Valori None → 'N/A'."""
        for key, val in [('tensione', tensione), ('corrente', corrente), ('potenza', potenza)]:
            e = self._psu_vals[key]
            text = f"{val:.3f}" if val is not None else 'N/A'
            e.config(state='normal')
            e.delete(0, 'end')
            e.insert(0, text)
            e.config(state='readonly')

    def set_com(self, state: str):
        """Aggiorna il LED COM nella sidebar."""
        self._led_com.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_psu(self, state: str):
        """Aggiorna il LED PSU nella sidebar."""
        self._led_psu.config(fg=_LED_COLORS.get(state, '#555555'))

    def is_expanded(self) -> bool:
        return self._expanded