"""
Pannello CSV: tabella comandi + controlli per i comandi automatici + countdown.
Gestisce internamente il loop after() e lo stato auto_commands_running.
Delega l'invio dei comandi ai callback forniti da main_window.
"""
import tkinter as tk
from tkinter import ttk, filedialog
import datetime
import logging
from logic.data_processing import DataProcessor


def _format_time(seconds):
    try:
        s = int(float(seconds))
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    except Exception:
        return "--:--:--"


class CsvPanel(ttk.Frame):
    """
    Contiene:
      - Tabella comandi CSV (colonna A, row 0)
      - Controlli automatici (colonna A, row 1)
      - Comandi manuali BLE + controllo banco (colonna B, rowspan 2)
    """

    def __init__(self, parent,
                 on_dispatch,          # (command_type, value, speed_banco) — invia un comando
                 on_set_banco_speed,   # (speed_kmh) — imposta velocità banco
                 on_auto_status,       # (led_state, label_text) — aggiorna status_bar.set_auto()
                 on_auto_completed,    # () — chiamato al termine dei cicli
                 on_send_level,        # (value) — comando manuale livello
                 on_send_power,        # (value) — comando manuale potenza
                 on_send_simulation,   # (value) — comando manuale simulazione
                 on_emergency_stop,    # () — pulsante STOP BANCO
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._on_dispatch       = on_dispatch
        self._on_set_banco      = on_set_banco_speed
        self._on_auto_status    = on_auto_status
        self._on_auto_completed = on_auto_completed
        self._on_send_level     = on_send_level
        self._on_send_power     = on_send_power
        self._on_send_simulation = on_send_simulation
        self._on_emergency_stop = on_emergency_stop

        self._log = logging.getLogger(__name__)
        self.auto_commands_running  = False
        self._csv_single_cycle_seconds = 0
        self.total_test_duration_seconds = 0
        self.remaining_test_duration_seconds = 0
        self._auto_command_id   = None
        self._countdown_id      = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._build_csv_table()
        self._build_auto_controls()
        self._build_col_b()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build_csv_table(self):
        f = ttk.LabelFrame(self, text="Comandi da CSV")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)

        sb = ttk.Scrollbar(f, orient="vertical")
        sb.grid(row=0, column=1, sticky="ns")

        self._table = ttk.Treeview(
            f,
            columns=("Comando", "Val", "t[s]", "Vb[km/h]"),
            show='headings',
            yscrollcommand=sb.set,
            style='Compact.Treeview',
        )
        for col, w in [("Comando", 95), ("Val", 70), ("t[s]", 55), ("Vb[km/h]", 85)]:
            self._table.heading(col, text=col)
            self._table.column(col, width=w, anchor='center')
        self._table.grid(row=0, column=0, sticky="nsew", padx=8, pady=4)
        sb.config(command=self._table.yview)
        self._table.tag_configure('oddrow',     background='lightgrey')
        self._table.tag_configure('evenrow',    background='white')
        self._table.tag_configure('currentrow', background='yellow')

    def _build_auto_controls(self):
        f = ttk.LabelFrame(self, text="Comandi automatici")
        f.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=1)

        self._lbl_status = tk.Label(f, text="Comandi Automatici: OFF",
                                    fg="red", font=('Helvetica', 9))
        self._lbl_status.grid(row=0, column=0, columnspan=2, padx=8, pady=(4, 2), sticky="w")

        ttk.Button(f, text="Carica CSV",
                   command=self.load_csv).grid(row=1, column=0, padx=(8, 4), pady=2, sticky='ew')
        ttk.Button(f, text="▶  Start",
                   command=self.start).grid(row=1, column=1, padx=(4, 8), pady=2, sticky='ew')

        frame_cicli = ttk.Frame(f)
        frame_cicli.grid(row=2, column=0, padx=8, pady=2, sticky='w')
        ttk.Label(frame_cicli, text="N. Cicli:").grid(row=0, column=0, padx=(0, 4))
        self._cycles_spin = ttk.Spinbox(frame_cicli, from_=1, to=9999, increment=1, width=6,
                                        command=self._on_cycles_changed)
        self._cycles_spin.set(1)
        self._cycles_spin.grid(row=0, column=1)
        self._cycles_spin.bind("<FocusOut>", lambda e: self._on_cycles_changed())
        self._cycles_spin.bind("<Return>",   lambda e: self._on_cycles_changed())

        ttk.Button(f, text="■  Stop",
                   command=self.stop).grid(row=2, column=1, padx=(4, 8), pady=2, sticky='ew')

        # Riga durate
        dur = ttk.Frame(f)
        dur.grid(row=3, column=0, columnspan=2, sticky='ew', padx=8, pady=(2, 2))
        ttk.Label(dur, text="Totale:").grid(row=0, column=0, sticky='w', padx=(0, 4))
        self._lbl_total = ttk.Label(dur, text="--:--:--", font=('Helvetica', 9, 'bold'))
        self._lbl_total.grid(row=0, column=1, sticky='w', padx=(0, 14))
        ttk.Label(dur, text="Rimanente:").grid(row=0, column=2, sticky='w', padx=(0, 4))
        self._lbl_remaining = ttk.Label(dur, text="--:--:--", font=('Helvetica', 9, 'bold'))
        self._lbl_remaining.grid(row=0, column=3, sticky='w')

        # Riga ora inizio / fine
        times = ttk.Frame(f)
        times.grid(row=4, column=0, columnspan=2, sticky='ew', padx=8, pady=(2, 6))
        ttk.Label(times, text="Inizio:").grid(row=0, column=0, sticky='w', padx=(0, 4))
        self._lbl_inizio = ttk.Label(times, text="--:--:--",
                                     font=('Helvetica', 9, 'bold'), foreground='#005500')
        self._lbl_inizio.grid(row=0, column=1, sticky='w', padx=(0, 14))
        ttk.Label(times, text="Fine:").grid(row=0, column=2, sticky='w', padx=(0, 4))
        self._lbl_fine = ttk.Label(times, text="--:--:--",
                                   font=('Helvetica', 9, 'bold'), foreground='#550000')
        self._lbl_fine.grid(row=0, column=3, sticky='w')

    def _build_col_b(self):
        col_b = ttk.Frame(self)
        col_b.grid(row=0, column=1, rowspan=2, sticky="new", padx=(4, 0))
        col_b.grid_columnconfigure(0, weight=1)

        # Comandi manuali BLE
        frame_cmd = ttk.LabelFrame(col_b, text="Comandi manuali BLE")
        frame_cmd.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        frame_cmd.grid_columnconfigure(0, weight=2)
        frame_cmd.grid_columnconfigure(1, weight=1)
        frame_cmd.grid_columnconfigure(2, weight=1)

        specs = [
            ("Livello [/200]",  self._on_send_level,      0,       200,    1,    None,   'livello'),
            ("Potenza [W]",     self._on_send_power,       0,      5000,    1,    None,   'potenza'),
            ("Simulazione [%]", self._on_send_simulation, -999999, 999999, 0.1, "%.1f",  'simulazione'),
        ]
        self._manual_entries = {}
        for i, (label, cmd, lo, hi, inc, fmt, key) in enumerate(specs):
            ttk.Label(frame_cmd, text=label).grid(row=i, column=0, padx=5, sticky="ew")
            kw = dict(from_=lo, to=hi, increment=inc, width=12)
            if fmt:
                kw['format'] = fmt
            spin = ttk.Spinbox(frame_cmd, **kw)
            spin.set(0 if fmt is None else 0.0)
            spin.grid(row=i, column=1, padx=5, sticky="ew")
            self._manual_entries[key] = spin
            ttk.Button(frame_cmd, text="Invia",
                       command=lambda c=cmd, k=key: c(self._manual_entries[k].get())
                       ).grid(row=i, column=2, padx=5, sticky="ew")

        # Controllo banco
        frame_banco = ttk.LabelFrame(col_b, text="Controllo Banco")
        frame_banco.grid(row=1, column=0, sticky="ew")
        frame_banco.grid_columnconfigure(0, weight=1)

        vel = ttk.Frame(frame_banco)
        vel.grid(row=0, column=0, sticky="ew", padx=6, pady=(8, 4))
        ttk.Label(vel, text="Vel [km/h]:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        self._speed_spin = ttk.Spinbox(vel, from_=0.0, to=100.0, increment=0.1,
                                       format="%.1f", width=8)
        self._speed_spin.set(0.0)
        self._speed_spin.grid(row=0, column=1, padx=(0, 4))
        ttk.Button(vel, text="Set",
                   command=self._clicked_set_speed).grid(row=0, column=2)

        btn_stop = tk.Button(
            frame_banco, text="⏹  STOP BANCO",
            command=self._on_emergency_stop,
            font=('Helvetica', 12, 'bold'),
            bg="#D0021B", fg="white",
            activebackground="#B00000", activeforeground="white",
            relief='raised', bd=3, cursor='hand2', height=2,
        )
        btn_stop.grid(row=1, column=0, sticky="ew", padx=6, pady=(4, 8))
        try:
            btn_stop.config(highlightthickness=2,
                            highlightbackground="#660000",
                            highlightcolor="#FFFFFF")
        except Exception:
            pass
        self._btn_stop_banco = btn_stop

    # ── Helpers interni ───────────────────────────────────────────────────────

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
        self._lbl_total.config(text=_format_time(total))

    def _start_countdown(self):
        self._stop_countdown()

        def _tick():
            if self.auto_commands_running and self.remaining_test_duration_seconds > 0:
                self.remaining_test_duration_seconds -= 1
                self._lbl_remaining.config(text=_format_time(self.remaining_test_duration_seconds))
                self._countdown_id = self.after(1000, _tick)
            elif self.auto_commands_running:
                self._lbl_remaining.config(text="00:00:00")
                self._countdown_id = None
            else:
                self._countdown_id = None

        _tick()

    def _stop_countdown(self):
        if self._countdown_id is not None:
            self.after_cancel(self._countdown_id)
            self._countdown_id = None

    def _reset_table_highlights(self):
        for index, item in enumerate(self._table.get_children()):
            self._table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def load_csv(self):
        """Apre il file dialog, popola la tabella e calcola la durata del ciclo."""
        if self.auto_commands_running:
            self._log.warning("Comandi automatici in corso. Impossibile caricare il file CSV.")
            return
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return

        self._stop_countdown()
        self._lbl_remaining.config(text="--:--:--")
        self._lbl_total.config(text="--:--:--")
        self._lbl_inizio.config(text="--:--:--", foreground='#005500')
        self._lbl_fine.config(text="--:--:--", foreground='#550000')
        self.total_test_duration_seconds = 0
        self._csv_single_cycle_seconds = 0

        for item in self._table.get_children():
            self._table.delete(item)

        commands = DataProcessor.read_brake_commands_from_csv(file_path)
        if not commands:
            self._log.warning("File CSV vuoto o non valido.")
            return

        single_cycle_s = 0
        for i, command in enumerate(commands):
            try:
                single_cycle_s += int(float(command[2]))
            except (ValueError, TypeError, IndexError):
                self._log.warning(f"Valore tempo non valido nel CSV: {command}")
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self._table.insert("", "end", values=command, tags=(tag,))

        self._csv_single_cycle_seconds = single_cycle_s
        self._on_cycles_changed()
        self._log.info(
            f"Caricati {len(commands)} comandi. Durata 1 ciclo: {_format_time(single_cycle_s)}")

    def start(self):
        """Avvia la sequenza di comandi automatici."""
        if self.auto_commands_running:
            self._log.warning("Comandi automatici già in esecuzione.")
            return
        if not self._table.get_children():
            self._log.info("La tabella dei comandi è vuota.")
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
        self._lbl_total.config(text=_format_time(self.total_test_duration_seconds))

        commands      = [self._table.item(i, 'values') for i in self._table.get_children()]
        command_items = self._table.get_children()
        self._reset_table_highlights()
        total_commands = len(commands) * num_cycles

        def send_next(absolute_index):
            if absolute_index < total_commands and self.auto_commands_running:
                index = absolute_index % len(commands)
                cycle = absolute_index // len(commands) + 1
                command_type, value, wait_time, speed_banco = commands[index]
                wait_time = int(wait_time)

                if absolute_index > 0:
                    prev = (absolute_index - 1) % len(commands)
                    self._table.item(command_items[prev],
                                     tags=('evenrow' if prev % 2 == 0 else 'oddrow',))
                self._table.item(command_items[index], tags=('currentrow',))

                self._lbl_status.config(
                    text=f"Comandi Automatici: ON  [Ciclo {cycle}/{num_cycles}]", fg="green")
                self._on_auto_status('ok', 'Auto: ON')
                self._on_dispatch(command_type, value, speed_banco)

                self._auto_command_id = self.after(
                    wait_time * 1000, lambda: send_next(absolute_index + 1))
            else:
                self.auto_commands_running = False
                self._stop_countdown()
                self._lbl_remaining.config(text="00:00:00")
                self._lbl_status.config(text="Comandi Automatici: Completati", fg="blue")
                self._on_auto_status('warn', 'Auto: OK')
                self._lbl_fine.config(
                    text=datetime.datetime.now().strftime("%H:%M:%S"),
                    foreground='#005500')
                self._log.info(f"Comandi automatici completati ({num_cycles} ciclo/i)")
                self._on_set_banco(0)
                self._reset_table_highlights()
                self._on_auto_completed()

        self.auto_commands_running = True
        self._lbl_status.config(
            text=f"Comandi Automatici: ON  [Ciclo 1/{num_cycles}]", fg="green")
        self._on_auto_status('ok', 'Auto: ON')

        now = datetime.datetime.now()
        self._lbl_inizio.config(text=now.strftime("%H:%M:%S"), foreground='#005500')
        fine = now + datetime.timedelta(seconds=self.total_test_duration_seconds)
        self._lbl_fine.config(text=fine.strftime("%H:%M:%S") + " ~", foreground='#885500')

        self.remaining_test_duration_seconds = self.total_test_duration_seconds
        self._lbl_remaining.config(text=_format_time(self.remaining_test_duration_seconds))
        self._start_countdown()
        send_next(0)

    def stop(self):
        """Interrompe la sequenza in corso (o resetta le label se era già ferma)."""
        if self.auto_commands_running:
            self.auto_commands_running = False
            self._stop_countdown()
            self._lbl_remaining.config(text="Interrotto")
            self._lbl_fine.config(
                text=datetime.datetime.now().strftime("%H:%M:%S"),
                foreground='#550000')
            self._lbl_status.config(text="Comandi Automatici: OFF", fg="red")
            self._on_auto_status('err', 'Auto: OFF')
            if self._auto_command_id is not None:
                self.after_cancel(self._auto_command_id)
                self._auto_command_id = None
            self._log.info("Comandi automatici interrotti")
            # Rimuove l'evidenziazione dalla riga corrente
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
        """Feedback visivo breve sul pulsante STOP BANCO."""
        try:
            orig = self._btn_stop_banco.cget("bg")
            self._btn_stop_banco.config(bg="#7A0000")
            self.after(180, lambda: self._btn_stop_banco.config(bg=orig))
        except Exception:
            pass
