"""
Pannello dati live — tre colonne nette.

  ┌─────────────────────────────────────────────────────────┐  ┌──────────┐
  │▌ BLE FTMS        │   Δ% (N= )   │      LORENZ        ▐│  │ Dati COM │
  │▌ Power [W]  [350]│   +3.2% pwr  │ [339]  Power [W]  ▐│  │ Valore 1 │
  │▌ Speed km/h [28.5│   −1.1% spd  │ [28.8] Speed km/h ▐│  │ Valore 2 │
  │▌ Resistance  [15]│              │        Torque  [Nm]▐│  │ Valore 3 │
  │▌ Cadence    [  0]│              │                    ▐│  │ Valore 4 │
  │▌ Tot.Dist   [  0]│              │                    ▐│  │          │
  │▌ Elapsed    [  0]│              │                    ▐│  │          │
  │▌ [Abilita Dati]  │              │                    ▐│  │          │
  └─────────────────────────────────────────────────────────┘  └──────────┘

BLE e Lorenz sono due colonne indipendenti e complete.
Il delta occupa la colonna centrale solo per Power e Speed.
"""
import tkinter as tk
from tkinter import ttk
import math
from collections import deque
from logic.delta_logic import (
    compute_speed_delta, compute_power_delta_pct, mean_or_none,
    color_for_speed_delta, color_for_power_delta,
    fmt_speed_delta, fmt_power_delta,
)

# ── Palette ──────────────────────────────────────────────────────────────────
_BLE_ACCENT = '#1565C0'
_LRZ_ACCENT = '#B85C00'
_BLE_BG     = '#EEF3FB'
_LRZ_BG     = '#FBF2EE'
_STRIP_W    = 5

# ── Font ─────────────────────────────────────────────────────────────────────
_F_TITLE = ('Helvetica', 9,  'bold')
_F_LABEL = ('Helvetica', 9)
_F_VAL_H = ('Helvetica', 13, 'bold')   # Power / Speed: font grande
_F_VAL_S = ('Helvetica', 9)            # altri campi: font normale
_F_DELTA = ('Helvetica', 11, 'bold')

# ── Larghezze entry ───────────────────────────────────────────────────────────
_W_H = 8    # entry campi evidenziati
_W_S = 8    # entry campi standard


