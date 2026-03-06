"""
Pannello dati live: tre box affiancati (BLE FTMS / Lorenz / COM).
Espone metodi di aggiornamento; la logica di connessione rimane in main_window.
"""
import tkinter as tk
from tkinter import ttk
import math


class LiveDataPanel(ttk.Frame):
    """Row 1 della colonna destra (sotto ComparePanel)."""

    def __init__(self, parent, on_toggle_ftms, style, **kwargs):
        """
        on_toggle_ftms: callback chiamata quando l'utente preme Abilita/Disabilita Dati.
        style: ttk.Style della finestra principale (per configurare gli stili dei pulsanti).
        """
        super().__init__(parent, **kwargs)
        self._on_toggle_ftms = on_toggle_ftms
        self._style = style

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_ble_box()
        self._build_lorenz_box()
        self._build_com_box()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _make_ro_entry(self, parent, label_text, row):
        tk.Label(parent, text=label_text, font=('Helvetica', 9),
                 anchor='e', width=10).grid(row=row, column=0, sticky='e',
                                            padx=(8, 4), pady=2)
        e = ttk.Entry(parent, state='readonly', justify='right', width=10)
        e.grid(row=row, column=1, sticky='ew', padx=(0, 8), pady=2)
        return e

    def _build_ble_box(self):
        f = ttk.LabelFrame(self, text="Dati BLE FTMS")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        inner = ttk.Frame(f)
        inner.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        inner.grid_columnconfigure(1, weight=1)

        fields = ["power", "speed", "resistance", "cadence", "total_distance", "elapsed_time"]
        self._ble_entries = {}
        for i, field in enumerate(fields):
            tk.Label(inner, text=field.capitalize(), font=('Helvetica', 9),
                     anchor='e', width=14).grid(row=i, column=0, sticky='e',
                                                padx=(6, 4), pady=2)
            entry = ttk.Entry(inner, state='readonly', justify='right', width=10)
            entry.grid(row=i, column=1, sticky='ew', padx=(0, 6), pady=2)
            self._ble_entries[field] = entry

        self._btn_toggle = ttk.Button(
            inner, text="Abilita Dati",
            command=self._on_toggle_ftms, style='Data.Disabled.TButton')
        self._btn_toggle.grid(row=len(fields), column=0, columnspan=2,
                              padx=6, pady=(4, 6), sticky='ew')

    def _build_lorenz_box(self):
        f = ttk.LabelFrame(self, text="Dati Lorenz")
        f.grid(row=0, column=1, sticky="nsew", padx=4)
        f.grid_columnconfigure(1, weight=1)
        self._lrz_power  = self._make_ro_entry(f, "Power",     0)
        self._lrz_speed  = self._make_ro_entry(f, "Speed Avg", 1)
        self._lrz_torque = self._make_ro_entry(f, "Torque",    2)

    def _build_com_box(self):
        f = ttk.LabelFrame(self, text="Dati COM")
        f.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        f.grid_columnconfigure(1, weight=1)
        self._com1 = self._make_ro_entry(f, "Valore 1", 0)
        self._com2 = self._make_ro_entry(f, "Valore 2", 1)
        self._com3 = self._make_ro_entry(f, "Valore 3", 2)
        self._com4 = self._make_ro_entry(f, "Valore 4", 3)

    # ── Helpers interni ───────────────────────────────────────────────────────

    @staticmethod
    def _set_ro(entry, text):
        entry.config(state='normal')
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(state='readonly')

    # ── API pubblica ──────────────────────────────────────────────────────────

    # BLE FTMS
    _BLE_KEY_MAP = {
        'Cad':      'cadence',
        'ElaTime':  'elapsed_time',
        'Pwr':      'power',
        'Res':      'resistance',
        'Spd':      'speed',
        'TotDist':  'total_distance',
    }

    def update_ble(self, bike_data: dict):
        """Aggiorna i campi BLE FTMS. Restituisce (speed, power) aggiornati per ComparePanel."""
        speed, power = None, None
        for data_key, value in bike_data.items():
            if value is None:
                continue
            ui_key = self._BLE_KEY_MAP.get(data_key)
            if ui_key is None:
                continue
            entry = self._ble_entries.get(ui_key)
            if entry:
                self._set_ro(entry, str(value))
            if ui_key == 'speed':
                speed = float(value)
            elif ui_key == 'power':
                power = float(value)
        return speed, power

    def clear_ble(self):
        for entry in self._ble_entries.values():
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.config(state='readonly')

    def is_ftms_enabled(self) -> bool:
        return self._btn_toggle.cget('text') == 'Disabilita Dati'

    def set_ftms_button(self, enabled: bool):
        if enabled:
            self._btn_toggle.config(text='Disabilita Dati', style='Data.Enabled.TButton')
        else:
            self._btn_toggle.config(text='Abilita Dati', style='Data.Disabled.TButton')

    # Lorenz
    def update_lorenz(self, data: dict):
        """Aggiorna i campi Lorenz. Restituisce (speed, power) per ComparePanel."""
        mapping = {
            self._lrz_power:  data.get("power_lorenz"),
            self._lrz_speed:  data.get("speed_avg_lorenz"),
            self._lrz_torque: data.get("torque_lorenz"),
        }
        for entry, val in mapping.items():
            self._set_ro(entry, f"{val:.2f}" if val is not None else "N/A")
        return data.get("speed_avg_lorenz"), data.get("power_lorenz")

    # COM
    def update_serial(self, data: dict):
        def fmt(val):
            if val is not None and not math.isnan(val):
                return f"{val:.2f}"
            return 'N/A'
        self._set_ro(self._com1, fmt(data.get('Valore1')))
        self._set_ro(self._com2, fmt(data.get('Valore2')))
        self._set_ro(self._com3, fmt(data.get('Valore3')))
        self._set_ro(self._com4, fmt(data.get('Valore4')))
