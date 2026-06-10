"""
Pannello comandi: tabella CSV + controlli automatici unificati in una sola box,
affiancati dai comandi manuali BLE e dal controllo banco.

Layout:
  ┌─ Sequenza automatica ─────────────────────┐  ┌─ Comandi manuali BLE ─┐
  │ [Carica] [▶ Start] [■ Stop]  N=[1]  stato │  │ Livello  [spin] Invia │
  │ ─────────────────────────────────────────  │  │ Potenza  [spin] Invia │
  │  Tabella CSV (scrollable, cresce)          │  │ Simul.   [spin] Invia │
  │ ─────────────────────────────────────────  │  ├─ Controllo Banco ─────┤
  │ Tot 00:36  Rim --:--  Ini 16:34  Fine ~   │  │ Vel [spin]  [Set]     │
  └────────────────────────────────────────────┘  │ [■■ STOP BANCO ■■■]  │
                                                   └───────────────────────┘
"""
import tkinter as tk
from tkinter import ttk, filedialog
import datetime
import logging
from logic.data_processing import DataProcessor


def _fmt(seconds):
    """Formatta secondi in HH:MM:SS, o Xg HH:MM:SS se >= 24h."""
    try:
        s = int(float(seconds))
        if s < 0:
            return "--:--:--"
        days = s // 86400
        s %= 86400
        hms = f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return f"{days}g {hms}" if days > 0 else hms
    except Exception:
        return "--:--:--"


