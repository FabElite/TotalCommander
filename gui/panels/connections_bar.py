"""
Barra connessioni (row 1): BLE / Lorenz / Banco / Sensore COM.
La sezione COM è collassabile: di default mostra solo un pulsante "+COM".
Il toggle chiama on_com_toggle(visible: bool) → main_window coordina anche LiveDataPanel.
"""
import tkinter as tk
from tkinter import ttk
import serial.tools.list_ports


class ConnectionsBar(ttk.Frame):
    """Row 1 della finestra principale."""

    def __init__(self, parent, lorenz_reader,
                 on_rec_start,
                 on_rec_stop,
                 on_open_output,
                 on_ble_search,
                 on_ble_connect,
                 on_ble_disconnect,
                 on_lorenz_connect,
                 on_lorenz_disconnect,
                 on_lorenz_read_offset,
                 on_lorenz_avg_change,
                 on_lorenz_invert,
                 on_banco_connect,
                 on_banco_disconnect,
                 on_serial_connect,
                 on_serial_disconnect,
                 on_com_toggle,        # (visible: bool) → coordinato da main_window
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._lorenz_reader        = lorenz_reader
        self._cb_rec_start         = on_rec_start
        self._cb_rec_stop          = on_rec_stop
        self._cb_open_output       = on_open_output
        self._cb_ble_search        = on_ble_search
        self._cb_ble_connect       = on_ble_connect
        self._cb_ble_disconnect    = on_ble_disconnect
        self._cb_lorenz_connect    = on_lorenz_connect
        self._cb_lorenz_disconnect = on_lorenz_disconnect
        self._cb_lorenz_offset     = on_lorenz_read_offset
        self._cb_lorenz_avg        = on_lorenz_avg_change
        self._cb_lorenz_invert     = on_lorenz_invert
        self._cb_banco_connect     = on_banco_connect
        self._cb_banco_disconnect  = on_banco_disconnect
        self._cb_serial_connect    = on_serial_connect
        self._cb_serial_disconnect = on_serial_disconnect
        self._cb_com_toggle        = on_com_toggle

        self._com_visible = False

        self.grid_columnconfigure(0, weight=1)   # REC
        self.grid_columnconfigure(1, weight=3)   # BLE
        self.grid_columnconfigure(2, weight=2)   # Lorenz
        self.grid_columnconfigure(4, weight=2)   # Banco
        self.grid_columnconfigure(4, weight=0)   # COM: parte collassata, niente peso

        self._build_rec()
        self._build_ble()
        self._build_lorenz()
        self._build_banco()
        self._build_com_toggle_btn()
        self._build_com_panel()          # creato ma non griddato

    # ── Sezioni sempre visibili ───────────────────────────────────────────────

    def _build_rec(self):
        f = ttk.LabelFrame(self, text="Registrazione")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        f.grid_columnconfigure(0, weight=1)

        self._btn_rec = tk.Button(
            f, text="⏺  REC",
            command=self._cb_rec_start,
            font=('Helvetica', 10, 'bold'),
            bg='#cc2222', fg='white',
            activebackground='#aa0000', activeforeground='white',
            relief='raised', bd=2, cursor='hand2',
        )
        self._btn_rec.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 2))

        self._btn_rec_stop = tk.Button(
            f, text="⏹  STOP",
            command=self._cb_rec_stop,
            font=('Helvetica', 10, 'bold'),
            bg='#444444', fg='white',
            activebackground='#222222', activeforeground='white',
            relief='raised', bd=2, cursor='hand2',
            state='disabled',
        )
        self._btn_rec_stop.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 4))

        self._rec_name_var = tk.StringVar(value="—")
        tk.Label(f, textvariable=self._rec_name_var,
                 font=('Helvetica', 7), fg='#555555',
                 wraplength=100, justify='center', anchor='center'
                 ).grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 2))

        ttk.Button(f, text="📁  Cartella output",
                   command=self._cb_open_output
                   ).grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 6))

    def _build_ble(self):
        f = ttk.LabelFrame(self, text="BLE")
        f.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=2)
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
                   command=self._cb_ble_connect
                   ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rb, text="Disconnetti",
                   command=self._cb_ble_disconnect
                   ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        self.progress = ttk.Progressbar(f, mode='indeterminate')
        self.progress.grid(row=3, column=0, sticky="ew", padx=6, pady=(2, 6))

    def _build_lorenz(self):
        f = ttk.LabelFrame(self, text="Lorenz")
        f.grid(row=0, column=2, sticky="nsew", padx=4, pady=2)
        f.grid_columnconfigure(0, weight=1); f.grid_columnconfigure(1, weight=1)

        rl = ttk.Frame(f)
        rl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))
        rl.grid_columnconfigure(0, weight=1); rl.grid_columnconfigure(1, weight=1)
        ttk.Button(rl, text="Connetti",
                   command=self._cb_lorenz_connect
                   ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rl, text="Disconnetti",
                   command=self._cb_lorenz_disconnect
                   ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        ttk.Button(f, text="Leggi Offset",
                   command=self._cb_lorenz_offset
                   ).grid(row=1, column=0, sticky="ew", padx=6, pady=2)
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
                        ).grid(row=3, column=0, columnspan=2, sticky="w",
                               padx=6, pady=(2, 6))

    def _build_banco(self):
        f = ttk.LabelFrame(self, text="Banco")
        f.grid(row=0, column=3, sticky="nsew", padx=4, pady=2)
        f.grid_columnconfigure(1, weight=1)

        ttk.Label(f, text="IP:").grid(row=0, column=0, sticky="e",
                                      padx=(6, 4), pady=(6, 2))
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
                   command=self._cb_banco_disconnect
                   ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    # ── Sezione COM collassabile ──────────────────────────────────────────────

    def _build_com_toggle_btn(self):
        """Pulsante piccolo sempre visibile in col 3 quando COM è chiuso."""
        self._btn_com = tk.Button(
            self, text="COM ＋",
            command=self._toggle_com,
            font=('Helvetica', 8, 'bold'),
            bg='#e8e8e8', fg='#555555',
            relief='flat', bd=1,
            cursor='hand2', padx=6, pady=4,
        )
        self._btn_com.grid(row=0, column=4, sticky='ns', padx=(4, 0), pady=2)

    def _build_com_panel(self):
        """LabelFrame COM — costruito subito ma non griddato."""
        f = ttk.LabelFrame(self, text="Sensore COM")
        f.grid_columnconfigure(1, weight=1)
        self._com_frame = f

        ttk.Label(f, text="Porta:").grid(row=0, column=0, sticky="e",
                                         padx=(6, 4), pady=(6, 2))
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
                   command=self._cb_serial_disconnect
                   ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

    def _toggle_com(self):
        self.set_com_visible(not self._com_visible)
        self._cb_com_toggle(self._com_visible)

    # ── Helpers interni ───────────────────────────────────────────────────────

    def _get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def _refresh_ports(self):
        current = self._com_combo.get()
        ports = self._get_ports()
        self._com_combo['values'] = ports
        self._com_combo.set(
            current if current in ports else (ports[0] if ports else ''))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def set_com_visible(self, visible: bool):
        self._com_visible = visible
        if visible:
            self.grid_columnconfigure(4, weight=2)
            self._btn_com.grid_remove()
            self._com_frame.grid(row=0, column=4, sticky="nsew",
                                 padx=(4, 0), pady=2)
            self._btn_com_close = tk.Button(
                self._com_frame, text="✕",
                command=self._toggle_com,
                font=('Helvetica', 8), fg='#888888',
                relief='flat', bd=0, cursor='hand2',
            )
            self._btn_com_close.place(relx=1.0, rely=0.0, anchor='ne', x=-4, y=2)
        else:
            self._com_frame.grid_remove()
            if hasattr(self, '_btn_com_close'):
                self._btn_com_close.destroy()
            self.grid_columnconfigure(4, weight=0)
            self._btn_com.grid(row=0, column=4, sticky='ns',
                               padx=(4, 0), pady=2)

    def get_selected_ble_device(self):
        sel = self.device_list.get(tk.ACTIVE) if self.device_list.size() > 0 else ""
        if not sel:
            return None, None
        try:
            parts = sel.split(" - ")
            return parts[0], parts[1]
        except Exception:
            return None, None

    def populate_ble_list(self, devices: dict):
        self.device_list.delete(0, tk.END)
        for address, (name, rssi) in devices.items():
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
            if rssi > -50:
                try:
                    self.device_list.itemconfig(tk.END, {'bg': 'lightcoral'})
                except Exception:
                    pass

    def set_rec_state(self, recording: bool, session_name: str = "—"):
        """Aggiorna pulsanti e label di sessione nella REC box."""
        self._rec_name_var.set(session_name)
        if recording:
            self._btn_rec.config(state='disabled')
            self._btn_rec_stop.config(state='normal')
        else:
            self._btn_rec.config(state='normal')
            self._btn_rec_stop.config(state='disabled')

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