"""
Pannello dati live — layout affiancato BLE|Lorenz con scarto a destra.

  ┌──────────────────────────────────────────────────────────────────┐
  │  Misura        ║  BLE      ║ Lorenz    ║  Scarto                │
  │  Power [W]     ║  350      ║  339      ║  +3.2%                 │
  │  Speed [km/h]  ║  28.5     ║  28.8     ║  −1.1%                 │
  │  ──────────────────────────────────────────────────────────────  │
  │  Resistance    ║   15      ║   —       ║                        │
  │  Cadence       ║    0      ║   —       ║                        │
  │  Tot.Dist      ║    0      ║   —       ║                        │
  │  Elapsed       ║    0      ║   —       ║                        │
  │  Torque [Nm]   ║   —       ║  2.45     ║                        │
  │  Offset [Nm]   ║   —       ║  0.0012   ║  [Leggi]               │
  │  Hz            ║  2.1 Hz   ║  10.0 Hz  ║                        │
  │  N campioni    ║  [5    ]  ║  [20   ]  ║                        │
  │  [Abilita Dati BLE                  ]                            │
  └──────────────────────────────────────────────────────────────────┘
"""
import tkinter as tk
from tkinter import ttk
from collections import deque
from logic.delta_logic import (
    compute_speed_delta, compute_power_delta_pct, mean_or_none,
    color_for_speed_delta, color_for_power_delta,
    fmt_speed_delta, fmt_power_delta,
)
from gui.theme import (BLE_ACCENT as _BLE_ACCENT, LRZ_ACCENT as _LRZ_ACCENT,
                       BLE_BG as _BLE_BG, LRZ_BG as _LRZ_BG, NA_FG as _NA_FG)

# ── Font ─────────────────────────────────────────────────────────────────────
_F_TITLE = ('Helvetica', 9,  'bold')
_F_LABEL = ('Helvetica', 9)
_F_VAL_H = ('Helvetica', 13, 'bold')
_F_VAL_S = ('Helvetica', 9)
_F_DELTA = ('Helvetica', 11, 'bold')

_W_LABEL = 11