class CsvPanel(ttk.Frame):

    def __init__(self, parent,
                 on_dispatch,
                 on_set_banco_speed,
                 on_auto_status,
                 on_auto_completed,
                 on_send_level,
                 on_send_power,
                 on_send_simulation,
                 on_emergency_stop,
                 stop_rec_on_auto_end,
                 on_before_auto_start=None,
                 on_stop_rec_changed=None,
                 on_spindown=None,
                 on_save=None,
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._on_dispatch        = on_dispatch
        self._on_set_banco       = on_set_banco_speed
        self._on_auto_status     = on_auto_status
        self._on_auto_completed  = on_auto_completed
        self._on_send_level      = on_send_level
        self._on_send_power      = on_send_power
        self._on_send_simulation = on_send_simulation
        self._on_emergency_stop  = on_emergency_stop
        self._on_before_auto_start = on_before_auto_start
        self._on_stop_rec_changed  = on_stop_rec_changed
        self._on_spindown          = on_spindown
        self._on_save              = on_save
        self._stop_rec_var         = tk.BooleanVar(value=stop_rec_on_auto_end)

        self._log = logging.getLogger(__name__)
        self.auto_commands_running       = False
        self._csv_single_cycle_seconds   = 0
        self.total_test_duration_seconds = 0
        self.remaining_test_duration_seconds = 0
        self._auto_command_id = None
        self._countdown_id    = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_sequence_panel()
        self._build_col_b()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build_sequence_panel(self):
        """Box unica: tabella → pulsanti/cicli → tempi."""
        f = ttk.LabelFrame(self, text="Sequenza automatica")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)   # tabella in row=0 occupa lo spazio libero

        self._build_table(f)       # row 0
        self._build_toolbar(f)     # rows 1,2  (separatore + pulsanti)
        self._build_timebar(f)     # rows 3,4  (separatore + tempi)

    def _build_toolbar(self, parent):
        """Riga 2 (sotto tabella): separatore + pulsanti + N. Cicli."""
        ttk.Separator(parent, orient='horizontal').grid(
            row=1, column=0, sticky='ew', padx=8, pady=(2, 0))

        tb = ttk.Frame(parent)
        tb.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 4))

        ttk.Button(tb, text="Carica file",
                   command=self.load_csv, width=11
                   ).grid(row=0, column=0, padx=(0, 4))

        ttk.Button(tb, text="▶  Start",
                   command=self.start, width=9
                   ).grid(row=0, column=1, padx=(0, 4))

        ttk.Button(tb, text="■  Stop",
                   command=self.stop, width=9
                   ).grid(row=0, column=2, padx=(0, 16))

        ttk.Label(tb, text="N. Cicli:").grid(row=0, column=3, padx=(0, 4))
        self._cycles_spin = ttk.Spinbox(tb, from_=1, to=9999, increment=1, width=6,
                                        command=self._on_cycles_changed)
        self._cycles_spin.set(1)
        self._cycles_spin.grid(row=0, column=4)
        self._cycles_spin.bind("<FocusOut>", lambda e: self._on_cycles_changed())
        self._cycles_spin.bind("<Return>",   lambda e: self._on_cycles_changed())

        ttk.Checkbutton(
            tb,
            text="Auto-Stop REC",
            variable=self._stop_rec_var,
            command=self._on_stop_rec_toggle,
        ).grid(row=1, column=0, sticky='w')

    def _build_table(self, parent):
        """Riga 0: Treeview con scrollbar."""
        wrap = ttk.Frame(parent)
        wrap.grid(row=0, column=0, sticky="nsew", padx=8, pady=(6, 0))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        sb = ttk.Scrollbar(wrap, orient="vertical")
        sb.grid(row=0, column=1, sticky="ns")

        self._table = ttk.Treeview(
            wrap,
            columns=("#", "Comando", "t[s]", "Valore", "Banco[km/h]", "Etichetta"),
            show='headings',
            yscrollcommand=sb.set,
            style='Compact.Treeview',
        )
        col_defs = [
            ("#",          28, 'center'),
            ("Comando",    88, 'center'),
            ("t[s]",       48, 'center'),
            ("Valore",     62, 'center'),
            ("Banco[km/h]",78, 'center'),
            ("Etichetta",  90, 'w'),
        ]
        for col, w, anchor in col_defs:
            self._table.heading(col, text=col)
            self._table.column(col, width=w, anchor=anchor, stretch=False)
        self._table.grid(row=0, column=0, sticky="nsew")
        sb.config(command=self._table.yview)
        self._table.tag_configure('oddrow',     background='lightgrey')
        self._table.tag_configure('evenrow',    background='white')
        self._table.tag_configure('currentrow', background='yellow')

        self._autoscroll_table = tk.BooleanVar(value=True)
        ttk.Checkbutton(wrap, text='Auto-scroll',
                        variable=self._autoscroll_table
                        ).grid(row=1, column=0, sticky='w', pady=(2, 0))

    def _build_timebar(self, parent):
        """Righe 3-4: separatore + tempi su 2 righe con larghezza fissa."""
        ttk.Separator(parent, orient='horizontal').grid(
            row=3, column=0, sticky='ew', padx=8, pady=(2, 0))

        tb = ttk.Frame(parent)
        tb.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 8))

        # Larghezza fissa per i valori: "00:00:00" = 8 car, "99g 00:00:00" = 12 car
        # Usiamo font monospace per garantire stabilità
        _F_LBL = ('Helvetica', 9)
        _F_VAL = ('Courier', 9, 'bold')   # monospace → larghezza costante
        _W_SHORT = 9   # HH:MM:SS
        _W_LONG  = 13  # Xg HH:MM:SS (per Totale e Fine che possono superare 24h)

        def _pair(row, col, label_text, attr, fg, width):
            ttk.Label(tb, text=label_text, font=_F_LBL
                      ).grid(row=row, column=col, sticky='w', padx=(0, 2))
            lbl = tk.Label(tb, text="--:--:--", font=_F_VAL,
                           fg=fg, width=width, anchor='w')
            lbl.grid(row=row, column=col + 1, sticky='w', padx=(0, 16))
            setattr(self, attr, lbl)

        # Riga 0: Totale  |  Rimanente
        _pair(0, 0, "Totale:",     "_lbl_total",     "black",   _W_LONG)
        _pair(0, 2, "Rimanente:",  "_lbl_remaining",  "black",   _W_SHORT)

        # Riga 1: Inizio  |  Fine
        _pair(1, 0, "Inizio:",     "_lbl_inizio",    "#005500", _W_SHORT)
        _pair(1, 2, "Fine:",       "_lbl_fine",      "#885500", _W_LONG)

    # ── Colonna B: comandi manuali + banco ────────────────────────────────────

    def _build_col_b(self):
        col_b = ttk.Frame(self)
        col_b.grid(row=0, column=1, sticky="new")
        col_b.grid_columnconfigure(0, weight=1)

        f = ttk.LabelFrame(col_b, text="Comandi")
        f.grid(row=0, column=0, sticky="ew")

        _W_SPIN = 8
        _PX = 5
        _PY = 3

        # Prima: 3 colonne (label | spinbox | pulsante)
        # Ora:   2 colonne (spinbox | pulsante autodescrittivo)
        f.grid_columnconfigure(0, weight=0)  # spinbox — fisso
        f.grid_columnconfigure(1, weight=1)  # pulsante — si espande

        # ── Sezione BLE ───────────────────────────────────────────────────────
        ttk.Label(f, text="BLE", font=('Helvetica', 8, 'bold'),
                  foreground='#1565C0').grid(
            row=0, column=0, columnspan=2, sticky='w', padx=_PX, pady=(6, 2))

        specs = [
            ("Livello [/200]", self._on_send_level, 0, 200, 1, None, 'livello'),
            ("Potenza [W]", self._on_send_power, 0, 5000, 1, None, 'potenza'),
            ("Simulazione [%]", self._on_send_simulation, -999999, 999999, 0.1, "%.1f", 'simulazione'),
        ]
        self._manual_entries = {}
        for i, (btn_label, cmd, lo, hi, inc, fmt, key) in enumerate(specs, start=1):
            kw = dict(from_=lo, to=hi, increment=inc, width=_W_SPIN)
            if fmt:
                kw['format'] = fmt
            spin = ttk.Spinbox(f, **kw)
            spin.set(0 if fmt is None else "0.0")
            spin.grid(row=i, column=0, padx=(_PX, 2), pady=_PY)
            self._manual_entries[key] = spin
            ttk.Button(f, text=btn_label,
                       command=lambda c=cmd, k=key: c(self._manual_entries[k].get())
                       ).grid(row=i, column=1, padx=(2, _PX), pady=_PY, sticky='ew')

        # ── Zero Freno ────────────────────────────────────────────────────────
        btn_zero = tk.Button(
            f, text="⬛  ZERO FRENO",
            command=lambda: self._on_send_level(0),
            font=('Helvetica', 10, 'bold'),
            bg="#0D3B6E", fg="white",
            activebackground="#082B52", activeforeground="white",
            relief='raised', bd=2, cursor='hand2',
        )
        btn_zero.grid(row=4, column=0, columnspan=2,  # ← era columnspan=3
                      sticky="ew", padx=_PX, pady=(6, 4))

        # ── Separatore ────────────────────────────────────────────────────────
        ttk.Separator(f, orient='horizontal').grid(
            row=5, column=0, columnspan=2, sticky='ew', padx=_PX, pady=(4, 4))

        # ── Sezione Banco ─────────────────────────────────────────────────────
        ttk.Label(f, text="Banco", font=('Helvetica', 8, 'bold'),
                  foreground='#444444').grid(
            row=6, column=0, columnspan=2, sticky='w', padx=_PX, pady=(0, 2))

        self._speed_spin = ttk.Spinbox(f, from_=0.0, to=100.0, increment=0.1,
                                       format="%.1f", width=_W_SPIN)
        self._speed_spin.set("0.0")
        self._speed_spin.grid(row=7, column=0, padx=(_PX, 2), pady=_PY)
        ttk.Button(f, text="Vel. Banco [km/h]",  # ← era Label "Vel [km/h]" + Button "Set"
                   command=self._clicked_set_speed).grid(
            row=7, column=1, padx=(2, _PX), pady=_PY, sticky='ew')

        # ── STOP BANCO ────────────────────────────────────────────────────────
        btn_stop = tk.Button(
            f, text="⏹  STOP BANCO",
            command=self._on_emergency_stop,
            font=('Helvetica', 12, 'bold'),
            bg="#D0021B", fg="white",
            activebackground="#B00000", activeforeground="white",
            relief='raised', bd=3, cursor='hand2', height=2,
        )
        btn_stop.grid(row=8, column=0, columnspan=2,  # ← era columnspan=3
                      sticky="ew", padx=_PX, pady=(6, 6))
        try:
            btn_stop.config(highlightthickness=2,
                            highlightbackground="#660000",
                            highlightcolor="#FFFFFF")
        except Exception:
            pass
        self._btn_stop_banco = btn_stop

    # ── Helpers interni ───────────────────────────────────────────────────────

    @property
    def stop_rec_on_auto_end(self) -> bool:
        return self._stop_rec_var.get()

    def _on_stop_rec_toggle(self):
        if self._on_stop_rec_changed is not None:
            self._on_stop_rec_changed(self._stop_rec_var.get())

    def _clicked_set_speed(self):
        try:
            self._on_set_banco(float(self._speed_spin.get()))
        except (ValueError, TypeError):
            self._log.error(f"Valore velocità non valido: {self._speed_spin.get()}")

    def _on_cycles_changed(self):
        if self._csv_single_cycle_seconds == 0:
            return
        try:
            n = max(1, int(self._cycles_spin.get()))
        except (ValueError, TypeError):
            n = 1
        total = self._csv_single_cycle_seconds * n
        self.total_test_duration_seconds = total
        self._lbl_total.config(text=_fmt(total))

    def _start_countdown(self):
        """
        Avvia il conto alla rovescia basato su wall-clock (time.monotonic).
        Non accumula deriva perché legge il tempo reale ad ogni tick
        invece di decrementare un contatore.
        """
        import time as _time
        self._stop_countdown()
        _t0    = _time.monotonic()
        _total = float(self.total_test_duration_seconds)

        def _tick():
            if not self.auto_commands_running:
                self._countdown_id = None
                return
            elapsed   = _time.monotonic() - _t0
            remaining = max(0.0, _total - elapsed)
            self.remaining_test_duration_seconds = int(remaining)
            self._lbl_remaining.config(text=_fmt(remaining))
            # Aggiorna ogni 500 ms per display fluido; si ferma quando arriva a zero
            if remaining > 0.5:
                self._countdown_id = self.after(500, _tick)
            else:
                self._lbl_remaining.config(text="00:00:00")
                self._countdown_id = None

        # Prima chiamata dopo 1 s: il display iniziale è già impostato in start()
        self._countdown_id = self.after(1000, _tick)

    def _stop_countdown(self):
        if self._countdown_id is not None:
            self.after_cancel(self._countdown_id)
            self._countdown_id = None

    def _reset_table_highlights(self):
        for index, item in enumerate(self._table.get_children()):
            self._table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def load_csv(self):
        if self.auto_commands_running:
            self._log.warning("Comandi automatici in corso. Impossibile caricare il file CSV.")
            return
        file_path = filedialog.askopenfilename(
            filetypes=[
                ("File sequenza", "*.csv *.xlsx *.xls"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xls"),
                ("Tutti i file", "*.*"),
            ]
        )
        if not file_path:
            return

        self._stop_countdown()
        self._lbl_remaining.config(text="--:--:--")
        self._lbl_total.config(text="--:--:--")
        self._lbl_inizio.config(text="--:--:--", fg='#005500')
        self._lbl_fine.config(text="--:--:--", fg='#885500')
        self.total_test_duration_seconds = 0
        self._csv_single_cycle_seconds = 0

        for item in self._table.get_children():
            self._table.delete(item)

        commands = DataProcessor.read_brake_commands_from_file(file_path)
        if not commands:
            self._log.warning("File vuoto o non valido (nessun comando riconosciuto).")
            return

        single_cycle_s = 0
        for i, command in enumerate(commands):
            try:
                single_cycle_s += int(float(command[1]))   # col 1 = tempo_s
            except (ValueError, TypeError, IndexError):
                self._log.warning(f"Valore tempo non valido nel file: {command}")
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self._table.insert("", "end", values=(i + 1, *command), tags=(tag,))

        self._csv_single_cycle_seconds = single_cycle_s
        self._on_cycles_changed()
        self._log.info(
            f"Caricati {len(commands)} comandi. Durata 1 ciclo: {_fmt(single_cycle_s)}")

    def start(self):
        if self.auto_commands_running:
            self._log.warning("Comandi automatici già in esecuzione.")
            return
        if not self._table.get_children():
            self._log.info("La tabella dei comandi è vuota.")
            return

        # Controllo pre-avvio (es. registrazione non attiva)
        if self._on_before_auto_start is not None:
            if not self._on_before_auto_start():
                return

        try:
            num_cycles = max(1, int(self._cycles_spin.get()))
        except (ValueError, TypeError):
            num_cycles = 1

        if self._csv_single_cycle_seconds == 0:
            s = 0
            for item in self._table.get_children():
                try:
                    s += int(float(self._table.item(item, 'values')[2]))
                except Exception:
                    pass
            self._csv_single_cycle_seconds = s

        self.total_test_duration_seconds = self._csv_single_cycle_seconds * num_cycles
        self._lbl_total.config(text=_fmt(self.total_test_duration_seconds))

        commands      = [self._table.item(i, 'values') for i in self._table.get_children()]
        command_items = self._table.get_children()
        self._reset_table_highlights()
        total_commands = len(commands) * num_cycles

        def send_next(absolute_index):
            if absolute_index < total_commands and self.auto_commands_running:
                index = absolute_index % len(commands)
                cycle = absolute_index // len(commands) + 1
                # Treeview restituisce: (#, command_type, tempo_s, valore_rullo, banco_kmh, etichetta)
                _num, command_type, tempo_s, valore_rullo, banco_kmh, etichetta = commands[index]
                try:
                    wait_time = int(float(tempo_s))
                except (ValueError, TypeError):
                    wait_time = 0

                if absolute_index > 0:
                    prev = (absolute_index - 1) % len(commands)
                    self._table.item(command_items[prev],
                                     tags=('evenrow' if prev % 2 == 0 else 'oddrow',))
                self._table.item(command_items[index], tags=('currentrow',))
                if self._autoscroll_table.get():
                    self._table.see(command_items[index])
                self._on_auto_status('ok', 'Auto: ON')

                if command_type == "save" and self._on_save is not None:
                    label_str = f"'{etichetta}'" if etichetta else "(nessuna)"
                    self._log.info(
                        f"[Auto] Raccolta media {label_str} — finestra {wait_time}s...")
                    self._on_auto_status('ok', 'Auto: SAVE…')
                    def _resume_save(success: bool, _ai=absolute_index):
                        if not self.auto_commands_running:
                            return
                        if success:
                            self._log.info("[Auto] Media salvata nel file sintesi.")
                        else:
                            self._log.warning("[Auto] Raccolta interrotta — riga non salvata.")
                        self._auto_command_id = self.after(
                            0, lambda: send_next(_ai + 1))
                    self._on_save(wait_time, str(etichetta), _resume_save)

                elif command_type == "spindown" and self._on_spindown is not None:
                    self._log.info("[Auto] Avvio calibrazione spin-down automatica...")
                    def _resume(success: bool, _ai=absolute_index):
                        if not self.auto_commands_running:
                            return
                        if success:
                            self._log.info("[Auto] Calibrazione completata — sequenza ripresa.")
                        else:
                            self._log.warning("[Auto] Calibrazione fallita — sequenza ripresa comunque.")
                        self._auto_command_id = self.after(0, lambda: send_next(_ai + 1))
                    self._on_spindown(_resume)

                else:
                    self._on_dispatch(command_type, valore_rullo, banco_kmh)
                    self._auto_command_id = self.after(
                        wait_time * 1000, lambda: send_next(absolute_index + 1))
            else:
                self.auto_commands_running = False
                self._stop_countdown()
                self._lbl_remaining.config(text="00:00:00")
                self._on_auto_status('warn', 'Auto: OK')
                self._lbl_fine.config(
                    text=datetime.datetime.now().strftime("%H:%M:%S"),
                    fg='#005500')
                self._log.info(f"Comandi automatici completati ({num_cycles} ciclo/i)")
                # Sicurezza: freno a 0 e banco a 0 al termine di tutti i cicli
                self._log.info("Fine sequenza — invio freno=0 e velocità banco=0 (sicurezza)")
                self._on_send_level(0)
                self._on_set_banco(0)
                self._reset_table_highlights()
                self._on_auto_completed()

        self.auto_commands_running = True
        self._on_auto_status('ok', 'Auto: ON')

        now = datetime.datetime.now()
        self._lbl_inizio.config(text=now.strftime("%H:%M:%S"), fg='#005500')
        fine = now + datetime.timedelta(seconds=self.total_test_duration_seconds)
        self._lbl_fine.config(text=fine.strftime("%H:%M:%S") + " ~", fg='#885500')

        self.remaining_test_duration_seconds = self.total_test_duration_seconds
        self._lbl_remaining.config(text=_fmt(self.remaining_test_duration_seconds))
        self._start_countdown()
        send_next(0)

    def stop(self):
        if self.auto_commands_running:
            self.auto_commands_running = False
            self._stop_countdown()
            self._lbl_remaining.config(text="Interrotto")
            self._lbl_fine.config(
                text=datetime.datetime.now().strftime("%H:%M:%S"),
                fg='#550000')
            self._on_auto_status('err', 'Auto: OFF')
            if self._auto_command_id is not None:
                self.after_cancel(self._auto_command_id)
                self._auto_command_id = None
            self._log.info("Comandi automatici interrotti")
            for item in self._table.get_children():
                if 'currentrow' in self._table.item(item, 'tags'):
                    idx = self._table.index(item)
                    self._table.item(item, tags=('evenrow' if idx % 2 == 0 else 'oddrow',))
                    break
        else:
            self._log.info("Non ci sono comandi automatici attivi")
            self._lbl_remaining.config(text="--:--:--")
            self._lbl_total.config(text="--:--:--")
            self.total_test_duration_seconds = 0

    def flash_stop_button(self):
        try:
            orig = self._btn_stop_banco.cget("bg")
            self._btn_stop_banco.config(bg="#7A0000")
            self.after(180, lambda: self._btn_stop_banco.config(bg=orig))
        except Exception:
            pass