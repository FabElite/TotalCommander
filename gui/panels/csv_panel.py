"""
Pannello comandi: tabella CSV + controlli automatici unificati in una sola box,
affiancati dai comandi manuali BLE e dal controllo banco.

Layout toolbar (stile media-player):
  [Carica file]  [⏮]  [▶ Start / ⏸ Pausa]  [⏭]  [■ Stop]  N=[1]
  [Auto-Stop REC □]
"""
import tkinter as tk
from tkinter import ttk, filedialog
import datetime
import time as _time
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
                 on_eeprom=None,
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
        self._on_eeprom            = on_eeprom
        self._stop_rec_var         = tk.BooleanVar(value=stop_rec_on_auto_end)

        self._log = logging.getLogger(__name__)

        # ── Stato sequenza ─────────────────────────────────────────────────────
        self.auto_commands_running           = False
        self._csv_single_cycle_seconds       = 0
        self.total_test_duration_seconds     = 0
        self.remaining_test_duration_seconds = 0
        self._auto_command_id                = None
        self._countdown_id                   = None

        # ── Stato navigazione / pausa ──────────────────────────────────────────
        # _paused          : True quando la sequenza è esplicitamente in pausa
        # _pending_pause   : True se pausa richiesta durante save/spindown (async);
        #                    verrà applicata al termine dell'operazione corrente.
        #                    Un secondo click sul pulsante annulla la pendenza.
        # _current_abs_idx : absolute_index del comando attualmente in esecuzione
        # _pause_remaining_ms: ms residui del timer del comando corrente al momento
        #                    della pausa (0 se pausa dopo save/spindown)
        # _after_deadline  : timestamp monotonic della scadenza del timer corrente;
        #                    usato per calcolare _pause_remaining_ms
        # _back_origin     : _current_abs_idx al momento del primo press di ⏮
        #                    (-1 = nessuna navigazione back in corso)
        # _back_count      : quante volte ⏮ è stato premuto nella sessione corrente
        #                    (0 = restart corrente, 1 = uno indietro, …)
        # _commands / _command_items / _total_commands / _num_cycles / _send_next:
        #                    riferimenti alla sessione start() corrente, necessari
        #                    per chiamare send_next dall'esterno della closure
        self._paused             = False
        self._pending_pause      = False
        self._current_abs_idx    = 0
        self._pause_remaining_ms = 0
        self._after_deadline     = 0.0
        self._back_origin        = -1
        self._back_count         = 0
        self._commands           = []
        self._command_items      = []
        self._total_commands     = 0
        self._num_cycles         = 1
        self._send_next          = None   # closure send_next dell'ultima start()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_sequence_panel()
        self._build_col_b()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _build_sequence_panel(self):
        """Box unica: tabella → toolbar → timebar."""
        f = ttk.LabelFrame(self, text="Sequenza automatica")
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        self._build_table(f)       # row 0
        self._build_toolbar(f)     # rows 1,2
        self._build_timebar(f)     # rows 3,4

    def _build_toolbar(self, parent):
        ttk.Separator(parent, orient='horizontal').grid(
            row=1, column=0, sticky='ew', padx=8, pady=(2, 0))

        tb = ttk.Frame(parent)
        tb.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 4))
        tb.grid_columnconfigure(2, weight=1)  # ▶/⏸ si espande con la finestra

        # ── Riga 0: controlli trasporto ───────────────────────────────────────
        ttk.Button(tb, text="Carica file",
                   command=self.load_csv, width=11
                   ).grid(row=0, column=0, padx=(0, 8))

        self._btn_prev = ttk.Button(
            tb, text="⏮", width=3,
            command=self.go_back, state='disabled')
        self._btn_prev.grid(row=0, column=1, padx=(0, 2))

        self._btn_play_pause = ttk.Button(
            tb, text="▶  Start",
            command=self._on_play_pause)
        self._btn_play_pause.grid(row=0, column=2, padx=(0, 2), sticky='ew')

        self._btn_skip = ttk.Button(
            tb, text="⏭", width=3,
            command=self.skip_next, state='disabled')
        self._btn_skip.grid(row=0, column=3, padx=(0, 8))

        ttk.Button(tb, text="■  Stop",
                   command=self.stop, width=9
                   ).grid(row=0, column=4)

        # ── Riga 1: checkbox a sx, N. Cicli a dx ─────────────────────────────
        row1 = ttk.Frame(tb)
        row1.grid(row=1, column=0, columnspan=5, sticky='ew', pady=(4, 0))
        row1.grid_columnconfigure(0, weight=1)  # checkbox prende spazio residuo

        ttk.Checkbutton(
            row1, text="Auto-Stop REC",
            variable=self._stop_rec_var,
            command=self._on_stop_rec_toggle,
        ).grid(row=0, column=0, sticky='w')

        ttk.Label(row1, text="N. Cicli:").grid(row=0, column=1, padx=(0, 4))
        self._cycles_spin = ttk.Spinbox(
            row1, from_=1, to=9999, increment=1, width=6,
            command=self._on_cycles_changed)
        self._cycles_spin.set(1)
        self._cycles_spin.grid(row=0, column=2)
        self._cycles_spin.bind("<FocusOut>", lambda e: self._on_cycles_changed())
        self._cycles_spin.bind("<Return>", lambda e: self._on_cycles_changed())


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
            columns=("#", "Comando", "t[s]", "Valore", "Banco[km/h]", "info"),
            show='headings',
            yscrollcommand=sb.set,
            style='Compact.Treeview',
        )
        col_defs = [
            ("#",           25, 'center', False),
            ("Comando",     80, 'center', False),
            ("t[s]",        45, 'center', False),
            ("Valore",      55, 'center', False),
            ("Banco[km/h]", 82, 'center', False),
            ("info",        10, 'w',      True),
        ]
        for col, w, anchor, stretch in col_defs:
            self._table.heading(col, text=col)
            self._table.column(col, width=w, anchor=anchor, stretch=stretch)
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

        _F_LBL = ('Helvetica', 9)
        _F_VAL = ('Courier', 9, 'bold')
        _W_SHORT = 9
        _W_LONG  = 13

        def _pair(row, col, label_text, attr, fg, width):
            ttk.Label(tb, text=label_text, font=_F_LBL
                      ).grid(row=row, column=col, sticky='w', padx=(0, 2))
            lbl = tk.Label(tb, text="--:--:--", font=_F_VAL,
                           fg=fg, width=width, anchor='w')
            lbl.grid(row=row, column=col + 1, sticky='w', padx=(0, 16))
            setattr(self, attr, lbl)

        _pair(0, 0, "Totale:",    "_lbl_total",     "black",   _W_LONG)
        _pair(0, 2, "Rimanente:", "_lbl_remaining",  "black",   _W_SHORT)
        _pair(1, 0, "Inizio:",    "_lbl_inizio",    "#005500", _W_SHORT)
        _pair(1, 2, "Fine:",      "_lbl_fine",      "#885500", _W_LONG)

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

        f.grid_columnconfigure(0, weight=0)
        f.grid_columnconfigure(1, weight=1)

        ttk.Label(f, text="BLE", font=('Helvetica', 8, 'bold'),
                  foreground='#1565C0').grid(
            row=0, column=0, columnspan=2, sticky='w', padx=_PX, pady=(6, 2))

        specs = [
            ("Livello [/200]",   self._on_send_level,       0,       200,    1,    None,   'livello'),
            ("Potenza [W]",      self._on_send_power,        0,      5000,    1,    None,   'potenza'),
            ("Simulazione [%]",  self._on_send_simulation, -999999, 999999, 0.1, "%.1f",   'simulazione'),
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

        btn_zero = tk.Button(
            f, text="⬛  ZERO FRENO",
            command=lambda: self._on_send_level(0),
            font=('Helvetica', 10, 'bold'),
            bg="#0D3B6E", fg="white",
            activebackground="#082B52", activeforeground="white",
            relief='raised', bd=2, cursor='hand2', height=2,
        )
        btn_zero.grid(row=4, column=0, columnspan=2,
                      sticky="ew", padx=_PX, pady=(6, 4))

        ttk.Separator(f, orient='horizontal').grid(
            row=5, column=0, columnspan=2, sticky='ew', padx=_PX, pady=(4, 4))

        ttk.Label(f, text="Banco", font=('Helvetica', 8, 'bold'),
                  foreground='#444444').grid(
            row=6, column=0, columnspan=2, sticky='w', padx=_PX, pady=(0, 2))

        self._speed_spin = ttk.Spinbox(f, from_=0.0, to=100.0, increment=0.1,
                                       format="%.1f", width=_W_SPIN)
        self._speed_spin.set("0.0")
        self._speed_spin.grid(row=7, column=0, padx=(_PX, 2), pady=_PY)
        ttk.Button(f, text="Vel. Banco [km/h]",
                   command=self._clicked_set_speed).grid(
            row=7, column=1, padx=(2, _PX), pady=_PY, sticky='ew')

        btn_stop = tk.Button(
            f, text="⏹  STOP BANCO",
            command=self._on_emergency_stop,
            font=('Helvetica', 12, 'bold'),
            bg="#D0021B", fg="white",
            activebackground="#B00000", activeforeground="white",
            relief='raised', bd=3, cursor='hand2', height=2,
        )
        btn_stop.grid(row=8, column=0, columnspan=2,
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
        Cattura total_test_duration_seconds al momento della chiamata come _total.
        """
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
            if remaining > 0.5:
                self._countdown_id = self.after(500, _tick)
            else:
                self._lbl_remaining.config(text="00:00:00")
                self._countdown_id = None

        self._countdown_id = self.after(1000, _tick)

    def _stop_countdown(self):
        if self._countdown_id is not None:
            self.after_cancel(self._countdown_id)
            self._countdown_id = None

    def _reset_table_highlights(self):
        for index, item in enumerate(self._table.get_children()):
            self._table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

    def _update_nav_buttons(self):
        """Abilita ⏮ e ⏭ solo quando la sequenza è attiva o in pausa."""
        active = self.auto_commands_running or self._paused
        s = 'normal' if active else 'disabled'
        self._btn_prev.config(state=s)
        self._btn_skip.config(state=s)

    def _remaining_seconds_from(self, abs_idx: int) -> int:
        """
        Somma i tempi di attesa (tempo_s) dei comandi da abs_idx fino a fine sequenza.
        Usato per ricalcolare il countdown dopo pause, salti e back.
        """
        if not self._commands or self._total_commands == 0:
            return 0
        n   = len(self._commands)
        tot = 0
        for i in range(abs_idx, self._total_commands):
            try:
                tot += int(float(self._commands[i % n][2]))   # col 2 = tempo_s
            except (ValueError, TypeError, IndexError):
                pass
        return tot

    # ── Navigazione / pausa ───────────────────────────────────────────────────

    def _on_play_pause(self):
        """
        Gestisce il pulsante play/pause unificato:
          - Idle          → start()
          - In esecuzione → pause()
          - In pausa      → resume()
          - Pending pause → annulla la pausa pendente
        """
        if self._paused:
            self.resume()
        elif self._pending_pause:
            self._pending_pause = False
            self._btn_play_pause.config(text="⏸  Pausa")
            self._log.info("Pausa annullata.")
        elif self.auto_commands_running:
            self.pause()
        else:
            self.start()

    def pause(self):
        """
        Mette in pausa la sequenza.

        Caso A — timer ordinario attivo (_auto_command_id set):
            Cancella il timer, salva il residuo in _pause_remaining_ms, entra in pausa.
        Caso B — operazione asincrona in corso (save / spindown):
            Imposta _pending_pause; la pausa verrà applicata al termine del callback.
            Un secondo click sul pulsante annulla la pendenza (→ _on_play_pause).
        """
        if not self.auto_commands_running or self._paused:
            return

        if self._auto_command_id is not None:
            # Pausa immediata
            self.after_cancel(self._auto_command_id)
            self._auto_command_id    = None
            self._pause_remaining_ms = max(
                0, int((self._after_deadline - _time.monotonic()) * 1000))
            self.auto_commands_running = False
            self._paused               = True
            self._stop_countdown()
            self._btn_play_pause.config(text="▶  Riprendi")
            self._on_auto_status('warn', 'Auto: PAUSA')
            self._update_nav_buttons()
            self._log.info(
                f"Sequenza in pausa (residuo timer: {self._pause_remaining_ms} ms).")
        else:
            # Pausa pendente durante save / spindown
            self._pending_pause = True
            self._btn_play_pause.config(text="⏸  Annulla ⏸")
            self._log.info(
                "Pausa richiesta — attendo fine operazione corrente (clicca ancora per annullare).")

    def resume(self):
        """
        Riprende la sequenza dopo una pausa immediata.
        Ricalcola il countdown come: residuo_timer_corrente + somma_tempi_successivi.
        """
        if not self._paused:
            return
        self._paused               = False
        self.auto_commands_running = True

        remaining_s = (self._pause_remaining_ms / 1000
                       + self._remaining_seconds_from(self._current_abs_idx + 1))
        self.total_test_duration_seconds = int(remaining_s)
        self._lbl_total.config(text=_fmt(self.total_test_duration_seconds))
        self._start_countdown()

        self._btn_play_pause.config(text="⏸  Pausa")
        self._on_auto_status('ok', 'Auto: ON')
        self._update_nav_buttons()

        # Pianifica l'avanzamento al comando successivo dopo il residuo del timer
        self._after_deadline  = _time.monotonic() + self._pause_remaining_ms / 1000
        self._auto_command_id = self.after(
            self._pause_remaining_ms, self._on_resume_advance)
        self._log.info("Sequenza ripresa.")

    def _on_resume_advance(self):
        """Fired quando il timer residuo di una pausa termina naturalmente."""
        self._auto_command_id = None
        self._back_origin     = -1
        self._back_count      = 0
        if self._send_next is not None:
            self._send_next(self._current_abs_idx + 1)

    def skip_next(self):
        """Salta immediatamente al comando successivo, resettando la navigazione back."""
        if not (self.auto_commands_running or self._paused):
            return
        self._back_origin = -1
        self._back_count  = 0
        self._jump_to(self._current_abs_idx + 1)

    def go_back(self):
        """
        Navigazione indietro con memoria della posizione originale:
          1° press → riavvia il comando corrente  (back_count=0, target=origin)
          2° press → va al comando precedente      (back_count=1, target=origin-1)
          3° press → va ancora indietro            (back_count=2, target=origin-2)
          …
        _back_origin è fissato al primo press; i press successivi ne sottraggono
        _back_count incrementalmente. Reset su skip, avanzamento naturale e stop.
        """
        if not (self.auto_commands_running or self._paused):
            return
        if self._back_origin == -1:
            # Primo press: memorizza la posizione corrente
            self._back_origin = self._current_abs_idx
        target = max(0, self._back_origin - self._back_count)
        self._back_count += 1
        self._log.debug(
            f"go_back: origin={self._back_origin} press={self._back_count-1} → target={target}")
        self._jump_to(target)

    def _jump_to(self, index: int):
        """
        Interrompe il timer corrente e salta a index.
        Azzera le evidenziature, ricalcola e riavvia il countdown.
        """
        if self._send_next is None:
            return
        index = max(0, min(index, self._total_commands))

        if self._auto_command_id is not None:
            self.after_cancel(self._auto_command_id)
            self._auto_command_id = None

        self._paused            = False
        self._pending_pause     = False
        self.auto_commands_running = True

        self._reset_table_highlights()
        remaining = self._remaining_seconds_from(index)
        self.total_test_duration_seconds = remaining
        self._lbl_total.config(text=_fmt(remaining))
        self._stop_countdown()
        self._start_countdown()

        self._btn_play_pause.config(text="⏸  Pausa")
        self._on_auto_status('ok', 'Auto: ON')
        self._update_nav_buttons()
        self._send_next(index)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def load_csv(self):
        if self.auto_commands_running or self._paused:
            self._log.warning(
                "Sequenza in esecuzione o in pausa. Impossibile caricare il file.")
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
        self._csv_single_cycle_seconds   = 0

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

    def _finish_async_command(self, ai, success, send_next, *,
                              fail_stops=False,
                              ok_msg="", fail_msg="", pause_msg=""):
        """Conclusione comune dei comandi asincroni (save / spindown / write_eeprom).

        Invocata sul main thread dai rispettivi resume-callback. Comportamento:
          - sequenza non più attiva          → no-op
          - fail_stops=True e success=False  → log errore + stop() (non avanza)
          - pausa pendente                   → applica la pausa
          - altrimenti                       → log esito e avanza (ai+1)

        pause_msg può essere una stringa o una funzione success->stringa (serve
        a 'save', il cui messaggio di pausa dipende dall'esito).
        """
        if not self.auto_commands_running:
            return

        if fail_stops and not success:
            self._log.error(fail_msg)
            self._current_abs_idx = ai
            self.stop()
            return

        if self._pending_pause:
            self._pending_pause        = False
            self._paused               = True
            self.auto_commands_running = False
            self._current_abs_idx      = ai
            self._pause_remaining_ms   = 0
            self._stop_countdown()
            self._btn_play_pause.config(text="▶  Riprendi")
            self._on_auto_status('warn', 'Auto: PAUSA')
            self._update_nav_buttons()
            msg = pause_msg(success) if callable(pause_msg) else pause_msg
            self._log.info(msg)
            return

        if success:
            self._log.info(ok_msg)
        else:
            self._log.warning(fail_msg)
        self._back_origin = -1
        self._back_count  = 0
        self._auto_command_id = self.after(0, lambda: send_next(ai + 1))

    def start(self):
        if self._paused:
            self.resume()
            return
        if self.auto_commands_running:
            self._log.warning("Comandi automatici già in esecuzione.")
            return
        if not self._table.get_children():
            self._log.info("La tabella dei comandi è vuota.")
            return

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

        # ── Reset stato navigazione ────────────────────────────────────────────
        self._paused             = False
        self._pending_pause      = False
        self._current_abs_idx    = 0
        self._back_origin        = -1
        self._back_count         = 0
        self._pause_remaining_ms = 0
        self._after_deadline     = 0.0

        commands       = [self._table.item(i, 'values') for i in self._table.get_children()]
        command_items  = list(self._table.get_children())
        total_commands = len(commands) * num_cycles

        # Salva riferimenti per navigazione esterna (go_back / skip_next / resume)
        self._commands       = commands
        self._command_items  = command_items
        self._total_commands = total_commands
        self._num_cycles     = num_cycles

        self._reset_table_highlights()

        # ── Closure send_next ──────────────────────────────────────────────────
        def send_next(absolute_index: int):
            self._current_abs_idx = absolute_index

            if absolute_index < total_commands and self.auto_commands_running:
                index = absolute_index % len(commands)
                _num, command_type, tempo_s, valore_rullo, banco_kmh, etichetta = commands[index]
                try:
                    wait_time = int(float(tempo_s))
                except (ValueError, TypeError):
                    wait_time = 0

                # Aggiorna evidenziatura riga
                if absolute_index > 0:
                    prev = (absolute_index - 1) % len(commands)
                    self._table.item(
                        command_items[prev],
                        tags=('evenrow' if prev % 2 == 0 else 'oddrow',))
                self._table.item(command_items[index], tags=('currentrow',))
                if self._autoscroll_table.get():
                    self._table.see(command_items[index])
                self._on_auto_status('ok', 'Auto: ON')

                # ── Comando SAVE ───────────────────────────────────────────────
                if command_type == "save" and self._on_save is not None:
                    label_str = f"'{etichetta}'" if etichetta else "(nessuna)"
                    self._log.info(
                        f"[Auto] Raccolta media {label_str} — finestra {wait_time}s...")
                    self._on_auto_status('ok', 'Auto: SAVE…')

                    def _resume_save(success: bool, _ai=absolute_index):
                        self._finish_async_command(
                            _ai, success, send_next,
                            ok_msg="[Auto] Media salvata nel file sintesi.",
                            fail_msg="[Auto] Raccolta interrotta — riga non salvata.",
                            pause_msg=lambda ok: (
                                f"[Auto] save {'OK' if ok else 'non salvato'}"
                                " — sequenza in pausa."),
                        )

                    self._on_save(wait_time, str(etichetta), _resume_save)

                # ── Comando SPINDOWN ───────────────────────────────────────────
                elif command_type == "spindown" and self._on_spindown is not None:
                    self._log.info("[Auto] Avvio calibrazione spin-down automatica...")

                    def _resume_spindown(success: bool, _ai=absolute_index):
                        self._finish_async_command(
                            _ai, success, send_next,
                            ok_msg="[Auto] Calibrazione completata — sequenza ripresa.",
                            fail_msg="[Auto] Calibrazione fallita — sequenza ripresa comunque.",
                            pause_msg="[Auto] Calibrazione terminata — sequenza in pausa.",
                        )

                    self._on_spindown(_resume_spindown)

                # ── Comando EEPROM (scrittura+verifica in memoria) ─────────────
                elif command_type == "write_eeprom" and self._on_eeprom is not None:
                    self._log.info(
                        f"[Auto] Scrittura EEPROM in memoria: {etichetta}")
                    self._on_auto_status('ok', 'Auto: EEPROM…')

                    def _resume_eeprom(success: bool, _ai=absolute_index):
                        # fail_stops=True: dopo i retry lato manager, un fallimento
                        # ferma la sequenza (lo stop ha priorità sulla pausa).
                        self._finish_async_command(
                            _ai, success, send_next,
                            fail_stops=True,
                            ok_msg="[Auto] Scrittura EEPROM verificata — sequenza ripresa.",
                            fail_msg=("[Auto] Scrittura EEPROM FALLITA dopo i retry — "
                                      "sequenza interrotta."),
                            pause_msg="[Auto] Scrittura EEPROM completata — sequenza in pausa.",
                        )

                    self._on_eeprom(str(etichetta), _resume_eeprom)

                # ── Comando ordinario con timer ────────────────────────────────
                else:
                    self._on_dispatch(command_type, valore_rullo, banco_kmh)
                    self._after_deadline = _time.monotonic() + wait_time

                    def _natural_advance(_ai=absolute_index):
                        """Avanzamento naturale: reset navigazione back, poi next."""
                        self._auto_command_id = None
                        self._back_origin     = -1
                        self._back_count      = 0
                        send_next(_ai + 1)

                    self._auto_command_id = self.after(
                        wait_time * 1000, _natural_advance)

            else:
                # ── Fine sequenza ──────────────────────────────────────────────
                self.auto_commands_running = False
                self._paused               = False
                self._pending_pause        = False
                self._back_origin          = -1
                self._back_count           = 0
                self._stop_countdown()
                self._lbl_remaining.config(text="00:00:00")
                self._on_auto_status('warn', 'Auto: OK')
                self._lbl_fine.config(
                    text=datetime.datetime.now().strftime("%H:%M:%S"),
                    fg='#005500')
                self._log.info(
                    f"Comandi automatici completati ({num_cycles} ciclo/i)")
                self._log.info(
                    "Fine sequenza — invio freno=0 e velocità banco=0 (sicurezza)")
                self._on_send_level(0)
                self._on_set_banco(0)
                self._reset_table_highlights()
                self._update_nav_buttons()
                self._btn_play_pause.config(text="▶  Start")
                self._on_auto_completed()

        # Salva riferimento alla closure per navigazione esterna
        self._send_next = send_next

        # ── Avvio ─────────────────────────────────────────────────────────────
        self.auto_commands_running = True
        self._on_auto_status('ok', 'Auto: ON')
        self._btn_play_pause.config(text="⏸  Pausa")
        self._update_nav_buttons()

        now  = datetime.datetime.now()
        self._lbl_inizio.config(text=now.strftime("%H:%M:%S"), fg='#005500')
        fine = now + datetime.timedelta(seconds=self.total_test_duration_seconds)
        self._lbl_fine.config(text=fine.strftime("%H:%M:%S") + " ~", fg='#885500')

        self.remaining_test_duration_seconds = self.total_test_duration_seconds
        self._lbl_remaining.config(text=_fmt(self.remaining_test_duration_seconds))
        self._start_countdown()
        send_next(0)

    def stop(self):
        was_active = self.auto_commands_running or self._paused
        if was_active:
            self.auto_commands_running = False
            self._paused               = False
            self._pending_pause        = False
            self._back_origin          = -1
            self._back_count           = 0
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
                    self._table.item(
                        item,
                        tags=('evenrow' if idx % 2 == 0 else 'oddrow',))
                    break
            self._update_nav_buttons()
            self._btn_play_pause.config(text="▶  Start")
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