class LiveDataPanel(ttk.Frame):
    """Pannello dati live con confronto BLE↔Lorenz integrato."""

    def __init__(self, parent, on_toggle_ftms,
                 smoothing_window: int = 5,
                 speed_thresholds=(1.0, 3.0),
                 power_thresholds=(2.0, 5.0),
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._on_toggle_ftms = on_toggle_ftms
        self._speed_thr = speed_thresholds
        self._power_thr = power_thresholds

        self._n = max(1, int(smoothing_window))
        self._speed_hist = deque(maxlen=self._n)
        self._power_hist = deque(maxlen=self._n)
        self._last_ble_speed = self._last_ble_power = None
        self._last_lrz_speed = self._last_lrz_power = None

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_main_panel()
        self._build_com_box()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build_main_panel(self):
        outer = ttk.LabelFrame(self, text="Misure")
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        # Col 0: striscia BLE  Col 1: contenuto BLE
        # Col 2: delta         Col 3: contenuto Lorenz  Col 4: striscia Lorenz
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_columnconfigure(3, weight=1)

        # Strisce colorate
        tk.Frame(outer, bg=_BLE_ACCENT, width=_STRIP_W).grid(
            row=0, column=0, rowspan=99, sticky='ns', padx=(6, 0), pady=6)
        tk.Frame(outer, bg=_LRZ_ACCENT, width=_STRIP_W).grid(
            row=0, column=4, rowspan=99, sticky='ns', padx=(0, 6), pady=6)

        self._build_ble_column(outer)
        self._build_delta_column(outer)
        self._build_lorenz_column(outer)

    # ── Colonna BLE ───────────────────────────────────────────────────────────

    def _build_ble_column(self, outer):
        f = tk.Frame(outer, bg=_BLE_BG)
        f.grid(row=0, column=1, sticky='nsew', padx=(2, 4), pady=6)
        f.grid_columnconfigure(0, weight=0)
        f.grid_columnconfigure(1, weight=1)

        tk.Label(f, text="BLE FTMS", font=_F_TITLE,
                 fg=_BLE_ACCENT, bg=_BLE_BG, anchor='w'
                 ).grid(row=0, column=0, columnspan=2, sticky='w',
                        padx=8, pady=(4, 6))

        # Campi evidenziati (Power, Speed) — font grande
        highlighted = [('Power [W]', '_ble_power'), ('Speed [km/h]', '_ble_speed')]
        for i, (label, attr) in enumerate(highlighted, start=1):
            tk.Label(f, text=label, font=_F_LABEL, bg=_BLE_BG,
                     anchor='e', width=12).grid(row=i, column=0, sticky='e',
                                                padx=(8, 4), pady=2)
            e = ttk.Entry(f, state='readonly', justify='right',
                          width=_W_H, font=_F_VAL_H)
            e.grid(row=i, column=1, sticky='w', padx=(0, 8), pady=2)
            setattr(self, attr, e)

        # Separatore sottile
        tk.Frame(f, bg='#C8D8EE', height=1).grid(
            row=3, column=0, columnspan=2, sticky='ew', padx=8, pady=(4, 2))

        # Campi standard — font normale
        self._ble_entries = {}
        standard = [
            ('resistance',     'Resistance'),
            ('cadence',        'Cadence'),
            ('total_distance', 'Tot.Dist'),
            ('elapsed_time',   'Elapsed'),
        ]
        for i, (key, label) in enumerate(standard, start=4):
            tk.Label(f, text=label, font=_F_VAL_S, bg=_BLE_BG,
                     anchor='e', width=12).grid(row=i, column=0, sticky='e',
                                                padx=(8, 4), pady=1)
            e = ttk.Entry(f, state='readonly', justify='right',
                          width=_W_S, font=_F_VAL_S)
            e.grid(row=i, column=1, sticky='w', padx=(0, 8), pady=1)
            self._ble_entries[key] = e

        # Pulsante toggle
        self._btn_toggle = ttk.Button(
            f, text="Abilita Dati",
            command=self._on_toggle_ftms, style='Data.Disabled.TButton')
        self._btn_toggle.grid(row=8, column=0, columnspan=2,
                              padx=8, pady=(6, 6), sticky='ew')

    # ── Colonna delta ─────────────────────────────────────────────────────────

    def _build_delta_column(self, outer):
        f = ttk.Frame(outer)
        f.grid(row=0, column=2, sticky='n', padx=6, pady=6)

        # Header con N=
        hdr = ttk.Frame(f)
        hdr.grid(row=0, column=0, sticky='ew', pady=(2, 10))
        ttk.Label(hdr, text="Δ%  N=", font=('Helvetica', 8)).grid(row=0, column=0)
        self._n_spin = ttk.Spinbox(hdr, from_=1, to=999, increment=1, width=4,
                                   command=self._on_n_changed)
        self._n_spin.set(self._n)
        self._n_spin.grid(row=0, column=1, padx=(3, 0))
        self._n_spin.bind("<Return>",   lambda e: self._on_n_changed())
        self._n_spin.bind("<FocusOut>", lambda e: self._on_n_changed())

        # Delta Power (allineato con riga Power)
        self._delta_power_lbl = tk.Label(
            f, text="—", width=10, anchor='center',
            fg='#666666', font=_F_DELTA)
        self._delta_power_lbl.grid(row=1, column=0, pady=2)

        # Delta Speed (allineato con riga Speed)
        self._delta_speed_lbl = tk.Label(
            f, text="—", width=10, anchor='center',
            fg='#666666', font=_F_DELTA)
        self._delta_speed_lbl.grid(row=2, column=0, pady=2)

    # ── Colonna Lorenz ────────────────────────────────────────────────────────

    def _build_lorenz_column(self, outer):
        f = tk.Frame(outer, bg=_LRZ_BG)
        f.grid(row=0, column=3, sticky='nsew', padx=(4, 2), pady=6)
        f.grid_columnconfigure(0, weight=0)
        f.grid_columnconfigure(1, weight=1)

        tk.Label(f, text="LORENZ", font=_F_TITLE,
                 fg=_LRZ_ACCENT, bg=_LRZ_BG, anchor='w'
                 ).grid(row=0, column=0, columnspan=2, sticky='w',
                        padx=8, pady=(4, 6))

        # Campi evidenziati (Power, Speed) — font grande
        highlighted = [('Power [W]', '_lrz_power'), ('Speed [km/h]', '_lrz_speed')]
        for i, (label, attr) in enumerate(highlighted, start=1):
            tk.Label(f, text=label, font=_F_LABEL, bg=_LRZ_BG,
                     anchor='e', width=12).grid(row=i, column=0, sticky='e',
                                                padx=(8, 4), pady=2)
            e = ttk.Entry(f, state='readonly', justify='right',
                          width=_W_H, font=_F_VAL_H)
            e.grid(row=i, column=1, sticky='w', padx=(0, 8), pady=2)
            setattr(self, attr, e)

        # Separatore sottile
        tk.Frame(f, bg='#EED8C8', height=1).grid(
            row=3, column=0, columnspan=2, sticky='ew', padx=8, pady=(4, 2))

        # Torque (unico campo standard Lorenz)
        tk.Label(f, text="Torque", font=_F_VAL_S, bg=_LRZ_BG,
                 anchor='e', width=12).grid(row=4, column=0, sticky='e',
                                            padx=(8, 4), pady=1)
        self._lrz_torque = ttk.Entry(f, state='readonly', justify='right',
                                     width=_W_S, font=_F_VAL_S)
        self._lrz_torque.grid(row=4, column=1, sticky='w', padx=(0, 8), pady=1)

    # ── COM box (nascosta di default, controllata da main_window) ────────────

    def _build_com_box(self):
        self._com_frame = ttk.LabelFrame(self, text="Dati COM")
        self._com_frame.grid_columnconfigure(1, weight=1)
        self._com = []
        for i in range(4):
            tk.Label(self._com_frame, text=f"Valore {i+1}", font=_F_VAL_S,
                     anchor='e', width=8).grid(row=i, column=0, sticky='e',
                                               padx=(8, 4), pady=3)
            e = ttk.Entry(self._com_frame, state='readonly', justify='right',
                          width=8, font=_F_VAL_S)
            e.grid(row=i, column=1, sticky='ew', padx=(0, 8), pady=3)
            self._com.append(e)

    # ── Smoothing & delta ─────────────────────────────────────────────────────

    def _on_n_changed(self):
        try:
            n = max(1, int(self._n_spin.get()))
        except (ValueError, TypeError):
            n = self._n
        if n != self._n:
            self._n = n
            self._speed_hist = deque(list(self._speed_hist)[-n:], maxlen=n)
            self._power_hist = deque(list(self._power_hist)[-n:], maxlen=n)
            self._n_spin.set(n)
        self._refresh_delta()

    def _refresh_delta(self):
        d_spd = compute_speed_delta(self._last_ble_speed, self._last_lrz_speed)
        d_pwr = compute_power_delta_pct(self._last_ble_power, self._last_lrz_power)

        if d_spd is not None: self._speed_hist.append(d_spd)
        if d_pwr is not None: self._power_hist.append(d_pwr)

        avg_spd = mean_or_none(self._speed_hist)
        avg_pwr = mean_or_none(self._power_hist)

        self._apply_delta(
            self._delta_power_lbl,
            avg_pwr if avg_pwr is not None else d_pwr,
            lambda v: color_for_power_delta(v, self._power_thr),
            fmt_power_delta,
        )
        self._apply_delta(
            self._delta_speed_lbl,
            avg_spd if avg_spd is not None else d_spd,
            lambda v: color_for_speed_delta(abs(v) if v is not None else None, self._speed_thr),
            fmt_speed_delta,
        )

    @staticmethod
    def _apply_delta(lbl, val, color_fn, fmt_fn):
        lbl.config(text=fmt_fn(val) if val is not None else "—",
                   fg=color_fn(val) if val is not None else '#666666')

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _set_ro(entry, text):
        entry.config(state='normal')
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(state='readonly')

    # ── API pubblica ──────────────────────────────────────────────────────────

    _BLE_KEY_MAP = {
        'Pwr':     'power',
        'Spd':     'speed',
        'Cad':     'cadence',
        'ElaTime': 'elapsed_time',
        'Res':     'resistance',
        'TotDist': 'total_distance',
    }

    def update_ble(self, bike_data: dict):
        for k, v in bike_data.items():
            if v is None:
                continue
            ui = self._BLE_KEY_MAP.get(k)
            if ui is None:
                continue
            if ui == 'power':
                self._set_ro(self._ble_power, str(v));  self._last_ble_power = float(v)
            elif ui == 'speed':
                self._set_ro(self._ble_speed, str(v));  self._last_ble_speed = float(v)
            elif ui in self._ble_entries:
                self._set_ro(self._ble_entries[ui], str(v))
        self._refresh_delta()

    def clear_ble(self):
        for e in [self._ble_power, self._ble_speed] + list(self._ble_entries.values()):
            self._set_ro(e, '')
        self._last_ble_speed = self._last_ble_power = None
        self._speed_hist.clear();  self._power_hist.clear()
        self._refresh_delta()

    def update_lorenz(self, data: dict):
        p = data.get("power_lorenz")
        s = data.get("speed_avg_lorenz")
        t = data.get("torque_lorenz")
        if p is not None:
            self._set_ro(self._lrz_power, f"{p:.2f}");  self._last_lrz_power = float(p)
        if s is not None:
            self._set_ro(self._lrz_speed, f"{s:.2f}");  self._last_lrz_speed = float(s)
        self._set_ro(self._lrz_torque, f"{t:.2f}" if t is not None else "N/A")
        self._refresh_delta()

    def update_serial(self, data: dict):
        def fmt(v):
            return f"{v:.2f}" if (v is not None and not math.isnan(v)) else 'N/A'
        for i, key in enumerate(['Valore1', 'Valore2', 'Valore3', 'Valore4']):
            self._set_ro(self._com[i], fmt(data.get(key)))

    def is_ftms_enabled(self) -> bool:
        return self._btn_toggle.cget('text') == 'Disabilita Dati'

    def set_ftms_button(self, enabled: bool):
        self._btn_toggle.config(
            text='Disabilita Dati' if enabled else 'Abilita Dati',
            style='Data.Enabled.TButton' if enabled else 'Data.Disabled.TButton')

    def get_smoothing_window(self) -> int:
        return self._n

    def set_thresholds(self, speed, power):
        self._speed_thr = speed;  self._power_thr = power
        self._refresh_delta()

    def set_com_visible(self, visible: bool):
        if visible:
            self.grid_columnconfigure(1, weight=1)
            self._com_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        else:
            self._com_frame.grid_remove()
            self.grid_columnconfigure(1, weight=0, minsize=0)