import tkinter as tk
from tkinter import ttk
import queue
from concurrent.futures import ThreadPoolExecutor
import logging
import json
import os
import sys
import subprocess
import asyncio
import threading
import math
from collections import deque  # <-- per smoothing Δ
from shared_lib.bluetooth_manager import BLEManager
from shared_lib.LorenzLib import LorenzReader
from shared_lib.funzioni_accessorie import trova_porta_usb_serial
from shared_lib.modbus_utils import ModbusBancoCollaudo
from logic.data_processing import DataProcessor
from tkinter import filedialog
import serial.tools.list_ports
from shared_lib.SerialDataLib import SerialDataReader

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.lorenz_update_id = None
        self.periodic_check_id = None
        self.auto_command_id = None
        self.countdown_timer_id = None  # <-- Aggiunto
        self.total_test_duration_seconds = 0  # <-- Aggiunto
        self.remaining_test_duration_seconds = 0  # <-- Aggiunto
        self._shutdown_future = None
        self._shutdown_win = None

        self.title("Total Commander")
        self.geometry("1375x855")

        self.style = ttk.Style(self)

        # Stile pulsante dati ON/OFF
        self.style.configure('Data.Enabled.TButton', foreground='#008000', font=('Helvetica', 10, 'bold'))
        self.style.configure('Data.Disabled.TButton', foreground='#CC0000', font=('Helvetica', 10, 'bold'))

        # Stili compatti per la tabella CSV (ulteriore accorciamento)
        self.style.configure('Compact.Treeview', rowheight=16, font=('Helvetica', 8))
        self.style.configure('Compact.Treeview.Heading', font=('Helvetica', 8, 'bold'), padding=(3, 1))

        # Font evidenziato per i valori chiave nel pannello di confronto
        self.value_font = ('Helvetica', 12, 'bold')

        self.ble_manager = BLEManager()
        self.data_processor = DataProcessor()
        self.modbus = ModbusBancoCollaudo()
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.auto_commands_running = False
        self.lorenz_reader = LorenzReader()
        self.serial_reader = SerialDataReader(baudrate=115200)
        self.serial_update_id = None

        self.settings_file = "settings.json"

        # Soglie Δ (defaults) – sovrascritte da settings.json se presenti
        self.delta_speed_thresholds_kmh = (1.0, 3.0)  # verde <=1.0, arancione <=3.0, rosso >3.0
        self.delta_power_thresholds_pct = (2.0, 5.0)  # verde <=2%, arancione <=5%, rosso >5%
        # Finestra smoothing (default) – overridable da settings
        self.delta_smoothing_window = 5

        self._shutdown_anim_id = None
        self._shutdown_pb = None

        # --- Loop asyncio dedicato al BLE (persistente) ---
        self._ble_loop = None
        self._ble_loop_thread = None
        self._ble_loop_ready = threading.Event()
        self._init_ble_loop()

        # Carica impostazioni (incluso soglie delta e smoothing)
        self.load_settings()

        # Frame principale
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=0, sticky="nsew")

        # Layout radice
        self.grid_rowconfigure(0, weight=1)  # zona principale
        self.grid_rowconfigure(1, weight=0)  # log
        self.grid_columnconfigure(0, weight=1)

        # Layout main_frame (4 colonne principali)
        self.main_frame.grid_columnconfigure(0, weight=0)  # sinistra
        self.main_frame.grid_columnconfigure(1, weight=0)  # centro-sinistra
        self.main_frame.grid_columnconfigure(2, weight=1)  # Dati BLE
        self.main_frame.grid_columnconfigure(3, weight=1)  # Lorenz + Banco (affiancati)
        self.main_frame.grid_rowconfigure(0, weight=0)  # confronto
        self.main_frame.grid_rowconfigure(1, weight=1)  # contenuti

        # Frame sinistro per ricerca, stato connessione e comandi
        self.left_frame = ttk.Frame(self.main_frame)
        self.left_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=5, pady=(8, 8))
        self.left_frame.grid_columnconfigure(0, weight=1)

        # Ricerca/Connessione BLE
        self.frame_search = ttk.LabelFrame(self.left_frame, text="Ricerca Dispositivi BLE")
        self.frame_search.grid(row=0, column=0, sticky="nsew", padx=5, pady=(4, 4))
        self.frame_search.grid_columnconfigure(0, weight=1)

        self.device_list = tk.Listbox(self.frame_search, height=7)
        self.device_list.grid(row=0, column=0, sticky="nsew", padx=10, pady=4)
        self.btn_search = ttk.Button(self.frame_search, text="Cerca Dispositivi", command=self.search_devices)
        self.btn_search.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        self.btn_connect = ttk.Button(self.frame_search, text="Connetti", command=self.connect_device)
        self.btn_connect.grid(row=2, column=0, sticky="ew", padx=10, pady=2)
        self.btn_disconnect = ttk.Button(self.frame_search, text="Disconnetti", command=self.disconnect_device)
        self.btn_disconnect.grid(row=3, column=0, sticky="ew", padx=10, pady=3)

        # Stato connessione
        self.frame_status = ttk.LabelFrame(self.left_frame, text="Stato Connessione")
        self.frame_status.grid(row=1, column=0, sticky="ew", padx=5, pady=(2, 4))
        self.frame_status.grid_columnconfigure(0, weight=1)
        self.frame_status.grid_columnconfigure(1, weight=1)
        self.connection_status = tk.Label(self.frame_status, text="Non Connesso", fg="red")
        self.connection_status.grid(row=0, column=0, padx=5, pady=6)
        self.progress = ttk.Progressbar(self.frame_status, mode='indeterminate')
        self.progress.grid(row=0, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        # Comandi manuali
        self.frame_commands = ttk.LabelFrame(self.left_frame, text="Comandi manuali")
        self.frame_commands.grid(row=2, column=0, sticky="ew", padx=5, pady=(2, 6))
        self.create_command_controls()

        # Colonna intermedia (CSV + Auto comandi)
        self.middle_left_frame = ttk.Frame(self.main_frame)
        self.middle_left_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=5, pady=(4, 6))
        self.middle_left_frame.grid_rowconfigure(0, weight=1)
        self.middle_left_frame.grid_columnconfigure(0, weight=1)

        # Comandi da CSV (stile compatto ulteriore)
        self.automatic_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi da CSV")
        self.automatic_commands.grid(row=0, column=0, sticky="nsew", padx=5, pady=(2, 2))
        self.automatic_commands.grid_rowconfigure(0, weight=1)
        self.automatic_commands.grid_columnconfigure(0, weight=1)
        self.scrollbar = ttk.Scrollbar(self.automatic_commands, orient="vertical")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.commands_table = ttk.Treeview(
            self.automatic_commands,
            columns=("Comando", "Val", "t[s]", "Vb[km/h]"),
            show='headings',
            yscrollcommand=self.scrollbar.set,
            style='Compact.Treeview'
        )
        self.commands_table.heading("Comando", text="Comando")
        self.commands_table.heading("Val", text="Val")
        self.commands_table.heading("t[s]", text="t[s]")
        self.commands_table.heading("Vb[km/h]", text="Vb[km/h]")
        self.commands_table.column("Comando", width=95, anchor='center')
        self.commands_table.column("Val", width=70, anchor='center')
        self.commands_table.column("t[s]", width=55, anchor='center')
        self.commands_table.column("Vb[km/h]", width=85, anchor='center')
        self.commands_table.grid(row=0, column=0, sticky="nsew", padx=8, pady=4)
        self.scrollbar.config(command=self.commands_table.yview)
        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')

        # ---  Comandi automatici ---
        self.frame_auto_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi automatici")
        self.frame_auto_commands.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 4))
        self.frame_auto_commands.grid_columnconfigure(0, weight=1)
        self.frame_auto_commands.grid_columnconfigure(1, weight=1)

        self.btn_load_commands = ttk.Button(self.frame_auto_commands, text="Carica Comandi da CSV",
                                            command=self.load_commands_from_csv)
        self.btn_load_commands.grid(row=0, column=1, padx=8, pady=1, sticky='e')

        self.led_status = tk.Label(self.frame_auto_commands, text="Comandi Automatici: OFF", fg="red")
        self.led_status.grid(row=1, column=0, padx=8, pady=2, sticky="w")
        self.btn_auto_commands = ttk.Button(self.frame_auto_commands, text="Start Comandi Automatici",
                                            command=self.launch_auto_commands)
        self.btn_auto_commands.grid(row=1, column=1, padx=8, pady=1, sticky='e')

        self.btn_stop_auto_commands = ttk.Button(self.frame_auto_commands, text="Stop Comandi Automatici",
                                                 command=self.stop_auto_commands)
        self.btn_stop_auto_commands.grid(row=2, column=1, padx=8, pady=1, sticky='e')

        self.lbl_total_duration_text = ttk.Label(self.frame_auto_commands, text="Durata Totale Test:")
        self.lbl_total_duration_text.grid(row=3, column=0, padx=8, pady=(4, 2), sticky='w')
        self.lbl_total_duration_value = ttk.Label(self.frame_auto_commands, text="--:--:--",
                                                  font=('Helvetica', 10, 'bold'))
        self.lbl_total_duration_value.grid(row=3, column=1, padx=8, pady=(4, 2), sticky='w')

        self.lbl_remaining_duration_text = ttk.Label(self.frame_auto_commands, text="Tempo Rimanente:")
        self.lbl_remaining_duration_text.grid(row=4, column=0, padx=8, pady=2, sticky='w')
        self.lbl_remaining_duration_value = ttk.Label(self.frame_auto_commands, text="--:--:--",
                                                      font=('Helvetica', 10, 'bold'))
        self.lbl_remaining_duration_value.grid(row=4, column=1, padx=8, pady=2, sticky='w')

        # Nuovo wrapper per il lato destro
        self.right_wrapper = ttk.Frame(self.main_frame)
        self.right_wrapper.grid(row=0, column=2, rowspan=2, columnspan=2, sticky="nsew", padx=10, pady=5)
        self.right_wrapper.grid_rowconfigure(0, weight=0)  # Confronto fisso
        self.right_wrapper.grid_rowconfigure(1, weight=1)  # Right frame espande
        self.right_wrapper.grid_columnconfigure(0, weight=1)

        # =======================
        # PANNELLO DI CONFRONTO (in alto, largo come BLE + Lorenz + Banco)
        # =======================
        # Variabili per memorizzare gli ultimi valori BLE/Lorenz (per Δ)
        self._last_ble_speed = None
        self._last_ble_power = None
        self._last_lrz_speed = None
        self._last_lrz_power = None

        # Buffer per smoothing Δ
        win = max(1, int(self.delta_smoothing_window))
        self._delta_speed_hist = deque(maxlen=win)
        self._delta_power_hist = deque(maxlen=win)

        self._create_compare_panel()
        self.compare_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=(5, 2))

        # Lato destro: Lorenz e Banco AFFIANCATI nella stessa riga
        self.right_frame = ttk.Frame(self.right_wrapper)
        self.right_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.right_frame.grid_columnconfigure(0, weight=0)
        self.right_frame.grid_columnconfigure(1, weight=0)
        self.right_frame.grid_columnconfigure(2, weight=1)

        # Dati BLE FTMS (riga 1, colonna 2)
        self.frame_data = ttk.LabelFrame(self.right_frame, text="Dati BLE FTMS")
        self.frame_data.grid(row=0, column=0, sticky="nsew", padx=(0,5), pady=5)
        self.create_data_fields()

        # Sensore Temperatura (sotto il Banco)
        self.frame_serial = ttk.LabelFrame(self.right_frame, text="Gestione Sensore COM")
        self.frame_serial.grid(row=1, column=0, columnspan=3, sticky="new", padx=5, pady=(2, 5))

        self.serial_controls = ttk.Frame(self.frame_serial)
        self.serial_controls.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        # Combobox per selezionare COM
        ttk.Label(self.serial_controls, text="COM Port:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.com_port_combo = ttk.Combobox(self.serial_controls, values=self._get_available_com_ports(), width=15)
        self.com_port_combo.grid(row=0, column=1, padx=5, pady=5)

        self.serial_status = tk.Label(self.serial_controls, text="Temperatura: Non Connesso", fg="red")
        self.serial_status.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        self.btn_connect_serial = ttk.Button(self.serial_controls, text="Connetti", command=self.connect_serial)
        self.btn_connect_serial.grid(row=2, column=0, padx=5, pady=5)
        self.btn_disconnect_serial = ttk.Button(self.serial_controls, text="Disconnetti",
                                                command=self.disconnect_serial)
        self.btn_disconnect_serial.grid(row=2, column=1, padx=5, pady=5)

        # Etichette e entries in 2 colonne per i valori (row 3+)
        ttk.Label(self.serial_controls, text="Valore 1").grid(row=0, column=3, sticky="e", padx=5, pady=2)
        self.value1_label = ttk.Entry(self.serial_controls, width=12, state='readonly', justify='right')
        self.value1_label.grid(row=0, column=4, padx=5, pady=2)

        ttk.Label(self.serial_controls, text="Valore 2").grid(row=1, column=3, sticky="e", padx=5, pady=2)
        self.value2_label = ttk.Entry(self.serial_controls, width=12, state='readonly', justify='right')
        self.value2_label.grid(row=1, column=4, padx=5, pady=2)

        ttk.Label(self.serial_controls, text="Valore 3").grid(row=0, column=5, sticky="e", padx=5, pady=2)
        self.value3_label = ttk.Entry(self.serial_controls, width=12, state='readonly', justify='right')
        self.value3_label.grid(row=0, column=6, padx=5, pady=2)

        ttk.Label(self.serial_controls, text="Valore 4").grid(row=1, column=5, sticky="e", padx=5, pady=2)
        self.value4_label = ttk.Entry(self.serial_controls, width=12, state='readonly', justify='right')
        self.value4_label.grid(row=1, column=6, padx=5, pady=2)

        # Crea i due blocchi affiancati
        self.create_lorenz_controls()  # pos (row=0, col=0)
        self.create_banco_controls()  # pos (row=0, col=1)
        # Menu base (solo File)
        self._create_menu()

        # Aggiorna offset all'avvio
        self.offset_label.config(state='normal')
        self.offset_label.delete(0, tk.END)
        self.offset_label.insert(0, f"{self.lorenz_reader.offset:.2f}")
        self.offset_label.config(state='readonly')

        # Log
        self.autoscroll_log_var = tk.BooleanVar(value=True)
        self.frame_log = ttk.LabelFrame(self, text="Log delle Attività")
        self.frame_log.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.frame_log.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(self.frame_log, state='disabled', height=13)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.log_queue = queue.Queue()
        self._process_log_queue()
        chk_autoscroll = ttk.Checkbutton(
            self.frame_log,
            text="Auto-scroll",
            variable=self.autoscroll_log_var
        )
        chk_autoscroll.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))
        self.frame_log.grid_columnconfigure(0, weight=1)
        self.frame_log.grid_rowconfigure(0, weight=1)

        self.log_scrollbar = ttk.Scrollbar(self.frame_log, orient="vertical")
        self.log_scrollbar.grid(row=0, column=1, sticky="ns", pady=10)

        self.log_text = tk.Text(
            self.frame_log,
            state='disabled',
            height=13,
            yscrollcommand=self.log_scrollbar.set
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.log_scrollbar.config(command=self.log_text.yview)

        self.periodic_connection_check()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ------------------------------
    # Helper per entry readonly
    # ------------------------------
    def _set_ro(self, entry, text):
        entry.config(state='normal')
        entry.delete(0, tk.END)
        entry.insert(0, text)
        entry.config(state='readonly')

    # --- [NUOVA FUNZIONE] ---
    def _format_time(self, seconds):
        """Converte i secondi in una stringa formattata HH:MM:SS."""
        try:
            seconds = int(float(seconds))
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        except Exception:
            return "--:--:--"

    # ------------------------------
    # Pannello di confronto (BLE | Δ | Lorenz)
    # ------------------------------
    def _create_compare_panel(self):
        # Frame (internamente 3 colonne: BLE | Δ | Lorenz)
        self.compare_frame = ttk.LabelFrame(self.right_wrapper, text="Confronto BLE ↔ Lorenz")
        self.compare_frame.grid_columnconfigure(0, weight=1)  # BLE
        self.compare_frame.grid_columnconfigure(1, weight=0)  # Δ
        self.compare_frame.grid_columnconfigure(2, weight=1)  # Lorenz

        # --- Colonna sinistra: BLE FTMS ---
        left = ttk.Frame(self.compare_frame)
        left.grid(row=0, column=0, sticky="ew", padx=(10, 5), pady=8)
        left.grid_columnconfigure(0, weight=0)
        left.grid_columnconfigure(1, weight=1)

        ttk.Label(left, text="BLE FTMS", anchor="center").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )

        ttk.Label(left, text="Speed [km/h]", width=14, anchor="e").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        self.cmp_ble_speed = ttk.Entry(left, state='readonly', width=12, justify='right', font=self.value_font)
        self.cmp_ble_speed.grid(row=1, column=1, padx=0, pady=2, sticky="w")

        ttk.Label(left, text="Power [W]", width=14, anchor="e").grid(row=2, column=0, padx=5, pady=2, sticky="e")
        self.cmp_ble_power = ttk.Entry(left, state='readonly', width=12, justify='right', font=self.value_font)
        self.cmp_ble_power.grid(row=2, column=1, padx=0, pady=2, sticky="w")

        # --- Colonna centrale: Δ (velocità in km/h, potenza in %) ---
        center = ttk.Frame(self.compare_frame)
        center.grid(row=0, column=1, sticky="ns", padx=5, pady=8)

        # Header dinamico con finestra media
        self.cmp_delta_header = ttk.Label(
            center,
            text=f"Δ (Speed: km/h, Power: %) – media N={self.delta_smoothing_window}",
            anchor="center"
        )
        self.cmp_delta_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        # Etichette Δ: due righe (riga 1 = media con colore; riga 2 = istantaneo in grigio)
        self.cmp_delta_speed = tk.Label(center, text="—", width=16, anchor="center", fg="#666666", justify='center')
        self.cmp_delta_speed.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        self.cmp_delta_power = tk.Label(center, text="—", width=16, anchor="center", fg="#666666", justify='center')
        self.cmp_delta_power.grid(row=2, column=0, padx=2, pady=2, sticky="ew")

        # --- Colonna destra: LORENZ ---
        right = ttk.Frame(self.compare_frame)
        right.grid(row=0, column=2, sticky="ew", padx=(5, 10), pady=8)
        right.grid_columnconfigure(0, weight=0)
        right.grid_columnconfigure(1, weight=1)

        ttk.Label(right, text="Gestione Lorenz", anchor="center").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )

        ttk.Label(right, text="Speed [km/h]", width=14, anchor="e").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        self.cmp_lrz_speed = ttk.Entry(right, state='readonly', width=12, justify='right', font=self.value_font)
        self.cmp_lrz_speed.grid(row=1, column=1, padx=0, pady=2, sticky="w")

        ttk.Label(right, text="Power [W]", width=14, anchor="e").grid(row=2, column=0, padx=5, pady=2, sticky="e")
        self.cmp_lrz_power = ttk.Entry(right, state='readonly', width=12, justify='right', font=self.value_font)
        self.cmp_lrz_power.grid(row=2, column=1, padx=0, pady=2, sticky="w")

    # -------- Colori/soglie e formattazioni Δ --------
    def _color_for_speed_delta(self, abs_kmh):
        if abs_kmh is None:
            return "#666666"
        a = float(abs_kmh)
        t1, t2 = self.delta_speed_thresholds_kmh
        if a <= t1:
            return "#0A7A0A"  # verde
        elif a <= t2:
            return "#C98000"  # arancione
        else:
            return "#B00000"  # rosso

    def _color_for_power_delta(self, pct):
        if pct is None:
            return "#666666"
        a = abs(float(pct))
        t1, t2 = self.delta_power_thresholds_pct
        if a <= t1:
            return "#0A7A0A"  # verde
        elif a <= t2:
            return "#C98000"  # arancione
        else:
            return "#B00000"  # rosso

    def _fmt_speed_delta(self, diff_kmh):
        if diff_kmh is None:
            return "—"
        sign = "+" if diff_kmh >= 0 else "−"
        return f"{sign}{abs(diff_kmh):.2f} km/h"

    def _fmt_power_delta(self, pct):
        if pct is None:
            return "—"
        sign = "+" if pct >= 0 else "−"
        return f"{sign}{abs(pct):.1f}%"

    # -------- Calcolo Δ (inst) e smoothing --------
    def _compute_speed_delta_abs(self, ble_val, lrz_val):
        """Restituisce (BLE - Lorenz) in km/h; None se non computabile."""
        try:
            if ble_val is None or lrz_val is None:
                return None
            return float(ble_val) - float(lrz_val)
        except Exception:
            return None

    def _compute_power_delta_pct(self, ble_val, lrz_val):
        """Restituisce (BLE - Lorenz) / Lorenz * 100; None se non computabile/denominatore 0."""
        try:
            if ble_val is None or lrz_val is None:
                return None
            lrz = float(lrz_val)
            if lrz == 0:
                return None
            ble = float(ble_val)
            return (ble - lrz) / lrz * 100.0
        except Exception:
            return None

    def _mean_or_none(self, values_deque):
        vals = [v for v in values_deque if v is not None]
        return (sum(vals) / len(vals)) if vals else None

    def _update_compare_panel(self):
        # Δ istantanei
        d_speed_inst = self._compute_speed_delta_abs(self._last_ble_speed, self._last_lrz_speed)
        d_power_inst = self._compute_power_delta_pct(self._last_ble_power, self._last_lrz_power)

        # Aggiorna buffer smoothing (solo se disponibili)
        if d_speed_inst is not None:
            self._delta_speed_hist.append(d_speed_inst)
        if d_power_inst is not None:
            self._delta_power_hist.append(d_power_inst)

        # Δ medi (media mobile sui buffer)
        d_speed_avg = self._mean_or_none(self._delta_speed_hist)
        d_power_avg = self._mean_or_none(self._delta_power_hist)

        # Testi (media su 1 riga, instanteo tra parentesi su seconda riga)
        if d_speed_avg is not None or d_speed_inst is not None:
            smooth_txt = self._fmt_speed_delta(d_speed_avg if d_speed_avg is not None else d_speed_inst)
            inst_txt = self._fmt_speed_delta(d_speed_inst)
            txt = smooth_txt if inst_txt == "—" else f"{smooth_txt}\n({inst_txt})"
            color = self._color_for_speed_delta(abs(d_speed_avg) if d_speed_avg is not None else None)
            self.cmp_delta_speed.config(text=txt, fg=color)
        else:
            self.cmp_delta_speed.config(text="—", fg="#666666")

        if d_power_avg is not None or d_power_inst is not None:
            smooth_txt = self._fmt_power_delta(d_power_avg if d_power_avg is not None else d_power_inst)
            inst_txt = self._fmt_power_delta(d_power_inst)
            txt = smooth_txt if inst_txt == "—" else f"{smooth_txt}\n({inst_txt})"
            color = self._color_for_power_delta(d_power_avg)
            self.cmp_delta_power.config(text=txt, fg=color)
        else:
            self.cmp_delta_power.config(text="—", fg="#666666")

        # Aggiorna header con N
        self.cmp_delta_header.config(
            text=f"Δ (Speed: km/h, Power: %) – media N={self.delta_smoothing_window}"
        )

    # ------------------------------
    # Log queue
    # ------------------------------
    def _process_log_queue(self):
        """Processa i messaggi di log dalla coda in modo thread-safe."""
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.log_text.config(state='normal')
                self.log_text.insert(tk.END, record + '\n')
                self.log_text.config(state='disabled')
                if self.autoscroll_log_var.get():
                    self.log_text.yview(tk.END)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_log_queue)

    # ------------------------------
    # Loop asyncio BLE persistente
    # ------------------------------
    def _init_ble_loop(self):
        """Crea un thread dedicato con un event loop asyncio persistente per BLE."""

        def _worker():
            self._ble_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._ble_loop)
            self._ble_loop_ready.set()
            try:
                self._ble_loop.run_forever()
            finally:
                try:
                    if hasattr(self._ble_loop, "shutdown_asyncgens"):
                        self._ble_loop.run_until_complete(self._ble_loop.shutdown_asyncgens())
                except Exception:
                    pass
                self._ble_loop.close()

        self._ble_loop_thread = threading.Thread(target=_worker, name="BLE-Asyncio-Loop", daemon=True)
        self._ble_loop_thread.start()
        self._ble_loop_ready.wait()

    def _shutdown_ble_loop(self, join_timeout=3.0):
        """Ferma il loop BLE e attende il thread."""
        if self._ble_loop is not None:
            try:
                self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
            except Exception:
                pass
        if self._ble_loop_thread is not None:
            self._ble_loop_thread.join(timeout=join_timeout)

    # ------------------------------
    # Menu (solo File)
    # ------------------------------
    def _create_menu(self):
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)

        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Cartella di lavoro", command=self._open_working_directory)

    # ------------------------------
    # UI controls
    # ------------------------------
    def create_command_controls(self):
        commands = [
            ("Livello [/200]", self.send_level_command),
            ("Potenza [W]", self.send_power_command),
            ("Simulazione [%]", self.send_simulation_command)
        ]
        self.frame_commands.grid_columnconfigure(0, weight=2)
        self.frame_commands.grid_columnconfigure(1, weight=1)
        self.frame_commands.grid_columnconfigure(2, weight=1)

        for i, (label, command) in enumerate(commands):
            lbl = ttk.Label(self.frame_commands, text=label)
            lbl.grid(row=i, column=0, padx=5, sticky="ew")
            if "Livello" in label:
                entry = ttk.Spinbox(self.frame_commands, from_=0, to=200, increment=1, width=12)
                entry.set(0)
                self.livello_entry = entry
            elif "Potenza" in label:
                entry = ttk.Spinbox(self.frame_commands, from_=0, to=5000, increment=1, width=12)
                entry.set(0)
                self.potenza_entry = entry
            elif "Simulazione" in label:
                entry = ttk.Spinbox(self.frame_commands, from_=-999999, to=999999,
                                    increment=0.1, format="%.1f", width=12)
                entry.set(0.0)
                self.simulazione_entry = entry
            entry.grid(row=i, column=1, padx=5, sticky="ew")
            btn = ttk.Button(self.frame_commands, text="Invia", command=command)
            btn.grid(row=i, column=2, padx=5, sticky="ew")

    def create_data_fields(self):
        fields = ["power", "cadence", "speed", "resistance", "total_distance", "elapsed_time"]
        self.data_entries = {}
        self.data_controls = ttk.Frame(self.frame_data)
        self.data_controls.grid(row=0, column=0, sticky="ew", padx=0, pady=5)
        for i, field in enumerate(fields):
            frame = ttk.Frame(self.data_controls)
            frame.grid(row=i, column=0, sticky="e", padx=5, pady=2)
            lbl = ttk.Label(frame, text=field.capitalize(), width=14, anchor="e")
            lbl.grid(row=0, column=0, padx=5)
            entry = ttk.Entry(frame, state='readonly', justify='right', width=10)
            entry.grid(row=0, column=1, padx=0)
            self.data_entries[field.lower().replace(" ", "_")] = entry

        self.btn_toggle_data = ttk.Button(
            self.data_controls,
            text="Abilita Dati",
            command=self.toggle_data,
            style='Data.Disabled.TButton'
        )
        self.btn_toggle_data.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=5)

    # ------------------------------
    # Status check periodic
    # ------------------------------
    def periodic_connection_check(self):
        self.executor.submit(lambda: asyncio.run(self._async_check_ble_status()))
        self._check_and_update_modbus_status()
        self.periodic_check_id = self.after(1000, self.periodic_connection_check)

    async def _async_check_ble_status(self):
        try:
            is_connected = self.ble_manager.get_connection_status()
            self.after(0, self._update_ble_status_ui, is_connected, False)
        except Exception as e:
            logging.getLogger().error(f"Errore durante il controllo dello stato BLE: {e}")
            self.after(0, self._update_ble_status_ui, None, True)

    def _update_ble_status_ui(self, is_connected, error=False):
        if error:
            self.connection_status.config(text="Errore BLE", fg="orange")
        elif is_connected:
            self.connection_status.config(text="Connesso", fg="green")
        else:
            self.connection_status.config(text="Non Connesso", fg="red")

    def _check_and_update_modbus_status(self):
        if self.modbus.is_connesso():
            self.btn_connect_banco.config(text="Disconnetti")
            self.banco_status.config(text="Connesso", fg="green")
        else:
            self.btn_connect_banco.config(text="Connetti")
            self.banco_status.config(text="Non Connesso", fg="red")

    # ------------------------------
    # Ricerca/Connessione BLE
    # ------------------------------
    def search_devices(self):
        logging.getLogger().info("Richiesta ricerca dispositivi")
        self.progress.start()
        self.executor.submit(self._search_devices)

    def _search_devices(self):
        fut = asyncio.run_coroutine_threadsafe(self.ble_manager.scan_devices(timeout=5), self._ble_loop)
        try:
            devices = fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore nella scansione BLE: {e}")
            devices = {}
        self.after(0, self._populate_device_list, devices)

    def _populate_device_list(self, devices):
        self.device_list.delete(0, tk.END)
        for address, (name, rssi) in devices.items():
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
            if rssi > -50:
                try:
                    self.device_list.itemconfig(tk.END, {'bg': 'lightcoral'})
                except Exception:
                    pass
                logging.getLogger().info(f"Dispositivo trovato: {name} - {address} - RSSI: {rssi}")
        self.progress.stop()

    def connect_device(self):
        selected_device = self.device_list.get(tk.ACTIVE)
        if not selected_device:
            return
        try:
            address = selected_device.split(" - ")[1]
        except Exception:
            logging.getLogger().warning("Formato elemento lista dispositivi inatteso; impossibile estrarre address.")
            return
        self.progress.start()
        self.executor.submit(self._connect_device, address)

    def _connect_device(self, address):
        logging.getLogger().info(f"Tentativo connessione a {address}")
        fut = asyncio.run_coroutine_threadsafe(
            self.ble_manager.connect_to_device(address, connection_timeout=15.0),
            self._ble_loop
        )
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore imprevisto nella gestione della connessione BLE: {e}")
        finally:
            self.after(0, self.progress.stop)

    def disconnect_device(self):
        self.progress.start()
        logging.getLogger().info("Richiesta Disconnessione")
        self.executor.submit(self._disconnect_device)

    def _disconnect_device(self):
        ok = False
        try:
            fut = asyncio.run_coroutine_threadsafe(self.ble_manager.disconnect_device(), self._ble_loop)
            ok = fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione BLE: {e}")
        finally:
            def _ui():
                if ok:
                    self.connection_status.config(text="Non Connesso", fg="red")
                    self.progress.stop()

            self.after(0, _ui)

    # ------------------------------
    # Invio comandi BLE
    # ------------------------------
    def send_level_command(self, level=None):
        if level is None:
            level = self.livello_entry.get()
        self.executor.submit(self._send_level_command, level)

    def _send_level_command(self, level):
        try:
            level = int(float(level))
        except ValueError:
            logging.getLogger().error(f"Valore livello non valido: {level}")
            return
        logging.getLogger().info(f"Invio comando livello: {level}/200")
        fut = asyncio.run_coroutine_threadsafe(self.ble_manager.set_brake_percentage(level), self._ble_loop)
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio livello: {e}")

    def send_power_command(self, power=None):
        if power is None:
            power = self.potenza_entry.get()
        self.executor.submit(self._send_power_command, power)

    def _send_power_command(self, power):
        try:
            power = int(float(power))
        except ValueError:
            logging.getLogger().error(f"Valore potenza non valido: {power}")
            return
        logging.getLogger().info(f"Invio comando potenza: {power}W")
        fut = asyncio.run_coroutine_threadsafe(self.ble_manager.set_brake_power(int(power)), self._ble_loop)
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio potenza: {e}")

    def send_simulation_command(self, simulation=None):
        if simulation is None:
            simulation = self.simulazione_entry.get()
        self.executor.submit(self._send_simulation_command, simulation)

    def _send_simulation_command(self, simulation):
        logging.getLogger().info(f"Invio comando simulazione: {simulation}%")
        fut = asyncio.run_coroutine_threadsafe(
            self.ble_manager.set_brake_simulation(grade=int(simulation)),
            self._ble_loop
        )
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio simulazione: {e}")

    # ------------------------------
    # Dati FTMS (UI)
    # ------------------------------
    def toggle_data(self):
        if self.btn_toggle_data.cget('text') == 'Abilita Dati':
            if self.ble_manager.get_connection_status():
                self.btn_toggle_data.config(text='Disabilita Dati', style='Data.Enabled.TButton')
                logging.getLogger().info("Abilitate notifiche FTMS")
                self.executor.submit(self._enable_ftms_notifications)
            else:
                logging.getLogger().info("Nessun dispositivo connesso, abilitazione FTMS non possibile")
        else:
            self.btn_toggle_data.config(text='Abilita Dati', style='Data.Disabled.TButton')
            self._clear_data_fields_ui()
            logging.getLogger().info("Disabilitate notifiche FTMS")
            self.executor.submit(self._disable_ftms_notifications)

    def _enable_ftms_notifications(self):
        fut = asyncio.run_coroutine_threadsafe(
            self.ble_manager.enable_indoor_bike_data_notifications(self.update_data_fields),
            self._ble_loop
        )
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore abilitazione notifiche FTMS: {e}")

    def _disable_ftms_notifications(self):
        fut = asyncio.run_coroutine_threadsafe(
            self.ble_manager.disable_indoor_bike_data_notifications(),
            self._ble_loop
        )
        try:
            fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore disabilitazione notifiche FTMS: {e}")

    def update_data_fields(self, bike_data):
        # UI nel main thread
        self.after(0, self._update_data_fields_ui, bike_data)
        # Elaborazione dati (non UI)
        lorenz_data = self.lorenz_reader.get_data()
        # Aggiungi dati seriali (se connesso)
        serial_data = {}
        if self.serial_reader.connected:
            serial_data = self.serial_reader.get_data()
        else:
            logging.getLogger().warning("Sensore seriale non connesso: dati non inclusi.")
        combined_data = {**bike_data, **lorenz_data, **serial_data}
        self.data_processor.handle_bike_data(combined_data)

    def _update_data_fields_ui(self, bike_data):
        # Mappa tra chiavi di bike_data e nomi dei campi UI
        key_mapping = {
            'Cad': 'cadence',
            'ElaTime': 'elapsed_time',
            'Pwr': 'power',
            'Res': 'resistance',
            'Spd': 'speed',
            'TotDist': 'total_distance'
        }
        for data_key, value in bike_data.items():
            if value is None:
                continue
            ui_key = key_mapping.get(data_key)
            if ui_key is None:
                continue
            entry = self.data_entries.get(ui_key)
            if entry is None:
                continue
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.insert(0, str(value))
            entry.config(state='readonly')

            # Aggiorna pannello di confronto per BLE + memorizza ultimi valori
            try:
                if ui_key == 'speed' and hasattr(self, 'cmp_ble_speed'):
                    self._set_ro(self.cmp_ble_speed, str(value))
                    self._last_ble_speed = float(value)
                elif ui_key == 'power' and hasattr(self, 'cmp_ble_power'):
                    self._set_ro(self.cmp_ble_power, str(value))
                    self._last_ble_power = float(value)
            except Exception:
                pass

        # Ricalcola Δ (medie + istantanei)
        self._update_compare_panel()

    def _clear_data_fields_ui(self):
        """Pulisce tutti i campi dati nella UI."""
        logging.getLogger().debug("Pulizia campi dati UI...")
        for entry in self.data_entries.values():
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.config(state='readonly')
        # Reset BLE last values + buffer smoothing
        self._last_ble_speed = None
        self._last_ble_power = None
        self._delta_speed_hist.clear()
        self._delta_power_hist.clear()
        self._update_compare_panel()

    # ------------------------------
    # CSV / comandi automatici
    # ------------------------------
    def load_commands_from_csv(self):
        if self.auto_commands_running:
            logging.getLogger().warning("Comandi automatici in corso. Impossibile caricare il file CSV.")
            return

        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            # Resetta i timer e le etichette
            self._stop_countdown_timer()
            self.lbl_remaining_duration_value.config(text="--:--:--")
            self.lbl_total_duration_value.config(text="--:--:--")
            self.total_test_duration_seconds = 0

            # Pulisce la tabella
            for item in self.commands_table.get_children():
                self.commands_table.delete(item)

            commands = DataProcessor.read_brake_commands_from_csv(file_path)
            if not commands:
                logging.getLogger().warning("File CSV vuoto o non valido.")
                return

            total_seconds = 0
            for i, command in enumerate(commands):
                # Calcola durata totale
                try:
                    # command[2] è 't[s]'
                    wait_time = int(float(command[2]))
                    total_seconds += wait_time
                except (ValueError, TypeError, IndexError):
                    logging.getLogger().warning(f"Valore tempo non valido nel CSV: {command}")

                # Inserisce nella tabella
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                self.commands_table.insert("", "end", values=command, tags=(tag,))

            # Aggiorna la UI con la durata totale
            self.total_test_duration_seconds = total_seconds
            formatted_time = self._format_time(self.total_test_duration_seconds)
            self.lbl_total_duration_value.config(text=formatted_time)
            logging.getLogger().info(f"Caricati {len(commands)} comandi. Durata totale: {formatted_time}")

    def launch_auto_commands(self):
        if self.auto_commands_running:
            logging.getLogger().warning("Comandi automatici già in esecuzione.")
            return

        if not self.commands_table.get_children():
            logging.getLogger().info("La tabella dei comandi è vuota.")
            return

        # Assicura che la durata totale sia calcolata (se non lo è già)
        if self.total_test_duration_seconds == 0:
            logging.getLogger().warning("Ricalcolo durata test...")
            commands_list = [self.commands_table.item(item, 'values') for item in
                             self.commands_table.get_children()]
            total_seconds = 0
            for cmd in commands_list:
                try:
                    total_seconds += int(float(cmd[2]))
                except Exception:
                    pass
            self.total_test_duration_seconds = total_seconds
            self.lbl_total_duration_value.config(text=self._format_time(self.total_test_duration_seconds))

        commands = [self.commands_table.item(item, 'values') for item in self.commands_table.get_children()]
        command_items = self.commands_table.get_children()
        for index, item in enumerate(command_items):
            self.commands_table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

        def send_next_command(index):
            if index < len(commands) and self.auto_commands_running:
                command_type, value, wait_time, speed_banco = commands[index]
                wait_time = int(wait_time)

                if index > 0:
                    self.commands_table.item(command_items[index - 1],
                                             tags=('evenrow' if (index - 1) % 2 == 0 else 'oddrow',))
                self.commands_table.item(command_items[index], tags=('currentrow',))

                if command_type == "potenza":
                    self.send_power_command(value)
                elif command_type == "livelli":
                    self.send_level_command(value)
                elif command_type == "simulazione":
                    self.send_simulation_command(value)

                if speed_banco is not None and speed_banco != "None":
                    self.setspeed_modbus(float(speed_banco))
                else:
                    print("speed_banco is None or 'None'")

                self.auto_command_id = self.after(wait_time * 1000, lambda: send_next_command(index + 1))
            else:
                self.auto_commands_running = False
                self._stop_countdown_timer()  # <-- Aggiunto
                self.lbl_remaining_duration_value.config(text="00:00:00")  # <-- Aggiunto
                self.led_status.config(text="Comandi Automatici: Completati", fg="blue")
                logging.getLogger().info("Comandi automatici completati")
                self.setspeed_modbus(0)
                self.commands_table.tag_configure('oddrow', background='lightgrey')
                self.commands_table.tag_configure('evenrow', background='white')
                self.commands_table.tag_configure('currentrow', background='yellow')
                if self.btn_toggle_data.cget('text') == 'Disabilita Dati':
                    logging.getLogger().info("Comandi automatici terminati, disabilito le notifiche dati.")
                    self.toggle_data()

        self.auto_commands_running = True
        self.led_status.config(text="Comandi Automatici: ON", fg="green")

        # Avvia countdown
        self.remaining_test_duration_seconds = self.total_test_duration_seconds
        self.lbl_remaining_duration_value.config(text=self._format_time(self.remaining_test_duration_seconds))
        self._start_countdown_timer()

        send_next_command(0)

    def stop_auto_commands(self):
        if self.auto_commands_running:
            self.auto_commands_running = False
            self._stop_countdown_timer()  # <-- Aggiunto
            self.lbl_remaining_duration_value.config(text="Interrotto")  # <-- Aggiunto

            self.led_status.config(text="Comandi Automatici: OFF", fg="red")
            if hasattr(self, 'auto_command_id') and self.auto_command_id is not None:
                self.after_cancel(self.auto_command_id)
                self.auto_command_id = None
            logging.getLogger().info("Comandi automatici interrotti")
            for item in self.commands_table.get_children():
                if 'currentrow' in self.commands_table.item(item, 'tags'):
                    index = self.commands_table.index(item)
                    self.commands_table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))
                    break
        else:
            logging.getLogger().info("Non ci sono comandi automatici attivi")
            # Resetta le etichette se non è in esecuzione nulla
            self.lbl_remaining_duration_value.config(text="--:--:--")
            self.lbl_total_duration_value.config(text="--:--:--")
            self.total_test_duration_seconds = 0

    def _start_countdown_timer(self):
        """Avvia il timer per il conto alla rovescia (richiama _tick)."""
        self._stop_countdown_timer()  # Assicura che non ce ne siano altri attivi

        def _tick():
            if self.auto_commands_running and self.remaining_test_duration_seconds > 0:
                self.remaining_test_duration_seconds -= 1
                self.lbl_remaining_duration_value.config(text=self._format_time(self.remaining_test_duration_seconds))
                # Riprogramma il prossimo tick
                self.countdown_timer_id = self.after(1000, _tick)
            elif self.auto_commands_running:
                # Arrivato a zero (o negativo) ma ancora "running" (in attesa del cleanup)
                self.lbl_remaining_duration_value.config(text="00:00:00")
                self.countdown_timer_id = None
            else:
                # Stoppato da 'stop_auto_commands' o completato
                self.countdown_timer_id = None

        # Avvia il primo tick
        _tick()

    def _stop_countdown_timer(self):
        """Ferma il timer 'after' del conto alla rovescia, se attivo."""
        if self.countdown_timer_id is not None:
            self.after_cancel(self.countdown_timer_id)
            self.countdown_timer_id = None

    # --- [FINE NUOVE FUNZIONI] ---

    # ------------------------------
    # Lorenz (affiancato al Banco)
    # ------------------------------
    def create_lorenz_controls(self):
        self.frame_lorenz = ttk.LabelFrame(self.right_frame, text="Gestione Lorenz")
        # Affiancato: colonna 0
        self.frame_lorenz.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.lorenz_controls = ttk.Frame(self.frame_lorenz)
        self.lorenz_controls.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.lorenz_status = tk.Label(self.lorenz_controls, text="Lorenz: Non Connesso", fg="red")
        self.lorenz_status.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        self.btn_connect_lorenz = ttk.Button(self.lorenz_controls, text="Connetti", command=self.connect_lorenz)
        self.btn_connect_lorenz.grid(row=1, column=0, padx=5, pady=5)
        self.btn_disconnect_lorenz = ttk.Button(self.lorenz_controls, text="Disconnetti",
                                                command=self.disconnect_lorenz)
        self.btn_disconnect_lorenz.grid(row=1, column=1, padx=5, pady=5)
        self.btn_read_offset = ttk.Button(self.lorenz_controls, text="Leggi Offset", command=self.read_lorenz_offset)
        self.btn_read_offset.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        self.offset_label = self.create_labeled_entry(self.lorenz_controls, "Offset", 3)
        self.speed_avg_label = self.create_labeled_entry(self.lorenz_controls, "Speed Avg", 4)
        self.torque_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Torque Lorenz", 5)
        self.power_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Power Lorenz", 6)

        lbl_avg = ttk.Label(self.lorenz_controls, text="Media Campioni")
        lbl_avg.grid(row=7, column=0, sticky="e", padx=5, pady=2)
        self.avg_entry = ttk.Entry(self.lorenz_controls, width=15, justify='right')
        self.avg_entry.grid(row=7, column=1, padx=5, pady=2)
        self.avg_entry.insert(0, str(self.lorenz_reader.avg_dim))
        self.avg_entry.bind("<Return>", self.update_lorenz_avg)
        self.avg_entry.bind("<FocusOut>", self.update_lorenz_avg)

        self.invert_speed_var = tk.BooleanVar(value=self.lorenz_reader.invert_speed)
        chk_invert_speed = ttk.Checkbutton(
            self.lorenz_controls,
            text="Inverti Segno Velocità",
            variable=self.invert_speed_var,
            command=self.toggle_invert_speed
        )
        chk_invert_speed.grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=5)

    # ------------------------------
    # Banco (affiancato al Lorenz)
    # ------------------------------
    def create_banco_controls(self):
        self.banco_controls = ttk.LabelFrame(self.right_frame, text="Gestione Banco")
        # Affiancato: colonna 1 (stessa riga del Lorenz)
        self.banco_controls.grid(row=0, column=2, sticky="nsew", padx=(5, 0), pady=5)

        lbl_ip = ttk.Label(self.banco_controls, text="PORTA IP:")
        lbl_ip.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.entry_ip = ttk.Entry(self.banco_controls, width=12)
        self.entry_ip.insert(0, "192.168.0.10")
        self.entry_ip.grid(row=0, column=1, padx=5, pady=5)

        self.btn_connect_banco = ttk.Button(self.banco_controls, text="Connetti",
                                            command=self.toggle_modbus_connection)
        self.btn_connect_banco.grid(row=1, column=0, padx=5, pady=5)
        self.banco_status = tk.Label(self.banco_controls, text="Non Connesso", fg="red")
        self.banco_status.grid(row=1, column=1, padx=5, pady=5)

        self.btn_set_speed = ttk.Button(self.banco_controls, text="Set Velocità [km/h]:",
                                        command=self.clicked_button_setspeed_modbus)
        self.btn_set_speed.grid(row=2, column=0, padx=5, pady=5)

        self.speed_banco_spin = ttk.Spinbox(
            self.banco_controls,
            from_=0.0,
            to=100.0,
            increment=0.1,
            format="%.1f",
            width=12
        )
        self.speed_banco_spin.set(0.0)
        self.speed_banco_spin.grid(row=2, column=1, padx=5, pady=5)

        self.btn_zero_speed = ttk.Button(self.banco_controls, text="ZERO SPEED",
                                         command=lambda: self.setspeed_modbus(0))
        self.btn_zero_speed.grid(row=4, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

    def _get_available_com_ports(self):
        """Elenca le COM ports disponibili."""
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def connect_serial(self):
        com_port = self.com_port_combo.get()
        if not com_port:
            logging.getLogger().warning("Seleziona una COM port prima di connettere.")
            return
        logging.getLogger().info(f"Richiesta connessione sensore temperatura su {com_port}...")
        self.executor.submit(self._connect_serial_worker, com_port)

    def _connect_serial_worker(self, com_port):
        if self.serial_reader.open_connection(com_port):
            self.after(0, self._update_serial_ui, True)
        else:
            self.after(0, self._update_serial_ui, False)

    def _update_serial_ui(self, is_connected):
        if is_connected:
            self.serial_status.config(text="Temperatura: Connesso", fg="green")
            logging.getLogger().info("Sensore temperatura connesso")
            self.start_serial_update()
        else:
            self.serial_status.config(text="Temperatura: Non Connesso", fg="red")
            logging.getLogger().warning("Sensore temperatura non connesso o connessione fallita.")

    def start_serial_update(self):
        self.update_serial_data()
        self.serial_update_id = self.after(500, self.start_serial_update)

    def stop_serial_update(self):
        if self.serial_update_id is not None:
            self.after_cancel(self.serial_update_id)
            self.serial_update_id = None

    def update_serial_data(self):
        data = self.serial_reader.get_data()
        val1 = data.get('Valore1')
        val2 = data.get('Valore2')
        val3 = data.get('Valore3')
        val4 = data.get('Valore4')

        def format_value(val):
            if val is not None and not math.isnan(val):
                return f"{val:.2f}"
            else:
                return 'N/A'

        self._set_ro(self.value1_label, format_value(val1))
        self._set_ro(self.value2_label, format_value(val2))
        self._set_ro(self.value3_label, format_value(val3))
        self._set_ro(self.value4_label, format_value(val4))

    def disconnect_serial(self):
        if self.serial_reader.close_connection():
            self.serial_status.config(text="Temperatura: Non Connesso", fg="red")
            self.stop_serial_update()

    def create_labeled_entry(self, parent, label_text, row):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0, sticky="e", padx=5, pady=2)
        entry = ttk.Entry(parent, width=12, state='readonly', justify='right')
        entry.grid(row=row, column=1, padx=5, pady=2)
        return entry

    def update_lorenz_data(self):
        data = self.lorenz_reader.get_data()
        values = {
            self.offset_label: data.get("offset_lorenz"),
            self.speed_avg_label: data.get("speed_avg_lorenz"),
            self.torque_lorenz_label: data.get("torque_lorenz"),
            self.power_lorenz_label: data.get("power_lorenz"),
        }
        for entry, val in values.items():
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.insert(0, f"{val:.2f}" if val is not None else "N/A")
            entry.config(state='readonly')

        # Aggiorna pannello di confronto lato Lorenz + memorizza ultimi valori
        try:
            v_speed = data.get("speed_avg_lorenz")
            if v_speed is not None and hasattr(self, 'cmp_lrz_speed'):
                self._set_ro(self.cmp_lrz_speed, f"{v_speed:.2f}")
                self._last_lrz_speed = float(v_speed)
            v_power = data.get("power_lorenz")
            if v_power is not None and hasattr(self, 'cmp_lrz_power'):
                self._set_ro(self.cmp_lrz_power, f"{v_power:.2f}")
                self._last_lrz_power = float(v_power)
        except Exception:
            pass

        # Ricalcola Δ (medie + istantanei)
        self._update_compare_panel()

    def connect_lorenz(self):
        logging.getLogger().info("Richiesta connessione a Lorenz...")
        self.executor.submit(self._connect_lorenz_worker)

    def _connect_lorenz_worker(self):
        try:
            porta_com_lorenz = trova_porta_usb_serial("Lorenz USB sensor interface Port")
            if porta_com_lorenz:
                if self.lorenz_reader.open_connection(int(porta_com_lorenz.split("COM")[-1])):
                    self.after(0, self._update_lorenz_ui, True)
                else:
                    self.after(0, self._update_lorenz_ui, False)
            else:
                self.after(0, self._update_lorenz_ui, False)
        except Exception as e:
            logging.getLogger().error(f"Errore durante la connessione a Lorenz: {e}")
            self.after(0, self._update_lorenz_ui, False)

    def _update_lorenz_ui(self, is_connected):
        if is_connected:
            self.lorenz_status.config(text="Lorenz: Connesso", fg="green")
            logging.getLogger().info("Lorenz Connesso")
            self.start_lorenz_update()
        else:
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            logging.getLogger().warning("Lorenz non connesso o connessione fallita.")

    def start_lorenz_update(self):
        self.update_lorenz_data()
        self.lorenz_update_id = self.after(500, self.start_lorenz_update)

    def stop_lorenz_update(self):
        if self.lorenz_update_id is not None:
            self.after_cancel(self.lorenz_update_id)
            self.lorenz_update_id = None

    def disconnect_lorenz(self):
        if self.lorenz_reader.close_connection():
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            self.stop_lorenz_update()

    def read_lorenz_offset(self):
        self.lorenz_reader.read_offset()
        logging.getLogger().info(f"Offset letto: {self.lorenz_reader.offset}")
        self.save_settings()

    # ------------------------------
    # Modbus
    # ------------------------------
    def toggle_modbus_connection(self):
        logging.getLogger().info("Richiesta connessione/disconnessione Modbus...")
        self.btn_connect_banco.config(state='disabled')
        self.executor.submit(self._toggle_modbus_worker)

    def _toggle_modbus_worker(self):
        try:
            if not self.modbus.is_connesso():
                ip_address = self.entry_ip.get()
                self.modbus.connetti(ip_address, 502)
            else:
                self.modbus.disconnetti()
        except Exception as e:
            logging.getLogger().error(f"Errore durante l'operazione Modbus: {e}")
        finally:
            self.after(0, self._check_and_update_modbus_status)
            self.after(0, lambda: self.btn_connect_banco.config(state='normal'))

    def clicked_button_setspeed_modbus(self):
        try:
            speed_value = float(self.speed_banco_spin.get())
            self.setspeed_modbus(speed_value)
        except (ValueError, TypeError):
            logging.getLogger().error(f"Valore velocità non valido: {self.speed_banco_spin.get()}")

    def setspeed_modbus(self, speedkmh):
        logging.getLogger().info(f"Invio comando velocità banco: {speedkmh} km/h")
        self.executor.submit(self._setspeed_modbus_worker, speedkmh)

    def _setspeed_modbus_worker(self, speedkmh):
        try:
            if speedkmh is None:
                raise ValueError("La velocità non può essere None")
            if speedkmh > 80:
                raise ValueError("La velocità richiesta è superiore a 80km/h. Comando rifiutato.")
            if self.modbus.set_motor_speed(speedkmh * 10):
                logging.getLogger().info(f"Comando velocità {speedkmh} km/h inviato con successo.")
            else:
                logging.getLogger().info(f"Il comando di velocità non è andato a buon fine")
        except Exception as e:
            logging.getLogger().error(f"Errore nell'invio della velocità del banco: {e}")

    # ------------------------------
    # Settings (soglie + smoothing + lorenz)
    # ------------------------------
    def load_settings(self):
        """Carica le impostazioni da un file JSON (Lorenz + soglie delta + smoothing finestra)."""
        defaults = {'avg_dim': 20, 'invert_speed': False, 'offset': 0.0}
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                # Lorenz
                self.lorenz_reader.avg_dim = int(settings.get('avg_dim', defaults['avg_dim']))
                self.lorenz_reader.invert_speed = bool(settings.get('invert_speed', defaults['invert_speed']))
                self.lorenz_reader.offset = float(settings.get('offset', defaults['offset']))
                # Soglie delta
                sp = settings.get('delta_speed_thresholds_kmh', self.delta_speed_thresholds_kmh)
                pw = settings.get('delta_power_thresholds_pct', self.delta_power_thresholds_pct)
                if isinstance(sp, (list, tuple)) and len(sp) == 2:
                    self.delta_speed_thresholds_kmh = (float(sp[0]), float(sp[1]))
                if isinstance(pw, (list, tuple)) and len(pw) == 2:
                    self.delta_power_thresholds_pct = (float(pw[0]), float(pw[1]))
                # Finestra smoothing
                win = settings.get('delta_smoothing_window', self.delta_smoothing_window)
                try:
                    self.delta_smoothing_window = max(1, int(win))
                except Exception:
                    self.delta_smoothing_window = 5
                logging.getLogger().info(f"Impostazioni caricate da {self.settings_file}")
            else:
                # default + salva
                self.lorenz_reader.avg_dim = defaults['avg_dim']
                self.lorenz_reader.invert_speed = defaults['invert_speed']
                self.lorenz_reader.offset = defaults['offset']
                self.save_settings()
                logging.getLogger().info("File di impostazioni non trovato, uso i valori di default.")
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.getLogger().error(f"Errore nel caricare le impostazioni: {e}. Uso i valori di default.")
            self.lorenz_reader.avg_dim = defaults['avg_dim']
            self.lorenz_reader.invert_speed = defaults['invert_speed']
            self.lorenz_reader.offset = defaults['offset']

    def save_settings(self):
        """Salva le impostazioni correnti in un file JSON (Lorenz + soglie delta + smoothing)."""
        settings = {
            'avg_dim': self.lorenz_reader.avg_dim,
            'invert_speed': self.lorenz_reader.invert_speed,
            'offset': self.lorenz_reader.offset,
            'delta_speed_thresholds_kmh': list(self.delta_speed_thresholds_kmh),
            'delta_power_thresholds_pct': list(self.delta_power_thresholds_pct),
            'delta_smoothing_window': int(self.delta_smoothing_window),
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            logging.getLogger().info(f"Impostazioni salvate in {self.settings_file}")
        except IOError as e:
            logging.getLogger().error(f"Errore nel salvare le impostazioni: {e}")

    def update_lorenz_avg(self, event=None):
        try:
            new_avg = int(self.avg_entry.get())
            if new_avg > 0:
                if self.lorenz_reader.avg_dim != new_avg:
                    self.lorenz_reader.avg_dim = new_avg
                    logging.getLogger().info(f"Dimensione media Lorenz impostata a: {new_avg}")
                    self.save_settings()
            else:
                logging.getLogger().warning("La dimensione della media deve essere un intero positivo.")
                self.avg_entry.delete(0, tk.END)
                self.avg_entry.insert(0, str(self.lorenz_reader.avg_dim))
        except ValueError:
            logging.getLogger().error("Valore non valido per la media. Inserire un numero intero.")
            self.avg_entry.delete(0, tk.END)
            self.avg_entry.insert(0, str(self.lorenz_reader.avg_dim))

    def toggle_invert_speed(self):
        is_inverted = self.invert_speed_var.get()
        self.lorenz_reader.invert_speed = is_inverted
        logging.getLogger().info(f"Inversione velocità Lorenz: {'Attiva' if is_inverted else 'Disattiva'}")
        self.save_settings()

    # ------------------------------
    # Utility
    # ------------------------------
    def _get_application_path(self):
        """Restituisce il percorso della cartella dell'eseguibile o dello script."""
        if getattr(sys, 'frozen', False):
            application_path = os.path.dirname(sys.executable)
        else:
            application_path = os.path.dirname(os.path.abspath(__file__))
        return application_path

    def _open_working_directory(self):
        """Apre la cartella di lavoro nel file explorer del sistema operativo."""
        path = self._get_application_path()
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", path])
            else:  # linux
                subprocess.Popen(["xdg-open", path])
            logging.info(f"Apertura cartella di lavoro: {path}")
        except Exception as e:
            logging.error(f"Impossibile aprire la cartella di lavoro: {e}")

    # ------------------------------
    # Chiusura pulita
    # ------------------------------
    def on_closing(self):
        """
        Gestisce l'evento di chiusura della finestra in modo non bloccante e senza deadlock.
        """
        # Ferma task periodici
        if self.periodic_check_id:
            self.after_cancel(self.periodic_check_id)
            self.periodic_check_id = None
        if self.lorenz_update_id:
            self.after_cancel(self.lorenz_update_id)
            self.lorenz_update_id = None
        if self.auto_command_id:
            try:
                self.after_cancel(self.auto_command_id)
            except Exception:
                pass
            self.auto_command_id = None

        self.stop_serial_update()
        self._stop_countdown_timer()
        self.auto_commands_running = False

        # Disabilita chiusure multiple
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.title("Total Commander - Chiusura in corso...")

        # Finestra di spegnimento
        shutdown_win = tk.Toplevel(self)
        shutdown_win.title("Chiusura")

        w, h = 300, 130
        shutdown_win.withdraw()
        self.update_idletasks()

        pw, ph = self.winfo_width(), self.winfo_height()
        if pw <= 1 or ph <= 1:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
        else:
            px, py = self.winfo_rootx(), self.winfo_rooty()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        shutdown_win.geometry(f"{w}x{h}+{x}+{y}")

        status_var = tk.StringVar(value="Chiusura delle connessioni in corso...\nAttendere prego.")
        label = ttk.Label(shutdown_win, textvariable=status_var, anchor="center", justify="center")
        label.pack(expand=True, padx=20, pady=(16, 6))

        pb = ttk.Progressbar(shutdown_win, mode='indeterminate', length=220)
        pb.pack(padx=20, pady=(0, 14), fill='x')
        pb.start(12)

        dots = [' ', '. ', '.. ', '...']
        idx = 0

        def _animate_text():
            nonlocal idx
            status_var.set(f"Chiusura delle connessioni in corso{dots[idx]}\nAttendere prego.")
            idx = (idx + 1) % len(dots)
            try:
                self._shutdown_anim_id = shutdown_win.after(350, _animate_text)
            except Exception:
                self._shutdown_anim_id = None

        _animate_text()

        shutdown_win.resizable(False, False)
        shutdown_win.transient(self)
        shutdown_win.grab_set()
        shutdown_win.deiconify()
        shutdown_win.lift()
        shutdown_win.focus_force()

        self._shutdown_win = shutdown_win
        self._shutdown_pb = pb

        self._shutdown_future = self.executor.submit(self._graceful_shutdown)
        self._poll_shutdown_done()

    def _poll_shutdown_done(self):
        if self._shutdown_future and self._shutdown_future.done():
            try:
                self._shutdown_future.result()
            except Exception as e:
                logging.getLogger().error(f"Errore durante lo spegnimento: {e}")

            logging.getLogger().info("Arresto dei worker...")
            try:
                self.executor.shutdown(wait=True, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=True)
            logging.getLogger().info("Spegnimento completato.")

            if self._shutdown_win is not None and self._shutdown_win.winfo_exists():
                try:
                    if hasattr(self, "_shutdown_anim_id") and self._shutdown_anim_id:
                        try:
                            self._shutdown_win.after_cancel(self._shutdown_anim_id)
                        except Exception:
                            pass
                        self._shutdown_anim_id = None
                    if hasattr(self, "_shutdown_pb") and self._shutdown_pb is not None:
                        try:
                            self._shutdown_pb.stop()
                        except Exception:
                            pass
                        self._shutdown_pb = None
                    self._shutdown_win.destroy()
                except Exception:
                    pass
                self._shutdown_win = None
            self.destroy()
        else:
            self.after(100, self._poll_shutdown_done)

    def _graceful_shutdown(self):
        """
        Chiude in modo ordinato: Lorenz, Modbus, BLE (sul loop persistente),
        poi ferma il loop BLE e join-a il thread.
        """
        logging.getLogger().info("Avvio procedura di spegnimento controllato...")
        try:
            if self.lorenz_reader.connected:
                logging.getLogger().info("Chiusura connessione Lorenz...")
                self.lorenz_reader.close_connection()
                logging.getLogger().info("Connessione Lorenz chiusa.")

            if self.serial_reader.connected:
                logging.getLogger().info("Chiusura connessione sensore temperatura...")
                self.serial_reader.close_connection()
                logging.getLogger().info("Connessione sensore temperatura chiusa.")

            if self.modbus.is_connesso():
                logging.getLogger().info("Chiusura connessione Modbus...")
                self.modbus.disconnetti()
                logging.getLogger().info("Connessione Modbus chiusa.")

            if self.ble_manager.get_connection_status():
                logging.getLogger().info("Chiusura connessione BLE...")
                fut = asyncio.run_coroutine_threadsafe(self.ble_manager.disconnect_device(), self._ble_loop)
                try:
                    fut.result(timeout=10)
                except Exception as e:
                    logging.getLogger().error(f"Errore nella disconnessione BLE: {e}")
                logging.getLogger().info("Connessione BLE chiusa.")
        except Exception as e:
            logging.getLogger().error(f"Errore durante la disconnessione dei dispositivi: {e}")
        finally:
            self._shutdown_ble_loop(join_timeout=3.0)
            # L'executor e la UI vengono chiusi nel main thread.


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger().info("Avvio del programma...")
    app = MainWindow()
    app.mainloop()