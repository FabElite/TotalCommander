"""
Barra connessioni (row 1): sezioni BLE / Lorenz / Banco / Sensore COM.
Riceve i callback come argomenti; espone metodi pubblici per aggiornare la UI.
"""
import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports


class ConnectionsBar(ttk.Frame):
    """Row 1 della finestra principale."""

    def __init__(self, parent, lorenz_reader,
                 on_ble_search,
                 on_ble_connect,       # () → avvia connessione al dispositivo selezionato
                 on_ble_disconnect,
                 on_lorenz_connect,
                 on_lorenz_disconnect,
                 on_lorenz_read_offset,
                 on_lorenz_avg_change,  # (value_str) → chiamato su Return/FocusOut
                 on_lorenz_invert,      # (bool) → invertito sì/no
                 on_banco_connect,      # (ip_str) → chiamato con IP dalla entry
                 on_banco_disconnect,
                 on_serial_connect,     # (port_str)
                 on_serial_disconnect,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._lorenz_reader = lorenz_reader
        self._cb_ble_search         = on_ble_search
        self._cb_ble_connect        = on_ble_connect
        self._cb_ble_disconnect     = on_ble_disconnect
        self._cb_lorenz_connect     = on_lorenz_connect
        self._cb_lorenz_disconnect  = on_lorenz_disconnect
        self._cb_lorenz_offset      = on_lorenz_read_offset
        self._cb_lorenz_avg         = on_lorenz_avg_change
        self._cb_lorenz_invert      = on_lorenz_invert
        self._cb_banco_connect      = on_banco_connect
        self._cb_banco_disconnect   = on_banco_disconnect
        self._cb_serial_connect     = on_serial_connect
        self._cb_serial_disconnect  = on_serial_disconnect

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_columnconfigure(2, weight=2)
        self.grid_columnconfigure(3, weight=2)

        self._build_ble()
        self._build_lorenz()
        self._build_banco()
        self._build_com()

    # ── Sezioni ───────────────────────────────────────────────────────────────

    def _build_ble(self):
        f = ttk.LabelFrame(self, text="BLE")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        f.grid_columnconfigure(0, weight=1)

        self.device_list = tk.Listbox(f, height=4, font=('Helvetica', 8))
        self.device_list.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 2))

        ttk.Button(f, text="Cerca Dispositivi",
                   command=self._cb_ble_search
                   ).grid(row=1, column=0, sticky="ew", padx=6, pady=2)

        rb = ttk.Frame(f)
        rb.grid(row=2, column=0, sticky="ew", padx=6, pady=2)
        rb.grid_columnconfigure(0, weight=1); rb.grid_columnconfigure(1, weight=1)
        ttk.Button(rb, text="Connetti",
                   command=self._cb_ble_connect).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rb, text="Disconnetti",
                   command=self._cb_ble_disconnect).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        self.progress = ttk.Progressbar(f, mode='indeterminate')
        self.progress.grid(row=3, column=0, sticky="ew", padx=6, pady=(2, 6))

    def _build_lorenz(self):
        f = ttk.LabelFrame(self, text="Lorenz")
        f.grid(row=0, column=1, sticky="nsew", padx=4, pady=2)
        f.grid_columnconfigure(0, weight=1); f.grid_columnconfigure(1, weight=1)

        rl = ttk.Frame(f)
        rl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))
        rl.grid_columnconfigure(0, weight=1); rl.grid_columnconfigure(1, weight=1)
        ttk.Button(rl, text="Connetti",
                   command=self._cb_lorenz_connect).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rl, text="Disconnetti",
                   command=self._cb_lorenz_disconnect).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        ttk.Button(f, text="Leggi Offset",
                   command=self._cb_lorenz_offset).grid(row=1, column=0, sticky="ew", padx=6, pady=2)
        self._offset_entry = ttk.Entry(f, state='readonly', justify='right', width=9)
        self._offset_entry.grid(row=1, column=1, sticky="ew", padx=(2, 6), pady=2)

        avg_f = ttk.Frame(f)
        avg_f.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=2)
        avg_f.grid_columnconfigure(1, weight=1)
        ttk.Label(avg_f, text="Media:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self.avg_entry = ttk.Entry(avg_f, width=8, justify='right')
        self.avg_entry.grid(row=0, column=1, sticky="ew")
        self.avg_entry.insert(0, str(self._lorenz_reader.avg_dim))
        self.avg_entry.bind("<Return>",   lambda e: self._cb_lorenz_avg(self.avg_entry.get()))
        self.avg_entry.bind("<FocusOut>", lambda e: self._cb_lorenz_avg(self.avg_entry.get()))

        self._invert_var = tk.BooleanVar(value=self._lorenz_reader.invert_speed)
        ttk.Checkbutton(f, text="Inverti Velocità",
                        variable=self._invert_var,
                        command=lambda: self._cb_lorenz_invert(self._invert_var.get())
                        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))

    def _build_banco(self):
        f = ttk.LabelFrame(self, text="Banco")
        f.grid(row=0, column=2, sticky="nsew", padx=4, pady=2)
        f.grid_columnconfigure(1, weight=1)

        ttk.Label(f, text="IP:").grid(row=0, column=0, sticky="e", padx=(6, 4), pady=(6, 2))
        self._entry_ip = ttk.Entry(f, width=14)
        self._entry_ip.insert(0, "192.168.0.10")
        self._entry_ip.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=(6, 2))

        rb = ttk.Frame(f)
        rb.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 8))
        rb.grid_columnconfigure(0, weight=1); rb.grid_columnconfigure(1, weight=1)
        ttk.Button(rb, text="Connetti",
                   command=lambda: self._cb_banco_connect(self._entry_ip.get())
                   ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rb, text="Disconnetti",
                   command=self._cb_banco_disconnect).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    def _build_com(self):
        f = ttk.LabelFrame(self, text="Sensore COM")
        f.grid(row=0, column=3, sticky="nsew", padx=(4, 0), pady=2)
        f.grid_columnconfigure(1, weight=1)

        ttk.Label(f, text="Porta:").grid(row=0, column=0, sticky="e", padx=(6, 4), pady=(6, 2))
        self._com_combo = ttk.Combobox(f, values=self._get_ports(), width=10)
        self._com_combo.grid(row=0, column=1, sticky="ew", padx=(0, 2), pady=(6, 2))
        tk.Button(f, text="🔄", command=self._refresh_ports,
                  font=('Segoe UI Emoji', 11), relief='flat', bd=1,
                  cursor='hand2', padx=2, pady=1
                  ).grid(row=0, column=2, padx=(0, 6), pady=(6, 2))

        rc = ttk.Frame(f)
        rc.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(2, 6))
        rc.grid_columnconfigure(0, weight=1); rc.grid_columnconfigure(1, weight=1)
        ttk.Button(rc, text="Connetti",
                   command=lambda: self._cb_serial_connect(self._com_combo.get())
                   ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rc, text="Disconnetti",
                   command=self._cb_serial_disconnect).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    # ── Helpers interni ───────────────────────────────────────────────────────

    def _get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def _refresh_ports(self):
        current = self._com_combo.get()
        ports = self._get_ports()
        self._com_combo['values'] = ports
        if current in ports:
            self._com_combo.set(current)
        elif ports:
            self._com_combo.set(ports[0])
        else:
            self._com_combo.set('')

    # ── API pubblica ──────────────────────────────────────────────────────────

    def get_selected_ble_device(self):
        """Restituisce (name, address) del dispositivo selezionato, o (None, None)."""
        sel = self.device_list.get(tk.ACTIVE) if self.device_list.size() > 0 else ""
        if not sel:
            return None, None
        try:
            parts = sel.split(" - ")
            return parts[0], parts[1]
        except Exception:
            return None, None

    def populate_ble_list(self, devices: dict):
        """devices: {address: (name, rssi)}"""
        self.device_list.delete(0, tk.END)
        for address, (name, rssi) in devices.items():
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
            if rssi > -50:
                try:
                    self.device_list.itemconfig(tk.END, {'bg': 'lightcoral'})
                except Exception:
                    pass

    def set_progress(self, running: bool):
        self.progress.start() if running else self.progress.stop()

    def set_offset(self, value: float):
        self._offset_entry.config(state='normal')
        self._offset_entry.delete(0, tk.END)
        self._offset_entry.insert(0, f"{value:.2f}")
        self._offset_entry.config(state='readonly')

    def set_avg(self, value: int):
        self.avg_entry.delete(0, tk.END)
        self.avg_entry.insert(0, str(value))
