"""
Finestra principale dell'applicazione (ex MainWindow).

`TotalCommanderApp` è ora un guscio sottile che costruisce il layout, compone i
controller (BLE, dispositivi, registrazione) e instrada i callback dei pannelli.
La logica pesante vive nei moduli `core/` e nei dialog (`gui/dialogs.py`).

Facade pubblica usata dai dialog e dai pannelli: executor, ble (run/manager/
is_ready), banco, psu, latest_data, recording, connected_device_name/address,
status_bar / live_panel / conn_bar / sidebar / csv_panel / log_panel,
delta_*_thresholds_*, rec_hz, stop_rec_on_auto_end, banco_ip, lorenz_reader,
make_dialog, set_banco_speed, save_settings / load_settings, start_recording.
"""
import logging
import os
import re
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
from tkinter import ttk, messagebox

from logic import settings_manager
from logic.data_processing import DataProcessor
from shared_lib.bluetooth_manager import CalibrationPhase
from shared_lib.LorenzLib import LorenzReader
from shared_lib.SerialDataLib import SerialDataReader
from shared_lib.GammaLib import GammaSensorReader
from shared_lib.modbus_utils import ModbusBancoCollaudo

from core.app_state import LatestData
from core.ble_controller import BleController
from core.recording import RecordingCoordinator
from core.devices import (
    LorenzController, SerialSensorController, BancoController,
    PsuController, GammaController, LORENZ_FULL_SCALE_NM,
)

from gui.panels.status_bar import StatusBar
from gui.panels.connections_bar import ConnectionsBar
from gui.panels.csv_panel import CsvPanel
from gui.panels.live_data_panel import LiveDataPanel
from gui.panels.log_panel import LogPanel
from gui.panels.sidebar import CollapsibleSidebar
from gui.dialogs import (
    open_rec_dialog, open_delta_settings, open_psu_settings,
    open_eeprom_dialog, open_device_info, open_spindown_dialog, open_help,
)

try:
    from version import VERSION
except Exception:
    VERSION = "unknown"

try:
    from version import LIB_VERSION
except Exception:
    try:
        from importlib.metadata import version as _pkg_version
        LIB_VERSION = _pkg_version("shared_lib")
    except Exception:
        LIB_VERSION = "unknown"


def is_release(version: str) -> bool:
    """True solo se la versione è un tag pulito tipo v1.0.0 (nessun commit/dirty dopo)."""
    return bool(re.fullmatch(r"v?\d+\.\d+\.\d+", version.strip()))


class TotalCommanderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._is_dev = not is_release(VERSION)
        self.title("Total Commander IV" + (f" — ⚠ DEBUG {VERSION}" if self._is_dev else ""))
        self.geometry("1000x800")

        # ── Stili ttk ────────────────────────────────────────────────────────
        self.style = ttk.Style(self)
        self.style.configure('Data.Enabled.TButton',
                             foreground='#008000', font=('Helvetica', 10, 'bold'))
        self.style.configure('Data.Disabled.TButton',
                             foreground='#CC0000', font=('Helvetica', 10, 'bold'))
        self.style.configure('Compact.Treeview', rowheight=16, font=('Helvetica', 8))
        self.style.configure('Compact.Treeview.Heading',
                             font=('Helvetica', 8, 'bold'), padding=(3, 1))

        # ── Infrastruttura condivisa ─────────────────────────────────────────
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.latest_data = LatestData()

        self.ble = BleController()
        self.ble.start()

        # ── Librerie hardware (l'app mantiene i riferimenti per lo shutdown e
        #    per le impostazioni; i controller le pilotano) ───────────────────
        self.lorenz_reader = LorenzReader(
            campioni_media=20, full_scale_nm=LORENZ_FULL_SCALE_NM,
            sample_rate_hz=1000, output_rate_hz=10.0)
        self.serial_reader = SerialDataReader(baudrate=115200)
        self.gamma_reader = GammaSensorReader()
        self.modbus = ModbusBancoCollaudo()

        # ── Impostazioni (default + override da file) ────────────────────────
        self.settings_file = "settings.json"
        self.delta_speed_thresholds_kmh = (1.0, 3.0)
        self.delta_power_thresholds_pct = (2.0, 5.0)
        self.delta_smoothing_window = 5
        self.rec_hz = 1
        self.stop_rec_on_auto_end = False
        self.banco_ip = '192.168.0.10'
        self.load_settings()

        # ── Registrazione ────────────────────────────────────────────────────
        self.recording = RecordingCoordinator(
            latest_data=self.latest_data,
            executor=self.executor,
            schedule=self.after,
            cancel=self.after_cancel,
            rec_hz_provider=lambda: self.rec_hz,
            auto_running_provider=lambda: self.csv_panel.auto_commands_running,
        )

        # ── Controller dispositivi (callback widget come lambda → differiti) ──
        self.lorenz = LorenzController(
            self.lorenz_reader, self.executor, self._ui,
            on_status=lambda s: self.status_bar.set_lorenz(s),
            on_data=self._on_lorenz_data,
            on_hz=lambda hz: self.live_panel.set_lorenz_hz(hz),
        )
        self.serial = SerialSensorController(
            self.serial_reader, self.executor, self._ui,
            on_status=lambda s: self.sidebar.set_com(s),
            on_data=self._on_serial_data,
        )
        self.banco = BancoController(
            self.modbus, self.executor, self._ui,
            on_status=lambda s: self.status_bar.set_banco(s),
        )
        self.psu_ctl = PsuController(
            self.executor, self._ui, self.after, self.after_cancel,
            on_status=lambda s: self.sidebar.set_psu(s),
            on_measure=self._on_psu_measure,
            on_clear=lambda: self.sidebar.update_psu(None, None, None),
        )
        self.gamma = GammaController(
            self.gamma_reader, self.executor, self._ui,
            on_status=lambda s: self.sidebar.set_gamma(s),
            on_data=self._on_gamma_sample,
            on_clear=lambda: self.sidebar.update_gamma(None),
        )

        # ── Stato runtime BLE / timer ────────────────────────────────────────
        self._ble_was_connected = False
        self.connected_device_name = None
        self.connected_device_address = None
        self._ftms_timestamps = deque(maxlen=10)
        self._heartbeat_reset_id = None
        self._last_packet_time = None

        self.periodic_check_id = None
        self._ui_pulse_id = None
        self._sensor_poll_id = None

        self._shutdown_win = None
        self._shutdown_anim_id = None
        self._shutdown_pb = None
        self._shutdown_future = None

        # ── Layout + pannelli ────────────────────────────────────────────────
        self.grid_rowconfigure(0, weight=0)   # banner dev (riga vuota in release)
        self.grid_rowconfigure(1, weight=1)   # contenuto principale
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        if self._is_dev:
            self._dev_banner = tk.Label(
                self,
                text=f"⚠ BUILD DI SVILUPPO — NON RILASCIATA — {VERSION}",
                bg="#cc2222", fg="white", font=("Helvetica", 9, "bold"))
            self._dev_banner.grid(row=0, column=0, columnspan=2, sticky="ew")

        main_frame = ttk.Frame(self)
        main_frame.grid(row=1, column=0, sticky="nsew")
        main_frame.grid_rowconfigure(2, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.status_bar = StatusBar(main_frame)
        self.status_bar.grid(row=0, column=0, sticky="ew")

        self.conn_bar = ConnectionsBar(
            main_frame, self.lorenz_reader,
            on_rec_start=lambda: open_rec_dialog(self),
            on_rec_stop=self._rec_stop,
            on_open_output=self._open_output_dir,
            on_ble_search=self._ble_search,
            on_ble_connect=self._ble_connect,
            on_ble_disconnect=self._ble_disconnect,
            on_lorenz_connect=self.lorenz.connect,
            on_lorenz_disconnect=self.lorenz.disconnect,
            on_lorenz_invert=self._lorenz_invert_speed,
            on_banco_connect=self._banco_connect,
            on_banco_disconnect=self.banco.disconnect,
            banco_ip=self.banco_ip,
        )
        self.conn_bar.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 2))

        content = ttk.Frame(main_frame)
        content.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 2))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)

        self.csv_panel = CsvPanel(
            content,
            on_dispatch=self._dispatch_command,
            on_set_banco_speed=self.set_banco_speed,
            on_auto_status=self.status_bar.set_auto,
            on_auto_completed=self._on_auto_commands_completed,
            on_send_level=self._send_level,
            on_send_power=self._send_power,
            on_send_simulation=self._send_simulation,
            on_emergency_stop=self._emergency_stop,
            on_before_auto_start=self._on_before_auto_start,
            stop_rec_on_auto_end=self.stop_rec_on_auto_end,
            on_stop_rec_changed=self._on_stop_rec_changed,
            on_spindown=self._run_spindown_auto,
            on_save=self._on_save,
            on_eeprom=self._on_eeprom,
        )
        self.csv_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.live_panel = LiveDataPanel(
            content,
            on_toggle_ftms=self._toggle_ftms,
            on_lorenz_read_offset=self._lorenz_read_offset,
            on_lorenz_avg_change=self._lorenz_avg_changed,
            on_smoothing_change=self._on_smoothing_window_changed,
            smoothing_window=self.delta_smoothing_window,
            lorenz_avg_dim=self.lorenz_reader.avg_dim,
            speed_thresholds=self.delta_speed_thresholds_kmh,
            power_thresholds=self.delta_power_thresholds_pct,
        )
        self.live_panel.grid(row=0, column=1, sticky="nsew")

        self.log_panel = LogPanel(main_frame)
        self.log_panel.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.log_queue = self.log_panel.log_queue

        self.sidebar = CollapsibleSidebar(
            self,
            on_serial_connect=self.serial.connect,
            on_serial_disconnect=self.serial.disconnect,
            on_psu_connect=self.psu_ctl.connect,
            on_psu_disconnect=self.psu_ctl.disconnect,
            on_psu_settings=lambda: open_psu_settings(self),
            on_gamma_connect=self.gamma.connect,
            on_gamma_disconnect=self.gamma.disconnect,
        )
        self.sidebar.grid(row=1, column=1, sticky="ns")

        # ── Avvio cicli e chiusura ───────────────────────────────────────────
        self.live_panel.set_offset(self.lorenz_reader.offset)
        self._create_menu()
        self.periodic_connection_check()
        self._ui_pulse()
        self._sensor_poll()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ═════════════════════════════════════════════════════════════════════════
    # Helper di base
    # ═════════════════════════════════════════════════════════════════════════
    def _ui(self, fn, *args):
        """Marshalla una callback sul main thread (usato dai controller)."""
        self.after(0, fn, *args)

    @property
    def psu(self):
        """Alimentatore correntemente connesso (o None)."""
        return self.psu_ctl.psu

    def make_dialog(self, title, *, resizable=False, modal=True, size=None):
        win = tk.Toplevel(self)
        win.title(title)
        win.resizable(resizable, resizable)
        win.transient(self)
        if modal:
            win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        if size:
            w, h = size
            win.geometry(f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
        else:
            ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
            win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")
        return win

    # ═════════════════════════════════════════════════════════════════════════
    # Impostazioni
    # ═════════════════════════════════════════════════════════════════════════
    def load_settings(self):
        data = settings_manager.load(self.settings_file)
        d = settings_manager.DEFAULTS

        self.lorenz_reader.avg_dim = int(data.get('avg_dim', d['avg_dim']))
        self.lorenz_reader.invert_speed = bool(data.get('invert_speed', d['invert_speed']))
        self.lorenz_reader.offset = float(data.get('offset', d['offset']))

        sp = data.get('delta_speed_thresholds_kmh', d['delta_speed_thresholds_kmh'])
        pw = data.get('delta_power_thresholds_pct', d['delta_power_thresholds_pct'])
        if isinstance(sp, (list, tuple)) and len(sp) == 2:
            self.delta_speed_thresholds_kmh = tuple(float(x) for x in sp)
        if isinstance(pw, (list, tuple)) and len(pw) == 2:
            self.delta_power_thresholds_pct = tuple(float(x) for x in pw)

        try:
            self.delta_smoothing_window = max(
                1, int(data.get('delta_smoothing_window', d['delta_smoothing_window'])))
        except Exception:
            self.delta_smoothing_window = 5

        try:
            self.rec_hz = max(1, int(data.get('rec_hz', d['rec_hz'])))
        except Exception:
            self.rec_hz = 1

        self.stop_rec_on_auto_end = bool(
            data.get('stop_rec_on_auto_end', d['stop_rec_on_auto_end']))
        self.banco_ip = str(data.get('banco_ip', d['banco_ip']))

        if not data:
            self.save_settings()

    def save_settings(self):
        settings_manager.save(self.settings_file, {
            'avg_dim': self.lorenz_reader.avg_dim,
            'invert_speed': self.lorenz_reader.invert_speed,
            'offset': self.lorenz_reader.offset,
            'delta_speed_thresholds_kmh': list(self.delta_speed_thresholds_kmh),
            'delta_power_thresholds_pct': list(self.delta_power_thresholds_pct),
            'delta_smoothing_window': int(self.delta_smoothing_window),
            'rec_hz': int(self.rec_hz),
            'stop_rec_on_auto_end': bool(self.stop_rec_on_auto_end),
            'banco_ip': (self.conn_bar.get_banco_ip()
                         if hasattr(self, 'conn_bar') else self.banco_ip),
        })

    # ═════════════════════════════════════════════════════════════════════════
    # Cicli periodici (delegano ai controller)
    # ═════════════════════════════════════════════════════════════════════════
    def periodic_connection_check(self):
        self.ble.run(self._async_check_ble())
        self.lorenz.check()
        self.serial.check()
        self.banco.check()
        self.psu_ctl.check()
        self.gamma.check()
        self.periodic_check_id = self.after(1000, self.periodic_connection_check)

    def _sensor_poll(self):
        self.lorenz.poll()
        self.serial.poll()
        self.gamma.poll()
        self._sensor_poll_id = self.after(100, self._sensor_poll)

    # ═════════════════════════════════════════════════════════════════════════
    # Callback dati dispositivi (aggiornano latest_data + widget, sul main)
    # ═════════════════════════════════════════════════════════════════════════
    def _on_lorenz_data(self, data):
        self.latest_data.update(data)
        self.live_panel.update_lorenz(data)
        self.live_panel.set_offset(self.lorenz_reader.offset)

    def _on_serial_data(self, data):
        self.latest_data.update(data)
        self.sidebar.update_serial(data)

    def _on_psu_measure(self, tensione, corrente, potenza):
        self.latest_data.update({
            'tensione_psu': tensione,
            'corrente_psu': corrente,
            'potenza_psu': potenza,
        })
        self.sidebar.update_psu(tensione, corrente, potenza)

    def _on_gamma_sample(self, sample):
        self.latest_data.update({
            'dgs_gamma': sample.dgs,
            'tpr_gamma': sample.tpr,
            'trigger_gamma': sample.trigger,
        })
        self.sidebar.update_gamma(sample)

    # ═════════════════════════════════════════════════════════════════════════
    # Banco
    # ═════════════════════════════════════════════════════════════════════════
    def set_banco_speed(self, speed_kmh):
        self.banco.set_speed(speed_kmh)

    def _banco_connect(self, ip):
        self.banco_ip = ip
        self.save_settings()
        self.banco.connect(ip)

    # ═════════════════════════════════════════════════════════════════════════
    # Registrazione (avvio/arresto; la logica dati è in RecordingCoordinator)
    # ═════════════════════════════════════════════════════════════════════════
    def start_recording(self, session_name):
        """Avvia la registrazione. Ritorna (ok, errore)."""
        try:
            self.recording.start_session(session_name)
        except Exception as e:
            return False, str(e)
        self.recording.reset_sintesi()
        fname = os.path.basename(self.recording.xlsx_filename)
        self.conn_bar.set_rec_state(True, fname)
        self.status_bar.set_rec(True)
        self.status_bar.set_rec_hz(self.rec_hz, active=True)
        self.recording.start_tick()
        logging.getLogger().info(f"Registrazione avviata: {fname}")
        return True, None

    def _rec_stop(self):
        self.executor.submit(self._rec_stop_worker)

    def _rec_stop_worker(self):
        self.recording.stop_session()
        self.after(0, self._rec_stop_ui)

    def _rec_stop_ui(self):
        self.recording.stop_tick()
        self.status_bar.set_rec(False)
        self.status_bar.set_rec_hz(self.rec_hz, active=False)
        fname = (os.path.basename(self.recording.xlsx_filename)
                 if self.recording.xlsx_filename else "—")
        self.conn_bar.set_rec_state(False, f"OK {fname}")
        logging.getLogger().info(f"Registrazione terminata: {fname}")

    def _on_save(self, tempo_s, etichetta, resume_fn):
        self.recording.collect_save(tempo_s, etichetta, resume_fn)

    def _on_eeprom(self, etichetta, resume_fn):
        """
        Scrittura+verifica EEPROM da sequenza automatica.

        `etichetta` è il payload grezzo "ADDR: B0 B1 ..." (hex). Il parsing è
        già stato validato al caricamento del file; qui riparsiamo in modo
        difensivo. Su payload invalido o BLE non pronto → resume_fn(False),
        che fa fermare la sequenza (fail → stop).

        resume_fn(success: bool) viene chiamato sul main thread al termine.
        """
        parsed = DataProcessor.parse_eeprom_payload(etichetta)
        if parsed is None:
            logging.getLogger().error(
                f"[Auto-EEPROM] Payload non valido: {etichetta!r} — sequenza interrotta.")
            resume_fn(False)
            return
        address, data = parsed

        if not self.ble.is_ready():
            logging.getLogger().warning(
                "[Auto-EEPROM] BLE non connesso: scrittura saltata — sequenza interrotta.")
            resume_fn(False)
            return

        self.executor.submit(self._on_eeprom_worker, address, data, resume_fn)

    def _on_eeprom_worker(self, address, data, resume_fn):
        """Eseguito nel thread pool: write_and_verify gestisce retry e verifica
        read-back lato manager; qui attendiamo l'esito e riportiamo al main
        thread. Il timeout esterno (40s) copre il caso peggiore dei retry
        (3 × (write+read) + backoff ≈ 30s)."""
        try:
            ok = self.ble.run(
                self.ble.manager.write_and_verify(address, data)
            ).result(timeout=40)
        except Exception as e:
            logging.getLogger().error(
                f"[Auto-EEPROM] Errore scrittura/verifica 0x{address:04X}: {e}")
            ok = False

        if ok:
            logging.getLogger().info(
                f"[Auto-EEPROM] 0x{address:04X} = {data.hex()} scritto e verificato.")
        else:
            logging.getLogger().error(
                f"[Auto-EEPROM] 0x{address:04X} = {data.hex()} FALLITO.")

        self.after(0, lambda: resume_fn(ok))

    # ═════════════════════════════════════════════════════════════════════════
    # Menu
    # ═════════════════════════════════════════════════════════════════════════
    def _create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Cartella di lavoro", command=self._open_working_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Forza salvataggio dati", command=self._menu_flush_data)
        file_menu.add_separator()
        file_menu.add_command(
            label="Apri cartella output",
            command=lambda: self._open_working_directory(
                os.path.join(self._get_application_path(), 'output')))

        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Impostazioni", menu=settings_menu)
        settings_menu.add_command(label="Parametri delta e smoothing…",
                                  command=lambda: open_delta_settings(self))

        dispositivo_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Dispositivo", menu=dispositivo_menu)
        dispositivo_menu.add_command(label="Abilita cadenza simulata…",
                                     command=lambda: open_eeprom_dialog(self))
        dispositivo_menu.add_separator()
        dispositivo_menu.add_command(label="Informazioni dispositivo…",
                                     command=lambda: open_device_info(self))
        dispositivo_menu.add_command(label="Calibrazione spin-down…",
                                     command=lambda: open_spindown_dialog(self))

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Visualizza", menu=view_menu)
        view_menu.add_command(label="Mostra/Nascondi pannello COM", command=self.sidebar.toggle)

        info_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Info", menu=info_menu)
        info_menu.add_command(label="Guida all'uso…", command=lambda: open_help(self))
        info_menu.add_separator()
        _is_dev = self._is_dev
        _ver_label = f"Versione: {VERSION}" + ("  ⚠ build di sviluppo" if _is_dev else "")
        info_menu.add_command(label=_ver_label, state="disabled")
        info_menu.add_command(label=f"Libreria: {LIB_VERSION}", state="disabled")

    # ═════════════════════════════════════════════════════════════════════════
    # Chiusura
    # ═════════════════════════════════════════════════════════════════════════
    def on_closing(self):
        if self.periodic_check_id:
            self.after_cancel(self.periodic_check_id)
            self.periodic_check_id = None
        if self._ui_pulse_id:
            self.after_cancel(self._ui_pulse_id)
            self._ui_pulse_id = None
        self.recording.stop_tick()
        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id)
            self._heartbeat_reset_id = None
        self.psu_ctl.stop_updates()
        if self._sensor_poll_id:
            self.after_cancel(self._sensor_poll_id)
            self._sensor_poll_id = None
        self.csv_panel.stop()

        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.title("Total Commander - Chiusura in corso...")

        shutdown_win = tk.Toplevel(self)
        shutdown_win.title("Chiusura")
        w, h = 300, 130
        shutdown_win.withdraw()
        self.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        if pw <= 1 or ph <= 1:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        else:
            x = self.winfo_rootx() + (pw - w) // 2
            y = self.winfo_rooty() + (ph - h) // 2
        shutdown_win.geometry(f"{w}x{h}+{x}+{y}")

        status_var = tk.StringVar(
            value="Chiusura delle connessioni in corso...\nAttendere prego.")
        ttk.Label(shutdown_win, textvariable=status_var, anchor="center",
                  justify="center").pack(expand=True, padx=20, pady=(16, 6))
        pb = ttk.Progressbar(shutdown_win, mode='indeterminate', length=220)
        pb.pack(padx=20, pady=(0, 14), fill='x')
        pb.start(12)

        dots = [' ', '. ', '.. ', '...']
        idx = [0]

        def _anim():
            status_var.set(
                f"Chiusura delle connessioni in corso{dots[idx[0]]}\nAttendere prego.")
            idx[0] = (idx[0] + 1) % len(dots)
            try:
                self._shutdown_anim_id = shutdown_win.after(350, _anim)
            except Exception:
                self._shutdown_anim_id = None

        _anim()
        shutdown_win.resizable(False, False)
        shutdown_win.transient(self)
        shutdown_win.grab_set()
        shutdown_win.deiconify()
        shutdown_win.lift()
        shutdown_win.focus_force()
        self._shutdown_win = shutdown_win
        self._shutdown_pb = pb
        self._shutdown_future = self.executor.submit(self._graceful_shutdown)
        self._poll_shutdown()

    # ═════════════════════════════════════════════════════════════════════════
    # Metodi BLE / FTMS / calibrazione / shutdown (portati da MainWindow)
    # ═════════════════════════════════════════════════════════════════════════
    def _ui_pulse(self):
        """Batte nel main thread ogni 500 ms — si ferma se la UI si congela."""
        self.status_bar.pulse_ui()
        self._ui_pulse_id = self.after(500, self._ui_pulse)

    async def _async_check_ble(self):
        try:
            connected = self.ble.is_ready()
            self.after(0, self._update_ble_status, connected, False)
        except Exception as e:
            logging.getLogger().error(f"Errore check stato BLE: {e}")
            self.after(0, self._update_ble_status, None, True)

    def _update_ble_status(self, connected, error=False):
        if error:
            self.status_bar.set_ble('warn')
        elif connected:
            self.status_bar.set_ble('ok')
            self._ble_was_connected = True
        else:
            if self._ble_was_connected:
                self._on_ble_unexpected_disconnect()
            self.status_bar.set_ble('err')
            self._ble_was_connected = False

    def _auto_enable_ftms(self):
        if self.ble.is_ready() and not self.live_panel.is_ftms_enabled():
            logging.getLogger().debug("BLE connesso — avvio abilitazione automatica FTMS.")
            self._toggle_ftms()

    def _on_ble_unexpected_disconnect(self):
        sep = "=" * 55
        logging.getLogger().warning(sep)
        logging.getLogger().warning("*** DISCONNESSIONE BLE - connessione persa ***")
        if self.connected_device_name or self.connected_device_address:
            logging.getLogger().warning(
                f"    Dispositivo: {self.connected_device_name or '?'}  [{self.connected_device_address or '?'}]")
        logging.getLogger().warning(sep)
        self.ble.manager.reset_connection_state()
        self.connected_device_name = None
        self.connected_device_address = None
        self.status_bar.set_device_info()
        self._ftms_timestamps.clear()
        if self.live_panel.is_ftms_enabled():
            self.live_panel.set_ftms_button(False)
            self.live_panel.clear_ble()
            logging.getLogger().warning("    Notifiche FTMS disabilitate automaticamente.")
        self._reset_ftms_state()

    def _ble_search(self):
        logging.getLogger().info("Ricerca dispositivi BLE...")
        self.conn_bar.set_progress(True)
        self.executor.submit(self._ble_search_worker)

    def _ble_search_worker(self):
        fut = self.ble.run(self.ble.manager.scan_devices(timeout=5))
        try:
            devices = fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore scansione BLE: {e}")
            devices = {}
        self.after(0, self.conn_bar.populate_ble_list, devices)
        self.after(0, self.conn_bar.set_progress, False)

    def _ble_connect(self):
        name, address = self.conn_bar.get_selected_ble_device()
        if not address:
            return
        self.conn_bar.set_progress(True)
        self.executor.submit(self._ble_connect_worker, address, name)

    def _ble_connect_worker(self, address, name=""):
        logging.getLogger().info(f"Connessione BLE a {name or address}...")
        fut = self.ble.run(self.ble.manager.connect_to_device(address, connection_timeout=15.0))
        try:
            if fut.result():
                self.connected_device_name    = name
                self.connected_device_address = address
                self.after(0, self.status_bar.set_device_info, name, address)
                logging.getLogger().info(f"BLE connesso: {name} [{address}]")
                # Abilita FTMS subito — connect_to_device garantisce già
                # che i servizi GATT siano pronti a questo punto
                self.after(0, self._auto_enable_ftms)
                # Device number ANT+: lettura una-tantum da EEPROM (uint16 LE @ addr 2)
                try:
                    raw = self.ble.run(self.ble.manager.read_eeprom(2, 2)).result()
                    if raw and len(raw) >= 2:
                        devnum = int.from_bytes(bytes(raw[:2]), "little")
                        self.after(0, self.status_bar.set_device_number, devnum)
                        logging.getLogger().info(f"Device number: {devnum}")
                    else:
                        self.after(0, self.status_bar.set_device_number, None)
                        logging.getLogger().warning("Device number: risposta EEPROM vuota o troppo corta.")
                except Exception as e:
                    self.after(0, self.status_bar.set_device_number, None)
                    logging.getLogger().error(f"Errore lettura device number: {e}")
            else:
                logging.getLogger().warning(f"Connessione BLE fallita: {name or address} non ha risposto.")
        except Exception as e:
            logging.getLogger().error(f"Errore connessione BLE: {e}")
        finally:
            self.after(0, self.conn_bar.set_progress, False)

    def _ble_disconnect(self):
        if not self.ble.is_ready():
            logging.getLogger().debug("Disconnessione BLE: nessun dispositivo connesso.")
            return
        self.conn_bar.set_progress(True)
        logging.getLogger().info("Disconnessione BLE in corso...")
        self.executor.submit(self._ble_disconnect_worker)

    def _ble_disconnect_worker(self):
        ok = False
        try:
            ok = self.ble.run(self.ble.manager.disconnect_device()).result()
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione BLE: {e}")
        finally:
            if ok:
                self.recording.flush()
                logging.getLogger().debug("Flush dati eseguito dopo disconnessione BLE.")
            def _ui():
                self.conn_bar.set_progress(False)
                if ok:
                    self._ble_was_connected = False
                    self.connected_device_name = None
                    self.connected_device_address = None
                    self.status_bar.set_device_info()
                    self._ftms_timestamps.clear()
                    if self.live_panel.is_ftms_enabled():
                        self.live_panel.set_ftms_button(False)
                        self.live_panel.clear_ble()
                        logging.getLogger().info("Notifiche FTMS disabilitate.")
                    self._reset_ftms_state()
                    logging.getLogger().info("BLE disconnesso.")
                else:
                    logging.getLogger().warning("Disconnessione BLE non riuscita o già disconnesso.")
            self.after(0, _ui)

    def _send_level(self, value):
        self.executor.submit(self._send_level_worker, value)

    def _send_level_worker(self, value):
        try:
            level = int(float(value))
        except ValueError:
            logging.getLogger().error(f"Valore livello non valido: {value}"); return
        logging.getLogger().debug(f"Invio livello: {level}/200")
        try:
            self.ble.run(self.ble.manager.set_brake_percentage(level)).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio livello: {e}")

    def _send_power(self, value):
        self.executor.submit(self._send_power_worker, value)

    def _send_power_worker(self, value):
        try:
            power = int(float(value))
        except ValueError:
            logging.getLogger().error(f"Valore potenza non valido: {value}"); return
        logging.getLogger().debug(f"Invio potenza: {power}W")
        try:
            self.ble.run(self.ble.manager.set_brake_power(power)).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio potenza: {e}")

    def _send_simulation(self, value):
        self.executor.submit(self._send_simulation_worker, value)

    def _send_simulation_worker(self, value):
        logging.getLogger().debug(f"Invio simulazione: {value}%")
        try:
            self.ble.run(self.ble.manager.set_brake_simulation(grade=int(float(value)))).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio simulazione: {e}")

    def _dispatch_command(self, command_type, valore_rullo, banco_kmh):
        """Smista un comando proveniente dalla sequenza automatica."""
        if command_type == "potenza":
            self._send_power(valore_rullo)
        elif command_type == "livelli":
            self._send_level(valore_rullo)
        elif command_type == "simulazione":
            self._send_simulation(valore_rullo)
        if banco_kmh is not None and str(banco_kmh) not in ('', 'None'):
            self.set_banco_speed(float(banco_kmh))

    def _on_auto_commands_completed(self):
        """Chiamato da CsvPanel al termine di tutti i cicli."""
        if self.csv_panel.stop_rec_on_auto_end and self.recording.is_recording:
            logging.getLogger().info(
                "Fine sequenza automatica — interruzione registrazione automatica.")
            self._rec_stop()

    def _on_stop_rec_changed(self, value: bool):
        """Chiamato quando l'utente toglia il checkbox Stop REC nel pannello CSV."""
        self.stop_rec_on_auto_end = value
        self.save_settings()

    def _on_before_auto_start(self) -> bool:
        """
        Chiamato da CsvPanel prima di avviare la sequenza automatica.
        Se la registrazione non è attiva mostra un popup:
          Sì      → apre il dialogo REC (bloccante), poi prosegue solo se
                    la sessione è stata effettivamente avviata.
          No      → prosegue senza registrare (l'utente è stato avvisato).
          Annulla → annulla l'avvio della sequenza.
        Restituisce True per procedere, False per annullare.
        """
        if self.recording.is_recording:
            return True

        ans = messagebox.askyesnocancel(
            "Registrazione non attiva",
            "La registrazione dati non è attiva.\n\n"
            "Sì      →  avvia la registrazione e poi la sequenza\n"
            "No      →  avvia solo la sequenza (nessun dato salvato)\n"
            "Annulla →  non avviare",
            default=messagebox.YES,
        )
        if ans is None:   # Annulla
            return False
        if ans:           # Sì → apre dialogo REC (bloccante grazie a wait_window)
            open_rec_dialog(self)
            if not self.recording.is_recording:
                return False  # utente ha chiuso senza avviare
        return True

    def _reset_ftms_state(self):
        """Cancella il timer heartbeat e spegne il LED FTMS. Da chiamare su ogni disconnessione."""
        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id)
            self._heartbeat_reset_id = None
        self._last_packet_time = None
        self.status_bar.set_ftms(None)
        self.live_panel.set_ble_hz(None)

    def _toggle_ftms(self):
        if not self.live_panel.is_ftms_enabled():
            if self.ble.is_ready():
                self.live_panel.set_ftms_button(True)
                logging.getLogger().info("Notifiche FTMS abilitate.")
                self.status_bar.set_ftms(0)
                self.executor.submit(self._enable_ftms_worker)
            else:
                logging.getLogger().debug("Nessun dispositivo connesso: FTMS non abilitabile.")
        else:
            self.live_panel.set_ftms_button(False)
            self.live_panel.clear_ble()
            logging.getLogger().info("Notifiche FTMS disabilitate.")
            self._reset_ftms_state()
            self.executor.submit(self._disable_ftms_worker)

    def _enable_ftms_worker(self):
        try:
            self.ble.run(
                self.ble.manager.enable_indoor_bike_data_notifications(self._on_ble_data)
            ).result()
        except Exception as e:
            logging.getLogger().error(f"Errore abilitazione FTMS: {e}")
            # Ripristina lo stato del pulsante: il canale non è attivo
            self.after(0, self._ftms_enable_failed)

    def _ftms_enable_failed(self):
        """Chiamato sul main thread se enable_indoor_bike_data_notifications fallisce."""
        self.live_panel.set_ftms_button(False)
        self.live_panel.clear_ble()
        self._reset_ftms_state()
        logging.getLogger().warning("Abilitazione FTMS fallita: pulsante ripristinato a 'Abilita dati'.")

    def _disable_ftms_worker(self):
        try:
            self.ble.run(self.ble.manager.disable_indoor_bike_data_notifications()).result()
            self.recording.flush()
            logging.getLogger().debug("Flush dati eseguito dopo disabilitazione FTMS.")
        except Exception as e:
            logging.getLogger().error(f"Errore disabilitazione FTMS: {e}")

    def _on_ble_data(self, bike_data: dict):
        arrival_time = time.monotonic()  # timestamp reale di arrivo
        self.latest_data.update(bike_data)
        self.after(0, self._update_ble_ui, bike_data, arrival_time)

    def _update_ble_ui(self, bike_data: dict, arrival_time: float = None):
        now = arrival_time if arrival_time is not None else time.monotonic()
        self._ftms_timestamps.append(now)

        if len(self._ftms_timestamps) >= 2:
            span = self._ftms_timestamps[-1] - self._ftms_timestamps[0]
            if span > 0:
                hz = (len(self._ftms_timestamps) - 1) / span
                self.status_bar.set_ftms(hz)
                self.live_panel.set_ble_hz(hz)

        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id)
        self._heartbeat_reset_id = self.after(2000, self._on_ftms_heartbeat_timeout)
        self.live_panel.update_ble(bike_data)

    def _on_ftms_heartbeat_timeout(self):
        """Chiamato 2 s dopo l'ultimo pacchetto FTMS: indica assenza dati."""
        self._heartbeat_reset_id = None
        self.status_bar.set_ftms(0)
        self.live_panel.set_ble_hz(None)

    def _lorenz_read_offset(self):
        self.lorenz_reader.read_offset()
        logging.getLogger().debug(f"Offset Lorenz: {self.lorenz_reader.offset:.4f}")
        self.live_panel.set_offset(self.lorenz_reader.offset)
        self.save_settings()

    def _lorenz_avg_changed(self, value_str):
        try:
            new_avg = int(value_str)
            if new_avg > 0 and self.lorenz_reader.avg_dim != new_avg:
                self.lorenz_reader.avg_dim = new_avg
                logging.getLogger().debug(f"Media Lorenz impostata a {new_avg} campioni.")
                self.save_settings()
            elif new_avg <= 0:
                logging.getLogger().warning("La dimensione della media deve essere > 0.")
                self.live_panel.set_lorenz_avg(self.lorenz_reader.avg_dim)
        except ValueError:
            logging.getLogger().error("Valore media Lorenz non valido.")
            self.live_panel.set_lorenz_avg(self.lorenz_reader.avg_dim)

    def _lorenz_invert_speed(self, inverted: bool):
        self.lorenz_reader.invert_speed = inverted
        logging.getLogger().debug(f"Inversione velocità Lorenz: {'Attiva' if inverted else 'Disattiva'}")
        self.save_settings()

    def _on_smoothing_window_changed(self, n: int):
        """Callback dallo spinbox BLE N campioni nel LiveDataPanel."""
        self.delta_smoothing_window = n
        self.save_settings()
        logging.getLogger().debug(f"Smoothing window BLE: {n} campioni")

    def _run_spindown_auto(self, resume_cb):
        """
        Esegue una calibrazione spin-down in modalità automatica (da sequenza CSV).

        Gestione banco:
          CTRL_REQ → banco a 10 km/h di avvio
          SPIN_UP  → banco a target_high + 1 km/h (se ricevuto dal rullo)
          COAST_DOWN → banco a 0 subito
          SUCCESS/FAILED → banco a 0 per sicurezza, poi chiama resume_cb

        resume_cb(success: bool) viene chiamato sul main thread al termine.
        """

        if not self.ble.is_ready():
            logging.getLogger().warning("[Auto-Calib] BLE non connesso: calibrazione saltata.")
            resume_cb(False)
            return

        banco_ok = self.banco.is_connected()
        _RAMP_START = 10.0  # km/h avvio banco
        _MARGIN_KMH = 1.0  # km/h di margine sopra la velocità target
        _done = [False]  # flag anti-doppia-chiamata resume_cb

        def _safe_resume(success: bool):
            if _done[0]:
                return
            _done[0] = True
            self.after(0, lambda: resume_cb(success))

        def _on_phase(phase: CalibrationPhase, info: dict):
            if phase == CalibrationPhase.CTRL_REQ:
                if banco_ok:
                    self.set_banco_speed(_RAMP_START)
                    logging.getLogger().info(
                        f"[Auto-Calib] Banco avviato a {_RAMP_START:.0f} km/h")

            elif phase == CalibrationPhase.SPIN_UP:
                high = info.get('target_speed_high_kmh')
                if high is not None and banco_ok:
                    target = round(high + _MARGIN_KMH, 1)
                    self.set_banco_speed(target)
                    logging.getLogger().info(
                        f"[Auto-Calib] Banco portato a {target:.1f} km/h "
                        f"(target_high={high:.1f} + {_MARGIN_KMH:.0f} km/h margine)")

            elif phase == CalibrationPhase.COAST_DOWN:
                if banco_ok:
                    self.set_banco_speed(0)
                    logging.getLogger().info("[Auto-Calib] Banco fermato (coast-down)")

            elif phase == CalibrationPhase.SUCCESS:
                logging.getLogger().info("[Auto-Calib] Calibrazione completata con successo.")
                _safe_resume(True)

            elif phase == CalibrationPhase.FAILED:
                reason = info.get('reason', '?')
                logging.getLogger().warning(f"[Auto-Calib] Calibrazione fallita: {reason}")
                if banco_ok:
                    self.set_banco_speed(0)
                    logging.getLogger().info("[Auto-Calib] Banco fermato per sicurezza.")
                _safe_resume(False)

        self.executor.submit(self._run_spindown_auto_worker, _on_phase, _safe_resume)

    def _run_spindown_auto_worker(self, on_phase_cb, safe_resume):
        """Eseguito nel thread pool: lancia la coroutine sul loop BLE e attende."""
        fut = self.ble.run(
            self.ble.manager.start_spindown_calibration(
                status_callback=on_phase_cb,
                timeout_ctrl=5.0,
                timeout_spinup_request=60.0,  # parametro mantenuto per firma
                timeout_spinup=180.0,  # 3 min per raggiungere la velocità
                timeout_coastdown=90.0,
            )
        )
        try:
            result = fut.result(timeout=400)
            # safe_resume già chiamato da _on_phase per SUCCESS/FAILED;
            # questa chiamata è una rete di sicurezza in caso di percorsi anomali.
            if result not in (CalibrationPhase.SUCCESS, CalibrationPhase.FAILED):
                safe_resume(False)
        except Exception as e:
            logging.getLogger().error(f"[Auto-Calib] Eccezione nel worker: {e}")
            safe_resume(False)

    def _emergency_stop(self):
        try:
            if self.csv_panel.auto_commands_running:
                self.csv_panel.stop()
            self.set_banco_speed(0)
            self.csv_panel.flash_stop_button()
            logging.getLogger().warning("*** EMERGENCY STOP: speed=0, auto-cmd OFF ***")
        except Exception as e:
            logging.getLogger().error(f"Errore emergency_stop: {e}")

    def _menu_flush_data(self):
        if not self.recording.is_recording:
            logging.getLogger().debug("Flush richiesto: nessuna sessione attiva.")
            return
        self.recording.flush()
        logging.getLogger().debug("Flush manuale dati eseguito.")

    def _get_application_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _open_output_dir(self):
        self._open_working_directory(
            os.path.join(self._get_application_path(), 'output'))

    def _open_working_directory(self, path=None):
        if path is None:
            path = self._get_application_path()
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            logging.error(f"Impossibile aprire la cartella: {e}")

    def _poll_shutdown(self):
        if self._shutdown_future and self._shutdown_future.done():
            try:
                self._shutdown_future.result()
            except Exception as e:
                logging.getLogger().error(f"Errore shutdown: {e}")
            try:
                self.executor.shutdown(wait=True, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=True)
            if self._shutdown_win and self._shutdown_win.winfo_exists():
                try:
                    if self._shutdown_anim_id:
                        self._shutdown_win.after_cancel(self._shutdown_anim_id)
                    if self._shutdown_pb:
                        self._shutdown_pb.stop()
                    self._shutdown_win.destroy()
                except Exception:
                    pass
            self.destroy()
        else:
            self.after(100, self._poll_shutdown)

    def _graceful_shutdown(self):
        logging.getLogger().info("Spegnimento controllato in corso...")
        try:
            # 1. Ferma la registrazione dati subito — niente più scritture
            self.recording.close()

            # 2. Disabilita notifiche FTMS prima di disconnettere BLE.
            #    Senza questo passo, disconnect_device() si blocca in attesa
            #    che Bleak chiuda il canale delle notifiche.
            if self.ble.is_ready():
                if self.ble.manager.indoor_bike_data_notifications_enabled:
                    try:
                        self.ble.run(
                            self.ble.manager.disable_indoor_bike_data_notifications()
                        ).result(timeout=5)
                        logging.getLogger().info("Notifiche FTMS disabilitate (shutdown).")
                    except Exception as e:
                        logging.getLogger().warning(
                            f"Impossibile disabilitare notifiche FTMS: {e}")

            # 3. Disconnetti BLE — ora può uscire senza bloccarsi
            if self.ble.is_ready():
                try:
                    self.ble.run(
                        self.ble.manager.disconnect_device()
                    ).result(timeout=10)
                except Exception as e:
                    logging.getLogger().error(f"Errore disconnessione BLE in shutdown: {e}")

            # 4. Chiudi gli altri dispositivi
            if self.lorenz_reader.connected:
                self.lorenz_reader.close_connection()
            if self.serial_reader.connected:
                self.serial_reader.close_connection()
            if self.gamma.is_connected():
                self.gamma_reader.close()
            if self.banco.is_connected():
                self.modbus.disconnetti()
            if self.psu is not None and self.psu.is_connected():
                try:
                    self.psu.output_off()
                    self.psu.disconnect()
                    logging.getLogger().info("PSU spento e disconnesso (shutdown).")
                except Exception as e:
                    logging.getLogger().warning(f"Errore chiusura PSU in shutdown: {e}")

        except Exception as e:
            logging.getLogger().error(f"Errore durante lo spegnimento: {e}")
        finally:
            self.ble.shutdown(join_timeout=3.0)

if __name__ == "__main__":
    app = TotalCommanderApp()
    app.mainloop()