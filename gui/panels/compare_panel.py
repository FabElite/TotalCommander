"""
Pannello di confronto BLE FTMS ↔ Lorenz con calcolo Δ e smoothing.
Tutta la logica di calcolo/colore usa le funzioni pure di delta_logic.
"""
import tkinter as tk
from tkinter import ttk
from collections import deque
from logic.delta_logic import (
    compute_speed_delta, compute_power_delta_pct, mean_or_none,
    color_for_speed_delta, color_for_power_delta,
    fmt_speed_delta, fmt_power_delta,
)


class ComparePanel(ttk.LabelFrame):
    """Mostra Speed e Power di BLE e Lorenz affiancati con il Δ centrale."""

    def __init__(self, parent,
                 smoothing_window: int = 5,
                 speed_thresholds=(1.0, 3.0),
                 power_thresholds=(2.0, 5.0),
                 value_font=('Helvetica', 12, 'bold'),
                 **kwargs):
        super().__init__(parent, text="Confronto BLE ↔ Lorenz", **kwargs)
        self._speed_thr = speed_thresholds
        self._power_thr = power_thresholds
        self._smoothing_window = max(1, int(smoothing_window))
        self._value_font = value_font

        self._speed_hist = deque(maxlen=self._smoothing_window)
        self._power_hist = deque(maxlen=self._smoothing_window)
        self._last_ble_speed = None
        self._last_ble_power = None
        self._last_lrz_speed = None
        self._last_lrz_power = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)
        self._build()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build(self):
        # Colonna sinistra – BLE
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=8)
        left.grid_columnconfigure(1, weight=1)
        ttk.Label(left, text="BLE FTMS", anchor="center").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(left, text="Speed [km/h]", width=14, anchor="e").grid(
            row=1, column=0, padx=5, pady=2, sticky="e")
        self._ble_speed = ttk.Entry(left, state='readonly', width=12,
                                    justify='right', font=self._value_font)
        self._ble_speed.grid(row=1, column=1, pady=2, sticky="w")
        ttk.Label(left, text="Power [W]", width=14, anchor="e").grid(
            row=2, column=0, padx=5, pady=2, sticky="e")
        self._ble_power = ttk.Entry(left, state='readonly', width=12,
                                    justify='right', font=self._value_font)
        self._ble_power.grid(row=2, column=1, pady=2, sticky="w")

        # Colonna centrale – Δ
        center = ttk.Frame(self)
        center.grid(row=0, column=1, sticky="ns", padx=5, pady=8)
        self._delta_header = ttk.Label(
            center, text=self._header_text(), anchor="center")
        self._delta_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._delta_speed_lbl = tk.Label(
            center, text="—", width=18, anchor="center",
            fg="#666666", justify='center', height=2)
        self._delta_speed_lbl.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        self._delta_power_lbl = tk.Label(
            center, text="—", width=18, anchor="center",
            fg="#666666", justify='center', height=2)
        self._delta_power_lbl.grid(row=2, column=0, padx=2, pady=2, sticky="ew")

        # Colonna destra – Lorenz
        right = ttk.Frame(self)
        right.grid(row=0, column=2, sticky="ew", padx=(5, 10), pady=8)
        right.grid_columnconfigure(1, weight=1)
        ttk.Label(right, text="Gestione Lorenz", anchor="center").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        ttk.Label(right, text="Speed [km/h]", width=14, anchor="e").grid(
            row=1, column=0, padx=5, pady=2, sticky="e")
        self._lrz_speed = ttk.Entry(right, state='readonly', width=12,
                                    justify='right', font=self._value_font)
        self._lrz_speed.grid(row=1, column=1, pady=2, sticky="w")
        ttk.Label(right, text="Power [W]", width=14, anchor="e").grid(
            row=2, column=0, padx=5, pady=2, sticky="e")
        self._lrz_power = ttk.Entry(right, state='readonly', width=12,
                                    justify='right', font=self._value_font)
        self._lrz_power.grid(row=2, column=1, pady=2, sticky="w")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _header_text(self):
        return f"Δ – media N={self._smoothing_window}"

    @staticmethod
    def _set_ro(entry, text):
        entry.config(state='normal')
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(state='readonly')

    def _refresh(self):
        d_speed_inst = compute_speed_delta(self._last_ble_speed, self._last_lrz_speed)
        d_power_inst = compute_power_delta_pct(self._last_ble_power, self._last_lrz_power)

        if d_speed_inst is not None:
            self._speed_hist.append(d_speed_inst)
        if d_power_inst is not None:
            self._power_hist.append(d_power_inst)

        d_speed_avg = mean_or_none(self._speed_hist)
        d_power_avg = mean_or_none(self._power_hist)

        # Speed Δ label
        if d_speed_avg is not None or d_speed_inst is not None:
            smooth = fmt_speed_delta(d_speed_avg if d_speed_avg is not None else d_speed_inst)
            inst   = fmt_speed_delta(d_speed_inst)
            txt    = smooth if inst == "—" else f"{smooth}\n({inst})"
            col    = color_for_speed_delta(
                abs(d_speed_avg) if d_speed_avg is not None else None, self._speed_thr)
            self._delta_speed_lbl.config(text=txt, fg=col)
        else:
            self._delta_speed_lbl.config(text="—", fg="#666666")

        # Power Δ label
        if d_power_avg is not None or d_power_inst is not None:
            smooth = fmt_power_delta(d_power_avg if d_power_avg is not None else d_power_inst)
            inst   = fmt_power_delta(d_power_inst)
            txt    = smooth if inst == "—" else f"{smooth}\n({inst})"
            col    = color_for_power_delta(d_power_avg, self._power_thr)
            self._delta_power_lbl.config(text=txt, fg=col)
        else:
            self._delta_power_lbl.config(text="—", fg="#666666")

        self._delta_header.config(text=self._header_text())

    # ── API pubblica ──────────────────────────────────────────────────────────

    def update_ble(self, speed, power):
        """Aggiorna i valori BLE e ricalcola il Δ."""
        if speed is not None:
            self._set_ro(self._ble_speed, str(speed))
            self._last_ble_speed = float(speed)
        if power is not None:
            self._set_ro(self._ble_power, str(power))
            self._last_ble_power = float(power)
        self._refresh()

    def update_lorenz(self, speed, power):
        """Aggiorna i valori Lorenz e ricalcola il Δ."""
        if speed is not None:
            self._set_ro(self._lrz_speed, f"{speed:.2f}")
            self._last_lrz_speed = float(speed)
        if power is not None:
            self._set_ro(self._lrz_power, f"{power:.2f}")
            self._last_lrz_power = float(power)
        self._refresh()

    def clear_ble(self):
        """Resetta i valori BLE e svuota i buffer di smoothing."""
        self._last_ble_speed = None
        self._last_ble_power = None
        self._speed_hist.clear()
        self._power_hist.clear()
        self._refresh()

    def set_smoothing_window(self, n: int):
        n = max(1, int(n))
        self._smoothing_window = n
        self._speed_hist = deque(list(self._speed_hist)[-n:], maxlen=n)
        self._power_hist = deque(list(self._power_hist)[-n:], maxlen=n)
        self._delta_header.config(text=self._header_text())

    def set_thresholds(self, speed, power):
        self._speed_thr = speed
        self._power_thr = power
        self._refresh()
