import tkinter as tk
from tkinter import ttk

class ConnectionsBar(ttk.Frame):
    """Row 1 della finestra principale."""

    # Costanti per uniformare il layout
    PAD_OUT = 5
    PAD_IN = 4
    BANCO_IP = "192.168.0.10"

    # --------------------------------------------------------------------- #
    # Costruzione
    # --------------------------------------------------------------------- #
    def __init__(self, parent, lorenz_reader,
                 on_rec_start, on_rec_stop, on_open_output,
                 on_ble_search, on_ble_connect, on_ble_disconnect,
                 on_lorenz_connect, on_lorenz_disconnect,
                 on_lorenz_read_offset, on_lorenz_avg_change, on_lorenz_invert,
                 on_banco_connect, on_banco_disconnect, **kwargs):
        super().__init__(parent, **kwargs)

        # Callback e stato
        self._lorenz_reader = lorenz_reader
        self._cb_rec_start = on_rec_start
        self._cb_rec_stop = on_rec_stop
        self._cb_open_output = on_open_output
        self._cb_ble_search = on_ble_search
        self._cb_ble_connect = on_ble_connect
        self._cb_ble_disconnect = on_ble_disconnect
        self._cb_lorenz_connect = on_lorenz_connect
        self._cb_lorenz_disconnect = on_lorenz_disconnect
        self._cb_lorenz_offset = on_lorenz_read_offset
        self._cb_lorenz_avg = on_lorenz_avg_change
        self._cb_lorenz_invert = on_lorenz_invert
        self._cb_banco_connect = on_banco_connect
        self._cb_banco_disconnect = on_banco_disconnect

        # Layout griglia principale
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=2)
        self.grid_columnconfigure(3, weight=2)

        # Stile di base del Treeview
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=15)
        style.map("Treeview",
                  background=[("selected", "#CCE4FF")],
                  foreground=[("selected", "#111111")])

        # Build sezioni
        self._build_rec()
        self._build_ble()
        self._build_lorenz()
        self._build_banco()

    # --------------------------------------------------------------------- #
    # Registrazione
    # --------------------------------------------------------------------- #
    def _build_rec(self):
        f = ttk.LabelFrame(self, text="Registrazione")
        f.grid(row=0, column=0, sticky="nsew", padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)

        self._btn_rec = tk.Button(
            f, text="⏺ REC", command=self._cb_rec_start,
            font=('Helvetica', 10, 'bold'), bg='#cc2222', fg='white',
            activebackground='#aa0000', activeforeground='white',
            relief='raised', bd=2, cursor='hand2'
        )
        self._btn_rec.grid(row=0, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        self._btn_rec_stop = tk.Button(
            f, text="⏹ STOP", command=self._cb_rec_stop,
            font=('Helvetica', 10, 'bold'), bg='#444444', fg='white',
            activebackground='#222222', activeforeground='white',
            relief='raised', bd=2, cursor='hand2', state='disabled'
        )
        self._btn_rec_stop.grid(row=1, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        self._rec_name_var = tk.StringVar(value="—")
        tk.Label(
            f, textvariable=self._rec_name_var,
            font=('Helvetica', 7), fg='#555555',
            wraplength=100, justify='center', anchor='center'
        ).grid(row=2, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        ttk.Button(f, text="📁 Output", command=self._cb_open_output)\
            .grid(row=3, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

    # --------------------------------------------------------------------- #
    # BLE
    # --------------------------------------------------------------------- #
    def _build_ble(self):
        f = ttk.LabelFrame(self, text="BLE")
        f.grid(row=0, column=1, sticky="nsew", padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        # Treeview Layout
        list_frame = ttk.Frame(f)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=self.PAD_IN, pady=self.PAD_IN)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        columns = ("name", "mac", "rssi")
        self.device_list = ttk.Treeview(
            list_frame, columns=columns, show="headings", height=6, selectmode="browse"
        )
        self.device_list.heading("name", text="Nome", command=lambda: self._sort_by("name", False))
        self.device_list.heading("mac", text="Indirizzo MAC", command=lambda: self._sort_by("mac", False))
        self.device_list.heading("rssi", text="Segnale", command=lambda: self._sort_by("rssi", True))

        self.device_list.column("name", width=90, minwidth=70, anchor="w")
        self.device_list.column("mac", width=120, minwidth=100, anchor="center")
        self.device_list.column("rssi", width=85, minwidth=70, anchor="e")
        self.device_list.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.device_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.device_list.config(yscrollcommand=scrollbar.set)

        self.device_list.tag_configure("oddrow", background="#F7F7F7")
        self.device_list.bind("<Double-1>", lambda e: self._cb_ble_connect())
        self.device_list.bind("<<TreeviewSelect>>", self._on_ble_select)

        # Status Label
        self._ble_status_lbl = tk.Label(f, text="", font=('Helvetica', 7), fg='#777777', anchor='w')
        self._ble_status_lbl.grid(row=1, column=0, sticky='ew', padx=self.PAD_IN)

        # Colonna Pulsanti
        btn_col = ttk.Frame(f)
        btn_col.grid(row=0, column=1, rowspan=2, sticky="n", padx=self.PAD_IN, pady=self.PAD_IN)

        self.search_btn = ttk.Button(btn_col, text="🔍 Cerca", command=self._cb_ble_search, width=11)
        self.search_btn.grid(row=0, column=0, pady=(0, self.PAD_IN))

        self.progress = ttk.Progressbar(btn_col, mode='indeterminate', length=80)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, self.PAD_OUT))

        ttk.Separator(btn_col, orient='horizontal').grid(row=2, column=0, sticky='ew', pady=(0, self.PAD_OUT))

        self.connect_btn = ttk.Button(btn_col, text="Connetti", command=self._cb_ble_connect, state="disabled", width=11)
        self.connect_btn.grid(row=3, column=0, pady=(0, self.PAD_IN))

        self.disconnect_btn = ttk.Button(btn_col, text="Disconnetti", command=self._cb_ble_disconnect, width=11)
        self.disconnect_btn.grid(row=4, column=0)

    # --------------------------------------------------------------------- #
    # Utilità BLE
    # --------------------------------------------------------------------- #
    @staticmethod
    def _rssi_to_level(rssi: int) -> int:
        if rssi >= -50: return 4
        if rssi >= -65: return 3
        if rssi >= -80: return 2
        return 1

    @staticmethod
    def _level_to_bars(level: int) -> str:
        level = max(0, min(4, level))
        return "■" * level + "□" * (4 - level)

    def _sort_by(self, col, descending):
        data = []
        for iid in self.device_list.get_children():
            vals = self.device_list.item(iid)['values']
            if col == "rssi":
                try:
                    num = int(str(vals[2]).split()[-2])
                except (IndexError, ValueError):
                    num = -999
                data.append((num, iid))
            elif col == "name":
                data.append((str(vals[0]).lower(), iid))
            else:
                data.append((str(vals[1]).lower(), iid))

        data.sort(reverse=descending)
        for idx, (_, iid) in enumerate(data):
            self.device_list.move(iid, "", idx)

        self.device_list.heading(col, command=lambda: self._sort_by(col, not descending))

    def _on_ble_select(self, *_):
        has_selection = bool(self.device_list.selection())
        self.connect_btn.config(state=("normal" if has_selection else "disabled"))

    def populate_ble_list(self, devices: dict):
        # Svuotamento massivo ottimizzato
        self.device_list.delete(*self.device_list.get_children())

        for idx, (address, (name, rssi)) in enumerate(devices.items()):
            try:
                rssi = int(rssi)
            except (ValueError, TypeError):
                rssi = -99

            level = self._rssi_to_level(rssi)
            bars = self._level_to_bars(level)
            short_mac = address[-17:]
            tag = "oddrow" if (idx % 2) else ""

            self.device_list.insert(
                "", tk.END, iid=address,
                values=(name, short_mac, f"{bars}  {rssi:>4} dBm"),
                tags=(tag,)
            )

        children = self.device_list.get_children()
        if children:
            self.device_list.selection_set(children[0])
            self.device_list.focus(children[0])
        self._on_ble_select()

    def get_selected_ble_device(self):
        sel = self.device_list.selection()
        if not sel:
            return None, None
        return self.device_list.item(sel[0])['values'][0], sel[0]

    # --------------------------------------------------------------------- #
    # Lorenz
    # --------------------------------------------------------------------- #
    def _build_lorenz(self):
        f = ttk.LabelFrame(self, text="Lorenz")
        f.grid(row=0, column=2, sticky="nsew", padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)

        ttk.Button(f, text="Connetti", command=self._cb_lorenz_connect)\
            .grid(row=0, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)
        ttk.Button(f, text="Disconnetti", command=self._cb_lorenz_disconnect)\
            .grid(row=0, column=1, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        ttk.Button(f, text="Leggi Offset", command=self._cb_lorenz_offset)\
            .grid(row=1, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        self._offset_entry = ttk.Entry(f, state='readonly', justify='right', width=9)
        self._offset_entry.grid(row=1, column=1, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        ttk.Label(f, text="Media:").grid(row=2, column=0, sticky="e", padx=self.PAD_IN, pady=self.PAD_IN)
        self.avg_entry = ttk.Entry(f, width=8, justify='right')
        self.avg_entry.grid(row=2, column=1, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)
        self.avg_entry.insert(0, str(self._lorenz_reader.avg_dim))

        # Consolidato il binding per la media
        self.avg_entry.bind("<Return>", self._on_avg_change)
        self.avg_entry.bind("<FocusOut>", self._on_avg_change)

        self._invert_var = tk.BooleanVar(value=self._lorenz_reader.invert_speed)
        ttk.Checkbutton(
            f, text="Inverti Velocità", variable=self._invert_var,
            command=lambda: self._cb_lorenz_invert(self._invert_var.get())
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=self.PAD_IN, pady=self.PAD_IN)

    def _on_avg_change(self, event=None):
        self._cb_lorenz_avg(self.avg_entry.get())

    # --------------------------------------------------------------------- #
    # Banco
    # --------------------------------------------------------------------- #
    def _build_banco(self):
        f = ttk.LabelFrame(self, text="Banco")
        f.grid(row=0, column=3, sticky="nsew", padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)

        # Label informativa opzionale per far capire all'utente a quale IP ci si connette
        ttk.Label(f, text=f"IP: {self.BANCO_IP}", foreground="gray")\
            .grid(row=0, column=0, pady=(10, 5))

        ttk.Button(f, text="Connetti", command=lambda: self._cb_banco_connect(self.BANCO_IP))\
            .grid(row=1, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

        ttk.Button(f, text="Disconnetti", command=self._cb_banco_disconnect)\
            .grid(row=2, column=0, sticky="ew", padx=self.PAD_IN, pady=self.PAD_IN)

    # --------------------------------------------------------------------- #
    # API di stato
    # --------------------------------------------------------------------- #
    def set_rec_state(self, recording: bool, session_name: str = "—"):
        self._rec_name_var.set(session_name)
        if recording:
            self._btn_rec.config(state='disabled')
            self._btn_rec_stop.config(state='normal')
        else:
            self._btn_rec.config(state='normal')
            self._btn_rec_stop.config(state='disabled')

    def set_progress(self, running: bool):
        if running:
            self.progress.start()
            self.search_btn.config(state="disabled")
        else:
            self.progress.stop()
            self.search_btn.config(state="normal")

    def set_offset(self, value: float):
        self._offset_entry.config(state='normal')
        self._offset_entry.delete(0, tk.END)
        self._offset_entry.insert(0, f"{value:.2f}")
        self._offset_entry.config(state='readonly')

    def set_avg(self, value: int):
        self.avg_entry.delete(0, tk.END)
        self.avg_entry.insert(0, str(value))