"""
Barra connessioni (row 1): Sessione / BLE / Lorenz / Banco.

Layout:
  ┌─ Sessione ┐  ┌─ BLE ─────────────────────────────────┐  ┌─ Lorenz ──────┐  ┌─ Banco ──┐
  │ ⏺ REC    │  │ ┌────────────────────────┐  🔍 Cerca   │  │ [Conn] [Disc] │  │ Connetti │
  │ ⏹ STOP   │  │ │ Nome │ MAC  │ Segnale  │  ░░░░░░░░░  │  │ Offset: [val] │  │ Scollega │
  │ nome file │  │ │ ...  │ ...  │ ■■■□    │  ─────────  │  │ Media:  [   ] │  └──────────┘
  │ 📁 Esplora│  │ └────────────────────────┘  Connetti  │  │ □ Inverti     │
  └───────────┘  │ stato…                      Disconnetti│  └───────────────┘
                 └────────────────────────────────────────┘
"""

import tkinter as tk
from tkinter import ttk

_BANCO_DEFAULT_IP = "192.168.0.10"


class ConnectionsBar(ttk.Frame):
    """Row 1 della finestra principale."""

    PAD_OUT = 5
    PAD_IN  = 4

    def __init__(self, parent, lorenz_reader,
                 on_rec_start, on_rec_stop, on_open_output,
                 on_ble_search, on_ble_connect, on_ble_disconnect,
                 on_lorenz_connect, on_lorenz_disconnect,
                 on_lorenz_read_offset, on_lorenz_avg_change, on_lorenz_invert,
                 on_banco_connect, on_banco_disconnect,
                 banco_ip: str = _BANCO_DEFAULT_IP, **kwargs):
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
        self._banco_ip_init        = banco_ip

        # Stato animazione progress
        self._progress_anim_id = None
        self._progress_pos     = 0

        # Stile Treeview
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=18)
        style.map("Treeview",
                  background=[("selected", "#CCE4FF")],
                  foreground=[("selected", "#111111")])

        # Griglia principale
        self.grid_columnconfigure(0, weight=0, minsize=150)  # Sessione – fisso
        self.grid_columnconfigure(1, weight=1)  # BLE      – espandibile
        self.grid_columnconfigure(2, weight=0)  # Lorenz   – fisso
        self.grid_columnconfigure(3, weight=0)  # Banco    – fisso

        self._build_sessione()
        self._build_ble()
        self._build_lorenz()
        self._build_banco()

    # ------------------------------------------------------------------ #
    # Sessione (ex-REC)
    # ------------------------------------------------------------------ #
    def _build_sessione(self):
        f = ttk.LabelFrame(self, text="Sessione")
        f.grid(row=0, column=0, sticky="nsew",
               padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)

        self._btn_rec = tk.Button(
            f, text="⏺ REC", command=self._cb_rec_start,
            font=('Helvetica', 9, 'bold'), bg='#cc2222', fg='white',
            activebackground='#aa0000', activeforeground='white',
            width=8, cursor='hand2',
        )
        self._btn_rec.grid(row=0, column=0, sticky="ew",
                           padx=self.PAD_IN, pady=(self.PAD_IN, 2))

        self._btn_rec_stop = tk.Button(
            f, text="⏹ STOP", command=self._cb_rec_stop,
            font=('Helvetica', 9, 'bold'), bg='#444444', fg='white',
            activebackground='#222222', activeforeground='white',
            width=8, state='disabled', cursor='hand2',
        )
        self._btn_rec_stop.grid(row=1, column=0, sticky="ew",
                                padx=self.PAD_IN, pady=2)

        # Nome sessione corrente
        self._rec_name_var = tk.StringVar(value="—")
        tk.Label(f, textvariable=self._rec_name_var,
                 font=('Helvetica', 7), fg='#666666',
                 wraplength=90, justify='center', anchor='center',
                 ).grid(row=2, column=0, sticky="ew",
                        padx=self.PAD_IN, pady=(0, 2))

        ttk.Button(f, text="📁 Esplora", command=self._cb_open_output, width=10
                   ).grid(row=3, column=0, sticky="ew",
                          padx=self.PAD_IN, pady=(2, self.PAD_IN))

    # ------------------------------------------------------------------ #
    # BLE
    # ------------------------------------------------------------------ #
    def _build_ble(self):
        f = ttk.LabelFrame(self, text="BLE")
        f.grid(row=0, column=1, sticky="nsew",
               padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)   # tabella cresce
        f.grid_columnconfigure(1, weight=0)   # pulsanti: larghezza naturale
        f.grid_rowconfigure(0, weight=1)

        # ── Treeview ──────────────────────────────────────────────────
        list_frame = ttk.Frame(f)
        list_frame.grid(row=0, column=0, rowspan=2, sticky="nsew",
                        padx=(self.PAD_IN, 2), pady=self.PAD_IN)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self.device_list = ttk.Treeview(
            list_frame,
            columns=("name", "mac", "rssi"),
            show="headings", height=5, selectmode="browse",
        )
        self.device_list.heading("name", text="Nome",
                                 command=lambda: self._sort_by("name", False))
        self.device_list.heading("mac",  text="Indirizzo MAC",
                                 command=lambda: self._sort_by("mac",  False))
        self.device_list.heading("rssi", text="Segnale",
                                 command=lambda: self._sort_by("rssi", True))

        self.device_list.column("name", width=90,  minwidth=70,  anchor="w")
        self.device_list.column("mac",  width=120, minwidth=100, anchor="center")
        self.device_list.column("rssi", width=85,  minwidth=70,  anchor="e")

        self.device_list.grid(row=0, column=0, sticky="nsew")
        self.device_list.tag_configure("oddrow", background="#F7F7F7")
        self.device_list.bind("<Double-1>",         lambda e: self._cb_ble_connect())
        self.device_list.bind("<<TreeviewSelect>>", self._on_ble_select)

        sb = ttk.Scrollbar(list_frame, orient="vertical",
                           command=self.device_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.device_list.config(yscrollcommand=sb.set)

        # ── Label stato sotto la tabella ──────────────────────────────
        self._ble_status_lbl = tk.Label(
            f, text="", font=('Helvetica', 7),
            fg='#777777', anchor='w',
        )
        self._ble_status_lbl.grid(row=1, column=0, sticky='sw',
                                  padx=(self.PAD_IN + 2, 2),
                                  pady=(0, self.PAD_IN))

        # ── Colonna pulsanti a destra ──────────────────────────────────
        btn_col = ttk.Frame(f)
        btn_col.grid(row=0, column=1, rowspan=2, sticky="n",
                     padx=(2, self.PAD_IN), pady=self.PAD_IN)

        # Cerca + canvas progress direttamente sotto (collegati visivamente)
        self.search_btn = ttk.Button(btn_col, text="🔍 Cerca",
                                     command=self._cb_ble_search, width=11)
        self.search_btn.grid(row=0, column=0, pady=(0, 1))

        self._progress_canvas = tk.Canvas(
            btn_col, height=3, bg='#e0e0e0', highlightthickness=0, width=80,
        )
        self._progress_canvas.grid(row=1, column=0, sticky='ew', pady=(0, 8))

        ttk.Separator(btn_col, orient='horizontal').grid(
            row=2, column=0, sticky='ew', pady=(0, 8))

        self.connect_btn = ttk.Button(btn_col, text="Connetti",
                                      command=self._cb_ble_connect,
                                      state="disabled", width=11)
        self.connect_btn.grid(row=3, column=0, pady=(0, 4))

        self.disconnect_btn = ttk.Button(btn_col, text="Disconnetti",
                                         command=self._cb_ble_disconnect, width=11)
        self.disconnect_btn.grid(row=4, column=0)

    # ── Animazione canvas ──────────────────────────────────────────────
    def _start_canvas_anim(self):
        self._stop_canvas_anim()
        self._progress_pos = 0
        self._tick_canvas_anim()

    def _stop_canvas_anim(self):
        if self._progress_anim_id:
            self._progress_canvas.after_cancel(self._progress_anim_id)
            self._progress_anim_id = None
        self._progress_canvas.delete("all")

    def _tick_canvas_anim(self):
        c = self._progress_canvas
        w = c.winfo_width() or 80
        bar_w = max(w // 3, 20)
        x = self._progress_pos % (w + bar_w) - bar_w
        c.delete("all")
        c.create_rectangle(x, 0, x + bar_w, 3, fill='#1565C0', outline='')
        self._progress_pos += 8
        self._progress_anim_id = c.after(30, self._tick_canvas_anim)

    # ── RSSI helpers ───────────────────────────────────────────────────
    @staticmethod
    def _rssi_to_level(rssi: int) -> int:
        if rssi >= -50:   return 4
        elif rssi >= -65: return 3
        elif rssi >= -80: return 2
        else:             return 1

    @staticmethod
    def _level_to_bars(level: int) -> str:
        level = max(0, min(4, level))
        return "■" * level + "□" * (4 - level)

    # ── Ordinamento colonne ────────────────────────────────────────────
    def _sort_by(self, col: str, descending: bool):
        data = []
        for iid in self.device_list.get_children(""):
            vals = self.device_list.item(iid)['values']
            if col == "rssi":
                try:    num = int(str(vals[2]).split()[-2])
                except: num = -999
                data.append((num, iid))
            elif col == "name":
                data.append((str(vals[0]).lower(), iid))
            else:
                data.append((str(vals[1]).lower(), iid))
        data.sort(reverse=descending)
        for i, (_, iid) in enumerate(data):
            self.device_list.move(iid, "", i)
        self.device_list.heading(col,
            command=lambda: self._sort_by(col, not descending))

    # ── Selezione ──────────────────────────────────────────────────────
    def _on_ble_select(self, *_):
        has = bool(self.device_list.selection())
        self.connect_btn.config(state="normal" if has else "disabled")

    # ------------------------------------------------------------------ #
    # Lorenz
    # ------------------------------------------------------------------ #
    def _build_lorenz(self):
        f = ttk.LabelFrame(self, text="Lorenz")
        f.grid(row=0, column=2, sticky="nsew",
               padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)

        # Connetti / Disconnetti sulla stessa riga
        rl = ttk.Frame(f)
        rl.grid(row=0, column=0, columnspan=2, sticky="ew",
                padx=self.PAD_IN, pady=(self.PAD_IN, 2))
        rl.grid_columnconfigure(0, weight=1)
        rl.grid_columnconfigure(1, weight=1)
        ttk.Button(rl, text="Connetti",
                   command=self._cb_lorenz_connect
                   ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(rl, text="Disconnetti",
                   command=self._cb_lorenz_disconnect
                   ).grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # Offset: label + entry readonly + pulsante "Leggi" compatti
        off_f = ttk.Frame(f)
        off_f.grid(row=1, column=0, columnspan=2, sticky="ew",
                   padx=self.PAD_IN, pady=2)
        off_f.grid_columnconfigure(1, weight=1)
        ttk.Label(off_f, text="Offset:").grid(row=0, column=0,
                                               sticky="e", padx=(0, 4))
        self._offset_entry = ttk.Entry(off_f, state='readonly',
                                       justify='right', width=8)
        self._offset_entry.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(off_f, text="Leggi", width=5,
                   command=self._cb_lorenz_offset
                   ).grid(row=0, column=2)

        # Media
        avg_f = ttk.Frame(f)
        avg_f.grid(row=2, column=0, columnspan=2, sticky="ew",
                   padx=self.PAD_IN, pady=2)
        avg_f.grid_columnconfigure(1, weight=1)
        ttk.Label(avg_f, text="Media:").grid(row=0, column=0,
                                              sticky="e", padx=(0, 4))
        self.avg_entry = ttk.Entry(avg_f, width=8, justify='right')
        self.avg_entry.grid(row=0, column=1, sticky="ew")
        self.avg_entry.insert(0, str(self._lorenz_reader.avg_dim))
        self.avg_entry.bind("<Return>",
                            lambda e: self._cb_lorenz_avg(self.avg_entry.get()))
        self.avg_entry.bind("<FocusOut>",
                            lambda e: self._cb_lorenz_avg(self.avg_entry.get()))

        # Inverti velocità
        self._invert_var = tk.BooleanVar(value=self._lorenz_reader.invert_speed)
        ttk.Checkbutton(f, text="Inverti Velocità",
                        variable=self._invert_var,
                        command=lambda: self._cb_lorenz_invert(self._invert_var.get())
                        ).grid(row=3, column=0, columnspan=2, sticky="w",
                               padx=self.PAD_IN, pady=(2, self.PAD_IN))

    # ------------------------------------------------------------------ #
    # Banco  (IP da settings, modificabile in linea)
    # ------------------------------------------------------------------ #
    def _build_banco(self):
        f = ttk.LabelFrame(self, text="Banco")
        f.grid(row=0, column=3, sticky="nsew",
               padx=self.PAD_OUT, pady=self.PAD_OUT)
        f.grid_columnconfigure(0, weight=1)

        # Riga IP
        ip_f = ttk.Frame(f)
        ip_f.grid(row=0, column=0, sticky="ew",
                  padx=self.PAD_IN, pady=(self.PAD_IN, 2))
        ip_f.grid_columnconfigure(1, weight=1)
        ttk.Label(ip_f, text="IP:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self._banco_ip_entry = ttk.Entry(ip_f, width=14, justify='left')
        self._banco_ip_entry.insert(0, self._banco_ip_init)
        self._banco_ip_entry.grid(row=0, column=1, sticky="ew")

        ttk.Button(f, text="Connetti",
                   command=lambda: self._cb_banco_connect(self._banco_ip_entry.get()),
                   width=10
                   ).grid(row=1, column=0, sticky="ew",
                          padx=self.PAD_IN, pady=(2, 2))

        ttk.Button(f, text="Disconnetti",
                   command=self._cb_banco_disconnect, width=10
                   ).grid(row=2, column=0, sticky="ew",
                          padx=self.PAD_IN, pady=(2, self.PAD_IN))

    # ------------------------------------------------------------------ #
    # API pubblica
    # ------------------------------------------------------------------ #

    def set_rec_state(self, recording: bool, session_name: str = "—"):
        """Aggiorna pulsanti e nome sessione."""
        self._rec_name_var.set(session_name)
        if recording:
            self._btn_rec.config(state='disabled')
            self._btn_rec_stop.config(state='normal')
        else:
            self._btn_rec.config(state='normal')
            self._btn_rec_stop.config(state='disabled')

    def set_progress(self, running: bool, text: str = ""):
        """
        Avvia/ferma l'animazione e aggiorna la label di stato.
        Esempi:
            set_progress(True,  "Ricerca in corso…")
            set_progress(True,  "Connessione…")
            set_progress(True,  "Disconnessione…")
            set_progress(False, "")
        """
        self._ble_status_lbl.config(text=text)
        if running:
            self.search_btn.config(state="disabled")
            self._start_canvas_anim()
        else:
            self.search_btn.config(state="normal")
            self._stop_canvas_anim()

    def set_ble_status(self, text: str):
        """Aggiorna solo il testo di stato senza toccare l'animazione."""
        self._ble_status_lbl.config(text=text)

    def populate_ble_list(self, devices: dict):
        """
        Popola il Treeview con i dispositivi trovati.
        devices: { mac_str: (nome_str, rssi_int), ... }
        """
        for item in self.device_list.get_children():
            self.device_list.delete(item)

        for idx, (address, (name, rssi)) in enumerate(devices.items()):
            try:
                rssi = int(rssi)
            except Exception:
                rssi = -99
            level = self._rssi_to_level(rssi)
            bars  = self._level_to_bars(level)
            tag   = "oddrow" if (idx % 2) else ""
            self.device_list.insert(
                "", tk.END, iid=address,
                values=(name, address, f"{bars}  {rssi:>4} dBm"),
                tags=(tag,),
            )

        children = self.device_list.get_children()
        if children:
            self.device_list.selection_set(children[0])
            self.device_list.focus(children[0])
        self._on_ble_select()

    def get_selected_ble_device(self):
        """Ritorna (name, mac_completo) o (None, None) se nulla selezionato."""
        sel = self.device_list.selection()
        if not sel:
            return None, None
        return self.device_list.item(sel[0])['values'][0], sel[0]

    def get_banco_ip(self) -> str:
        """Restituisce l'IP banco attualmente inserito nel campo."""
        return self._banco_ip_entry.get().strip()

    def set_offset(self, value: float):
        self._offset_entry.config(state='normal')
        self._offset_entry.delete(0, tk.END)
        self._offset_entry.insert(0, f"{value:.2f}")
        self._offset_entry.config(state='readonly')

    def set_avg(self, value: int):
        self.avg_entry.delete(0, tk.END)
        self.avg_entry.insert(0, str(value))