class LiveDataPanel(ttk.Frame):

    def __init__(self, parent, on_toggle_ftms,
                 on_lorenz_read_offset,
                 on_lorenz_avg_change,
                 on_smoothing_change,
                 smoothing_window: int = 5,
                 lorenz_avg_dim: int = 20,
                 speed_thresholds=(1.0, 3.0),
                 power_thresholds=(2.0, 5.0),
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._on_toggle_ftms  = on_toggle_ftms
        self._on_lorenz_offset = on_lorenz_read_offset
        self._on_lorenz_avg    = on_lorenz_avg_change
        self._on_smoothing     = on_smoothing_change
        self._speed_thr        = speed_thresholds
        self._power_thr        = power_thresholds
        self._lorenz_avg_dim   = max(1, int(lorenz_avg_dim))

        self._n = max(1, int(smoothing_window))
        self._speed_hist = deque(maxlen=self._n)
        self._power_hist = deque(maxlen=self._n)
        self._last_ble_speed = self._last_ble_power = None
        self._last_lrz_speed = self._last_lrz_power = None
        self._ftms_enabled = False   # stato esplicito (non dedotto dal testo del bottone)

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_main_panel()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build_main_panel(self):
        outer = ttk.LabelFrame(self, text="Misure")
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        # col 0: label misura | col 1: BLE | col 2: Lorenz | col 3: delta
        outer.grid_columnconfigure(0, weight=0)
        outer.grid_columnconfigure(1, weight=1, minsize=80)
        outer.grid_columnconfigure(2, weight=1, minsize=80)
        outer.grid_columnconfigure(3, weight=1, minsize=80)

        self._outer = outer
        self._build_header(outer)
        self._build_rows(outer)

    def _lbl(self, parent, text, font, bg, fg='#222222',
             anchor='center', width=None, row=0, col=0,
             padx=4, pady=2, sticky='nsew', colspan=1):
        kw = dict(text=text, font=font, bg=bg, fg=fg, anchor=anchor)
        if width:
            kw['width'] = width
        lbl = tk.Label(parent, **kw)
        lbl.grid(row=row, column=col, columnspan=colspan,
                 sticky=sticky, padx=padx, pady=pady)
        return lbl

    def _build_header(self, outer):
        bg = '#f0f0f0'
        # intestazione colonne
        self._lbl(outer, "Misura",  _F_TITLE, bg,         fg='#333333',
                  anchor='w', width=_W_LABEL, row=0, col=0, padx=(8,4))
        self._lbl(outer, "BLE",     _F_TITLE, _BLE_BG,    fg=_BLE_ACCENT,
                  row=0, col=1, padx=2, pady=(4,2))
        self._lbl(outer, "Lorenz",  _F_TITLE, _LRZ_BG,    fg=_LRZ_ACCENT,
                  row=0, col=2, padx=2, pady=(4,2))

        # Header scarto — N configurabile solo in Impostazioni
        tk.Label(outer, text="Scarto", font=_F_TITLE,
                 bg=bg, fg='#555555', anchor='center').grid(
            row=0, column=3, sticky='ew', padx=(4,8), pady=(4,2))

    def _val_lbl(self, parent, row, col, font, bg, bold_fg='#111111'):
        """Label usata come campo valore readonly — colorata."""
        lbl = tk.Label(parent, text="", font=font, bg=bg, fg=bold_fg,
                       anchor='center', relief='flat',
                       bd=0, padx=6, pady=2)
        lbl.grid(row=row, column=col, sticky='nsew', padx=2, pady=1)
        return lbl

    def _build_rows(self, outer):
        bg = '#f0f0f0'

        # ── Righe evidenziate: Power, Speed ───────────────────────────────────
        highlighted = [
            ('Power [W]',    '_ble_power', '_lrz_power',  '_delta_power_lbl'),
            ('Speed [km/h]', '_ble_speed', '_lrz_speed',  '_delta_speed_lbl'),
        ]
        for row, (label, ble_a, lrz_a, delta_a) in enumerate(highlighted, 1):
            self._lbl(outer, label, _F_LABEL, bg, fg='#333333',
                      anchor='w', width=_W_LABEL, row=row, col=0, padx=(8,4))

            e_ble = self._val_lbl(outer, row, 1, _F_VAL_H, _BLE_BG, _BLE_ACCENT)
            setattr(self, ble_a, e_ble)

            e_lrz = self._val_lbl(outer, row, 2, _F_VAL_H, _LRZ_BG, _LRZ_ACCENT)
            setattr(self, lrz_a, e_lrz)

            d_lbl = tk.Label(outer, text="—", font=_F_DELTA,
                             fg='#666666', anchor='center')
            d_lbl.grid(row=row, column=3, sticky='ew', padx=(4,8), pady=1)
            setattr(self, delta_a, d_lbl)

        # Separatore
        tk.Frame(outer, bg='#CCCCCC', height=1).grid(
            row=3, column=0, columnspan=4, sticky='ew', padx=8, pady=(4,2))

        # ── Righe standard BLE ────────────────────────────────────────────────
        self._ble_val_lbls = {}
        standard = [
            ('resistance',     'Resistance'),
            ('cadence',        'Cadence'),
            ('total_distance', 'Tot.Dist'),
            ('elapsed_time',   'Elapsed'),
        ]
        for i, (key, label) in enumerate(standard, 4):
            self._lbl(outer, label, _F_VAL_S, bg, fg='#333333',
                      anchor='w', width=_W_LABEL, row=i, col=0, padx=(8,4))
            lbl_ble = self._val_lbl(outer, i, 1, _F_VAL_S, _BLE_BG)
            self._ble_val_lbls[key] = lbl_ble
            # Lorenz: N/A
            self._lbl(outer, "—", _F_VAL_S, _LRZ_BG, fg=_NA_FG,
                      row=i, col=2, padx=2, pady=1)

        # ── Riga Torque ───────────────────────────────────────────────────────
        self._lbl(outer, "Torque [Nm]", _F_VAL_S, bg, fg='#333333',
                  anchor='w', width=_W_LABEL, row=8, col=0, padx=(8,4))
        self._lbl(outer, "—", _F_VAL_S, _BLE_BG, fg=_NA_FG,
                  row=8, col=1, padx=2, pady=1)
        self._lrz_torque = self._val_lbl(outer, 8, 2, _F_VAL_S, _LRZ_BG)

        # ── Riga Offset [Nm] (row 9, solo Lorenz) ────────────────────────────
        self._lbl(outer, "Offset [Nm]", _F_VAL_S, bg, fg='#333333',
                  anchor='w', width=_W_LABEL, row=9, col=0, padx=(8, 4))
        self._lbl(outer, "—", _F_VAL_S, _BLE_BG, fg=_NA_FG,
                  row=9, col=1, padx=2, pady=1)
        self._lrz_offset = self._val_lbl(outer, 9, 2, _F_VAL_S, _LRZ_BG, _LRZ_ACCENT)
        # "Leggi" occupa col 3 (normalmente delta, non usato per queste righe)
        ttk.Button(outer, text="Leggi", width=6,
                   command=self._on_lorenz_offset
                   ).grid(row=9, column=3, padx=(4, 8), pady=1, sticky='w')

        # ── Riga Hz (row 10) ─────────────────────────────────────────────────
        self._lbl(outer, "Hz", _F_VAL_S, bg, fg='#333333',
                  anchor='w', width=_W_LABEL, row=10, col=0, padx=(8, 4))
        self._ble_hz_lbl    = self._val_lbl(outer, 10, 1, _F_VAL_S, _BLE_BG, _BLE_ACCENT)
        self._lorenz_hz_lbl = self._val_lbl(outer, 10, 2, _F_VAL_S, _LRZ_BG, _LRZ_ACCENT)

        # ── Riga N campioni (row 11) ──────────────────────────────────────────
        self._lbl(outer, "N campioni", _F_VAL_S, bg, fg='#333333',
                  anchor='w', width=_W_LABEL, row=11, col=0, padx=(8, 4))

        self._ble_n_spin = ttk.Spinbox(outer, from_=1, to=500, increment=1, width=6)
        self._ble_n_spin.set(self._n)
        self._ble_n_spin.grid(row=11, column=1, padx=2, pady=(2, 4))
        self._ble_n_spin.config(command=self._on_ble_n_changed)
        self._ble_n_spin.bind('<Return>',   lambda e: self._on_ble_n_changed())
        self._ble_n_spin.bind('<FocusOut>', lambda e: self._on_ble_n_changed())

        self._lorenz_n_spin = ttk.Spinbox(outer, from_=1, to=5000, increment=1, width=6)
        self._lorenz_n_spin.set(self._lorenz_avg_dim)
        self._lorenz_n_spin.grid(row=11, column=2, padx=2, pady=(2, 4))
        self._lorenz_n_spin.config(command=self._on_lorenz_n_changed)
        self._lorenz_n_spin.bind('<Return>',   lambda e: self._on_lorenz_n_changed())
        self._lorenz_n_spin.bind('<FocusOut>', lambda e: self._on_lorenz_n_changed())

        # ── Pulsante toggle FTMS (row 12) ─────────────────────────────────────
        self._btn_toggle = ttk.Button(
            outer, text="Abilita Dati BLE",
            command=self._on_toggle_ftms, style='Data.Disabled.TButton')
        self._btn_toggle.grid(row=12, column=0, columnspan=2,
                              padx=(8, 2), pady=(2, 6), sticky='ew')

    # ── Handler spinbox N campioni ────────────────────────────────────────────

    def _on_ble_n_changed(self):
        try:
            n = max(1, int(float(self._ble_n_spin.get())))
        except (ValueError, TypeError):
            n = 1
        self._ble_n_spin.set(n)
        self.set_smoothing_window(n)
        if self._on_smoothing:
            self._on_smoothing(n)

    def _on_lorenz_n_changed(self):
        try:
            n = max(1, int(float(self._lorenz_n_spin.get())))
        except (ValueError, TypeError):
            n = 1
        self._lorenz_n_spin.set(n)
        self._lorenz_avg_dim = n
        if self._on_lorenz_avg:
            self._on_lorenz_avg(str(n))

    # ── Smoothing & delta ─────────────────────────────────────────────────────

    def _on_n_changed(self):
        # kept for compatibility (called by set_smoothing_window)
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
            lambda v: color_for_speed_delta(abs(v) if v is not None else None,
                                            self._speed_thr),
            fmt_speed_delta,
        )

    @staticmethod
    def _apply_delta(lbl, val, color_fn, fmt_fn):
        lbl.config(text=fmt_fn(val) if val is not None else "—",
                   fg=color_fn(val) if val is not None else '#666666')

    # ── Aggiornamento valori ──────────────────────────────────────────────────

    @staticmethod
    def _set_lbl(lbl, text):
        lbl.config(text=text)

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
                self._set_lbl(self._ble_power, str(v))
                self._last_ble_power = float(v)
            elif ui == 'speed':
                self._set_lbl(self._ble_speed, str(v))
                self._last_ble_speed = float(v)
            elif ui in self._ble_val_lbls:
                self._set_lbl(self._ble_val_lbls[ui], str(v))
        self._refresh_delta()

    def clear_ble(self):
        for lbl in [self._ble_power, self._ble_speed] + \
                   list(self._ble_val_lbls.values()):
            self._set_lbl(lbl, '')
        self._last_ble_speed = self._last_ble_power = None
        self._speed_hist.clear()
        self._power_hist.clear()
        self.set_ble_hz(None)
        self._refresh_delta()

    def update_lorenz(self, data: dict):
        p = data.get("power_lorenz")
        s = data.get("speed_avg_lorenz")
        t = data.get("torque_lorenz")
        if p is not None:
            self._set_lbl(self._lrz_power, f"{p:.2f}")
            self._last_lrz_power = float(p)
        if s is not None:
            self._set_lbl(self._lrz_speed, f"{s:.2f}")
            self._last_lrz_speed = float(s)
        self._set_lbl(self._lrz_torque, f"{t:.2f}" if t is not None else "N/A")
        self._refresh_delta()

    # ── API pubblica ──────────────────────────────────────────────────────────

    def is_ftms_enabled(self) -> bool:
        return self._ftms_enabled

    def set_ftms_button(self, enabled: bool):
        self._ftms_enabled = enabled
        self._btn_toggle.config(
            text='Disabilita Dati BLE' if enabled else 'Abilita Dati BLE',
            style='Data.Enabled.TButton' if enabled else 'Data.Disabled.TButton')

    def get_smoothing_window(self) -> int:
        return self._n

    def set_thresholds(self, speed, power):
        self._speed_thr = speed
        self._power_thr = power
        self._refresh_delta()

    def set_smoothing_window(self, n: int):
        n = max(1, int(n))
        if n == self._n:
            return
        self._n = n
        self._speed_hist = deque(list(self._speed_hist)[-n:], maxlen=n)
        self._power_hist = deque(list(self._power_hist)[-n:], maxlen=n)
        self._refresh_delta()

    def set_offset(self, value: float):
        """Aggiorna la label offset Lorenz."""
        self._lrz_offset.config(text=f'{value:.4f}')

    def set_ble_hz(self, hz):
        """Aggiorna la frequenza BLE (None → '—')."""
        self._ble_hz_lbl.config(text=f'{hz:.1f} Hz' if hz else '—')

    def set_lorenz_hz(self, hz):
        """Aggiorna la frequenza Lorenz misurata (None → '—')."""
        self._lorenz_hz_lbl.config(text=f'{hz:.1f} Hz' if hz else '—')

    def set_lorenz_avg(self, n: int):
        """Aggiorna lo spinbox Lorenz N campioni (chiamato al caricamento settings)."""
        n = max(1, int(n))
        self._lorenz_avg_dim = n
        self._lorenz_n_spin.set(n)