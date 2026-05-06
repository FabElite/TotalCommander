"""
MainWindow — orchestratore principale.
Istanzia librerie, pannelli e controller; gestisce solo la logica di collegamento
tra i vari componenti (connessioni, polling, shutdown).
Tutta la UI di dettaglio vive nei rispettivi panel; le funzioni pure in logic/.
"""
import tkinter as tk
from tkinter import ttk
import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from shared_lib.bluetooth_manager import BLEManager
from shared_lib.LorenzLib import LorenzReader
from shared_lib.funzioni_accessorie import trova_porta_usb_serial
from shared_lib.modbus_utils import ModbusBancoCollaudo
from shared_lib.SerialDataLib import SerialDataReader
from shared_lib.ScpiAlimentatore import Alimentatore, SCPIError, SCPINotConnectedError
from logic.data_processing import DataProcessor
from logic import settings_manager

from gui.panels.status_bar      import StatusBar
from gui.panels.connections_bar import ConnectionsBar
from gui.panels.csv_panel       import CsvPanel
from gui.panels.live_data_panel import LiveDataPanel
from gui.panels.log_panel       import LogPanel
from gui.panels.sidebar         import CollapsibleSidebar

try:
    from version import VERSION
except ImportError:
    VERSION = "unknown"


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Total Commander  —  {VERSION}")
        self.geometry("965x754")

        # ── Stili ─────────────────────────────────────────────────────────────
        self.style = ttk.Style(self)
        self.style.configure('Data.Enabled.TButton',  foreground='#008000', font=('Helvetica', 10, 'bold'))
        self.style.configure('Data.Disabled.TButton', foreground='#CC0000', font=('Helvetica', 10, 'bold'))
        self.style.configure('Compact.Treeview',         rowheight=16, font=('Helvetica', 8))
        self.style.configure('Compact.Treeview.Heading', font=('Helvetica', 8, 'bold'), padding=(3, 1))

        # ── Librerie ──────────────────────────────────────────────────────────
        self.ble_manager    = BLEManager()
        self.data_processor = DataProcessor()
        self.modbus         = ModbusBancoCollaudo()
        self.lorenz_reader  = LorenzReader()
        self.serial_reader  = SerialDataReader(baudrate=115200)
        self.psu: Alimentatore | None = None   # creato su connect, None = mai connesso
        self.executor       = ThreadPoolExecutor(max_workers=5)

        # ── Stato connessioni (per rilevare disconnessioni inattese) ──────────
        self._ble_was_connected    = False
        self._lorenz_was_connected = False
        self._serial_was_connected = False
        self._modbus_was_connected = False
        self._psu_was_connected    = False
        self._connected_device_name    = None
        self._connected_device_address = None

        # ── Settings ──────────────────────────────────────────────────────────
        self.settings_file = "settings.json"
        self.delta_speed_thresholds_kmh = (1.0, 3.0)
        self.delta_power_thresholds_pct = (2.0, 5.0)
        self.delta_smoothing_window = 5
        self._rec_hz = 1
        self._stop_rec_on_auto_end = False
        self._load_settings()

        # ── Loop asyncio BLE persistente ──────────────────────────────────────
        self._ble_loop       = None
        self._ble_loop_thread = None
        self._ble_loop_ready  = threading.Event()
        self._init_ble_loop()

        # ── Timer ids ─────────────────────────────────────────────────────────
        self.periodic_check_id = None
        self.lorenz_update_id  = None
        self.serial_update_id  = None
        self.psu_update_id     = None
        self._heartbeat_reset_id = None
        self._last_packet_time   = None
        self._ui_pulse_id    = None
        self._rec_timer_id   = None
        self._latest_data    = {}
        self._shutdown_win    = None
        self._shutdown_anim_id = None
        self._shutdown_pb      = None

        # ── Layout root: col 0 = contenuto, col 1 = sidebar ──────────────────
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        # Frame contenitore principale (tutta la UI esistente vive qui)
        _mf = ttk.Frame(self)
        _mf.grid(row=0, column=0, sticky="nsew")
        _mf.grid_rowconfigure(0, weight=0)   # status bar
        _mf.grid_rowconfigure(1, weight=0)   # connections bar
        _mf.grid_rowconfigure(2, weight=1)   # content
        _mf.grid_rowconfigure(3, weight=0)   # log
        _mf.grid_columnconfigure(0, weight=1)

        # ── Pannelli ──────────────────────────────────────────────────────────
        self._status_bar = StatusBar(_mf)
        self._status_bar.grid(row=0, column=0, sticky="ew")

        self._conn_bar = ConnectionsBar(
            _mf, self.lorenz_reader,
            on_rec_start         = self._rec_start_dialog,
            on_rec_stop          = self._rec_stop,
            on_open_output       = self._open_output_dir,
            on_ble_search        = self._ble_search,
            on_ble_connect       = self._ble_connect,
            on_ble_disconnect    = self._ble_disconnect,
            on_lorenz_connect    = self._lorenz_connect,
            on_lorenz_disconnect = self._lorenz_disconnect,
            on_lorenz_read_offset= self._lorenz_read_offset,
            on_lorenz_avg_change = self._lorenz_avg_changed,
            on_lorenz_invert     = self._lorenz_invert_speed,
            on_banco_connect     = self._banco_connect,
            on_banco_disconnect  = self._banco_disconnect,
        )
        self._conn_bar.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 2))

        # Content area (2 colonne)
        content = ttk.Frame(_mf)
        content.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 4))
        content.grid_columnconfigure(0, weight=0)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self._csv_panel = CsvPanel(
            content,
            on_dispatch          = self._dispatch_command,
            on_set_banco_speed   = self._set_banco_speed,
            on_auto_status       = self._status_bar.set_auto,
            on_auto_completed    = self._on_auto_commands_completed,
            on_send_level        = self._send_level,
            on_send_power        = self._send_power,
            on_send_simulation   = self._send_simulation,
            on_emergency_stop    = self._emergency_stop,
            on_before_auto_start = self._on_before_auto_start,
            stop_rec_on_auto_end = self._stop_rec_on_auto_end,
            on_stop_rec_changed  = self._on_stop_rec_changed,
            on_spindown          = self._run_spindown_auto,
        )
        self._csv_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self._live_panel = LiveDataPanel(
            content,
            on_toggle_ftms   = self._toggle_ftms,
            smoothing_window = self.delta_smoothing_window,
            speed_thresholds = self.delta_speed_thresholds_kmh,
            power_thresholds = self.delta_power_thresholds_pct,
        )
        self._live_panel.grid(row=0, column=1, sticky="nsew")

        self._log_panel = LogPanel(_mf)
        self._log_panel.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.log_queue  = self._log_panel.log_queue   # esposto per main.py
        self.log_panel  = self._log_panel                   # esposto per main.py

        # ── Sidebar collassabile (destra) ─────────────────────────────────────
        self._sidebar = CollapsibleSidebar(
            self,
            on_serial_connect    = self._serial_connect,
            on_serial_disconnect = self._serial_disconnect,
            on_psu_connect       = self._psu_connect,
            on_psu_disconnect    = self._psu_disconnect,
            on_psu_settings      = self._open_psu_settings,
        )
        self._sidebar.grid(row=0, column=1, sticky="ns")

        # Aggiorna offset al primo avvio
        self._conn_bar.set_offset(self.lorenz_reader.offset)
        # Inizializza label Hz REC con la frequenza configurata (sempre visibile)
        self._status_bar.set_rec_hz(self._rec_hz)

        self._create_menu()
        self.periodic_connection_check()
        self._ui_pulse()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ── Settings ─────────────────────────────────────────────────────────────

    def _load_settings(self):
        data = settings_manager.load(self.settings_file)
        d = settings_manager.DEFAULTS
        self.lorenz_reader.avg_dim     = int(data.get('avg_dim', d['avg_dim']))
        self.lorenz_reader.invert_speed = bool(data.get('invert_speed', d['invert_speed']))
        self.lorenz_reader.offset       = float(data.get('offset', d['offset']))
        sp = data.get('delta_speed_thresholds_kmh', d['delta_speed_thresholds_kmh'])
        pw = data.get('delta_power_thresholds_pct', d['delta_power_thresholds_pct'])
        if isinstance(sp, (list, tuple)) and len(sp) == 2:
            self.delta_speed_thresholds_kmh = tuple(float(x) for x in sp)
        if isinstance(pw, (list, tuple)) and len(pw) == 2:
            self.delta_power_thresholds_pct = tuple(float(x) for x in pw)
        try:
            self.delta_smoothing_window = max(1, int(data.get('delta_smoothing_window', d['delta_smoothing_window'])))
        except Exception:
            self.delta_smoothing_window = 5
        try:
            self._rec_hz = max(1, int(data.get('rec_hz', d['rec_hz'])))
        except Exception:
            self._rec_hz = 1
        self._stop_rec_on_auto_end = bool(
            data.get('stop_rec_on_auto_end', d['stop_rec_on_auto_end']))
        if not data:
            self._save_settings()

    def _save_settings(self):
        settings_manager.save(self.settings_file, {
            'avg_dim':                    self.lorenz_reader.avg_dim,
            'invert_speed':               self.lorenz_reader.invert_speed,
            'offset':                     self.lorenz_reader.offset,
            'delta_speed_thresholds_kmh': list(self.delta_speed_thresholds_kmh),
            'delta_power_thresholds_pct': list(self.delta_power_thresholds_pct),
            'delta_smoothing_window':     int(self.delta_smoothing_window),
            'rec_hz':                     int(self._rec_hz),
            'stop_rec_on_auto_end':       bool(self._stop_rec_on_auto_end),
        })

    # ── Loop asyncio BLE ─────────────────────────────────────────────────────

    def _init_ble_loop(self):
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
        if self._ble_loop is not None:
            try:
                self._ble_loop.call_soon_threadsafe(self._ble_loop.stop)
            except Exception:
                pass
        if self._ble_loop_thread is not None:
            self._ble_loop_thread.join(timeout=join_timeout)

    def _run_ble(self, coro):
        """Esegue una coroutine BLE sul loop dedicato e restituisce il Future."""
        return asyncio.run_coroutine_threadsafe(coro, self._ble_loop)

    # ── Polling stato connessioni ─────────────────────────────────────────────

    def _ui_pulse(self):
        """Batte nel main thread ogni 500 ms — si ferma se la UI si congela."""
        self._status_bar.pulse_ui()
        self._ui_pulse_id = self.after(500, self._ui_pulse)

    def periodic_connection_check(self):
        self._run_ble(self._async_check_ble())
        self._check_lorenz()
        self._check_serial()
        self._check_modbus()
        self._check_psu()
        self.periodic_check_id = self.after(1000, self.periodic_connection_check)

    async def _async_check_ble(self):
        try:
            connected = self.ble_manager.get_connection_status()
            self.after(0, self._update_ble_status, connected, False)
        except Exception as e:
            logging.getLogger().error(f"Errore check stato BLE: {e}")
            self.after(0, self._update_ble_status, None, True)

    def _update_ble_status(self, connected, error=False):
        if error:
            self._status_bar.set_ble('warn')
        elif connected:
            self._status_bar.set_ble('ok')
            self._ble_was_connected = True
        else:
            if self._ble_was_connected:
                self._on_ble_unexpected_disconnect()
            self._status_bar.set_ble('err')
            self._ble_was_connected = False

    def _auto_enable_ftms(self):
        if self.ble_manager.get_connection_status() and not self._live_panel.is_ftms_enabled():
            logging.getLogger().debug("BLE connesso — avvio abilitazione automatica FTMS.")
            self._toggle_ftms()

    def _on_ble_unexpected_disconnect(self):
        sep = "=" * 55
        logging.getLogger().warning(sep)
        logging.getLogger().warning("*** DISCONNESSIONE BLE - connessione persa ***")
        if self._connected_device_name or self._connected_device_address:
            logging.getLogger().warning(
                f"    Dispositivo: {self._connected_device_name or '?'}  [{self._connected_device_address or '?'}]")
        logging.getLogger().warning(sep)
        self.ble_manager.reset_connection_state()
        self._connected_device_name = None
        self._connected_device_address = None
        self._status_bar.set_device_info()
        if self._live_panel.is_ftms_enabled():
            self._live_panel.set_ftms_button(False)
            self._live_panel.clear_ble()
            logging.getLogger().warning("    Notifiche FTMS disabilitate automaticamente.")
        self._reset_ftms_state()

    def _check_lorenz(self):
        connected = self.lorenz_reader.connected
        self._status_bar.set_lorenz('ok' if connected else 'err')
        if connected:
            self._lorenz_was_connected = True
        elif self._lorenz_was_connected:
            logging.getLogger().warning("=" * 55)
            logging.getLogger().warning("*** DISCONNESSIONE LORENZ - connessione persa ***")
            logging.getLogger().warning("=" * 55)
            self._stop_lorenz_update()
            self._lorenz_was_connected = False

    def _check_serial(self):
        connected = self.serial_reader.connected
        self._sidebar.set_com('ok' if connected else 'err')
        if connected:
            self._serial_was_connected = True
        elif self._serial_was_connected:
            logging.getLogger().warning("=" * 55)
            logging.getLogger().warning("*** DISCONNESSIONE SENSORE SERIALE - connessione persa ***")
            logging.getLogger().warning("=" * 55)
            self._stop_serial_update()
            self._serial_was_connected = False

    def _check_modbus(self, from_user_action=False):
        connected = self.modbus.is_connesso()
        self._status_bar.set_banco('ok' if connected else 'err')
        if connected:
            if not self._modbus_was_connected:
                logging.getLogger().debug("Modbus: connessione attiva (check periodico).")
            self._modbus_was_connected = True
        else:
            if self._modbus_was_connected:
                logging.getLogger().warning("=" * 55)
                logging.getLogger().warning("*** DISCONNESSIONE MODBUS - connessione persa ***")
                logging.getLogger().warning("=" * 55)
            elif from_user_action:
                logging.getLogger().debug("Modbus: nessuna connessione attiva da chiudere.")
            self._modbus_was_connected = False

    # ── BLE: scan / connect / disconnect ─────────────────────────────────────

    def _ble_search(self):
        logging.getLogger().info("Ricerca dispositivi BLE...")
        self._conn_bar.set_progress(True)
        self.executor.submit(self._ble_search_worker)

    def _ble_search_worker(self):
        fut = self._run_ble(self.ble_manager.scan_devices(timeout=5))
        try:
            devices = fut.result()
        except Exception as e:
            logging.getLogger().error(f"Errore scansione BLE: {e}")
            devices = {}
        self.after(0, self._conn_bar.populate_ble_list, devices)
        self.after(0, self._conn_bar.set_progress, False)

    def _ble_connect(self):
        name, address = self._conn_bar.get_selected_ble_device()
        if not address:
            return
        self._conn_bar.set_progress(True)
        self.executor.submit(self._ble_connect_worker, address, name)

    def _ble_connect_worker(self, address, name=""):
        logging.getLogger().info(f"Connessione BLE a {name or address}...")
        fut = self._run_ble(self.ble_manager.connect_to_device(address, connection_timeout=15.0))
        try:
            if fut.result():
                self._connected_device_name    = name
                self._connected_device_address = address
                self.after(0, self._status_bar.set_device_info, name, address)
                logging.getLogger().info(f"BLE connesso: {name} [{address}]")
                # Abilita FTMS subito — connect_to_device garantisce già
                # che i servizi GATT siano pronti a questo punto
                self.after(0, self._auto_enable_ftms)
            else:
                logging.getLogger().warning(f"Connessione BLE fallita: {name or address} non ha risposto.")
        except Exception as e:
            logging.getLogger().error(f"Errore connessione BLE: {e}")
        finally:
            self.after(0, self._conn_bar.set_progress, False)

    def _ble_disconnect(self):
        if not self.ble_manager.get_connection_status():
            logging.getLogger().debug("Disconnessione BLE: nessun dispositivo connesso.")
            return
        self._conn_bar.set_progress(True)
        logging.getLogger().info("Disconnessione BLE in corso...")
        self.executor.submit(self._ble_disconnect_worker)

    def _ble_disconnect_worker(self):
        ok = False
        try:
            ok = self._run_ble(self.ble_manager.disconnect_device()).result()
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione BLE: {e}")
        finally:
            if ok:
                self.data_processor.flush()
                logging.getLogger().debug("Flush dati eseguito dopo disconnessione BLE.")
            def _ui():
                self._conn_bar.set_progress(False)
                if ok:
                    self._ble_was_connected = False
                    self._connected_device_name = None
                    self._connected_device_address = None
                    self._status_bar.set_device_info()
                    if self._live_panel.is_ftms_enabled():
                        self._live_panel.set_ftms_button(False)
                        self._live_panel.clear_ble()
                        logging.getLogger().info("Notifiche FTMS disabilitate.")
                    self._reset_ftms_state()
                    logging.getLogger().info("BLE disconnesso.")
                else:
                    logging.getLogger().warning("Disconnessione BLE non riuscita o già disconnesso.")
            self.after(0, _ui)

    # ── BLE: comandi frenata ─────────────────────────────────────────────────

    def _send_level(self, value):
        self.executor.submit(self._send_level_worker, value)

    def _send_level_worker(self, value):
        try:
            level = int(float(value))
        except ValueError:
            logging.getLogger().error(f"Valore livello non valido: {value}"); return
        logging.getLogger().debug(f"Invio livello: {level}/200")
        try:
            self._run_ble(self.ble_manager.set_brake_percentage(level)).result()
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
            self._run_ble(self.ble_manager.set_brake_power(power)).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio potenza: {e}")

    def _send_simulation(self, value):
        self.executor.submit(self._send_simulation_worker, value)

    def _send_simulation_worker(self, value):
        logging.getLogger().debug(f"Invio simulazione: {value}%")
        try:
            self._run_ble(self.ble_manager.set_brake_simulation(grade=int(float(value)))).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio simulazione: {e}")

    # ── Dispatch comandi automatici ───────────────────────────────────────────

    def _dispatch_command(self, command_type, value, speed_banco):
        """Smista un comando proveniente dalla sequenza automatica."""
        if command_type == "potenza":
            self._send_power(value)
        elif command_type == "livelli":
            self._send_level(value)
        elif command_type == "simulazione":
            self._send_simulation(value)
        if speed_banco is not None and speed_banco != "None":
            self._set_banco_speed(float(speed_banco))

    def _on_auto_commands_completed(self):
        """Chiamato da CsvPanel al termine di tutti i cicli."""
        if self._csv_panel.stop_rec_on_auto_end and self.data_processor.is_recording:
            logging.getLogger().info(
                "Fine sequenza automatica — interruzione registrazione automatica.")
            self._rec_stop()

    def _on_stop_rec_changed(self, value: bool):
        """Chiamato quando l'utente toglia il checkbox Stop REC nel pannello CSV."""
        self._stop_rec_on_auto_end = value
        self._save_settings()

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
        if self.data_processor.is_recording:
            return True

        from tkinter import messagebox
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
            self._rec_start_dialog()
            if not self.data_processor.is_recording:
                return False  # utente ha chiuso senza avviare
        return True

    # ── FTMS notifications ────────────────────────────────────────────────────

    def _reset_ftms_state(self):
        """Cancella il timer heartbeat e spegne il LED FTMS. Da chiamare su ogni disconnessione."""
        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id)
            self._heartbeat_reset_id = None
        self._last_packet_time = None
        self._status_bar.set_ftms(None)

    def _toggle_ftms(self):
        if not self._live_panel.is_ftms_enabled():
            if self.ble_manager.get_connection_status():
                self._live_panel.set_ftms_button(True)
                logging.getLogger().info("Notifiche FTMS abilitate.")
                self._status_bar.set_ftms(0)
                self.executor.submit(self._enable_ftms_worker)
            else:
                logging.getLogger().debug("Nessun dispositivo connesso: FTMS non abilitabile.")
        else:
            self._live_panel.set_ftms_button(False)
            self._live_panel.clear_ble()
            logging.getLogger().info("Notifiche FTMS disabilitate.")
            self._reset_ftms_state()
            self.executor.submit(self._disable_ftms_worker)

    def _enable_ftms_worker(self):
        try:
            self._run_ble(
                self.ble_manager.enable_indoor_bike_data_notifications(self._on_ble_data)
            ).result()
        except Exception as e:
            logging.getLogger().error(f"Errore abilitazione FTMS: {e}")
            # Ripristina lo stato del pulsante: il canale non è attivo
            self.after(0, self._ftms_enable_failed)

    def _ftms_enable_failed(self):
        """Chiamato sul main thread se enable_indoor_bike_data_notifications fallisce."""
        self._live_panel.set_ftms_button(False)
        self._live_panel.clear_ble()
        self._reset_ftms_state()
        logging.getLogger().warning("Abilitazione FTMS fallita: pulsante ripristinato a 'Abilita dati'.")

    def _disable_ftms_worker(self):
        try:
            self._run_ble(self.ble_manager.disable_indoor_bike_data_notifications()).result()
            self.data_processor.flush()
            logging.getLogger().debug("Flush dati eseguito dopo disabilitazione FTMS.")
        except Exception as e:
            logging.getLogger().error(f"Errore disabilitazione FTMS: {e}")

    def _on_ble_data(self, bike_data: dict):
        """Callback invocata dal loop BLE ad ogni pacchetto FTMS."""
        self._latest_data.update(bike_data)
        self.after(0, self._update_ble_ui, bike_data)

    def _update_ble_ui(self, bike_data: dict):
        # Heartbeat
        now = time.monotonic()
        if self._last_packet_time is not None:
            dt = now - self._last_packet_time
            if dt > 0:
                self._status_bar.set_ftms(1.0 / dt)
        self._last_packet_time = now
        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id)
        self._heartbeat_reset_id = self.after(2000, lambda: self._status_bar.set_ftms(0))

        # Aggiorna live panel e ottieni speed/power per ComparePanel
        self._live_panel.update_ble(bike_data)


    # ── Lorenz ────────────────────────────────────────────────────────────────

    def _lorenz_connect(self):
        logging.getLogger().info("Connessione Lorenz in corso...")
        self.executor.submit(self._lorenz_connect_worker)

    def _lorenz_connect_worker(self):
        try:
            import re
            port = trova_porta_usb_serial("Lorenz USB sensor interface Port")
            if port:
                match = re.search(r'(\d+)$', port)
                if not match:
                    raise ValueError(f"Impossibile estrarre il numero di porta da: {port!r}")
                ok = self.lorenz_reader.open_connection(int(match.group(1)))
                self.after(0, self._on_lorenz_connect_result, ok)
            else:
                self.after(0, self._on_lorenz_connect_result, False)
        except Exception as e:
            logging.getLogger().error(f"Errore connessione Lorenz: {e}")
            self.after(0, self._on_lorenz_connect_result, False)

    def _on_lorenz_connect_result(self, ok):
        if ok:
            logging.getLogger().info("Lorenz connesso")
            self._start_lorenz_update()
        else:
            logging.getLogger().warning("Lorenz non connesso.")

    def _start_lorenz_update(self):
        self._stop_lorenz_update()
        self._lorenz_update_tick()

    def _lorenz_update_tick(self):
        data = self.lorenz_reader.get_data()
        self._latest_data.update(data)
        self._live_panel.update_lorenz(data)
        self._conn_bar.set_offset(self.lorenz_reader.offset)
        self.lorenz_update_id = self.after(500, self._lorenz_update_tick)

    def _stop_lorenz_update(self):
        if self.lorenz_update_id is not None:
            self.after_cancel(self.lorenz_update_id)
            self.lorenz_update_id = None

    def _lorenz_disconnect(self):
        logging.getLogger().info("Disconnessione Lorenz in corso...")
        self._lorenz_was_connected = False
        self._stop_lorenz_update()
        self.executor.submit(self._lorenz_disconnect_worker)

    def _lorenz_disconnect_worker(self):
        ok = self.lorenz_reader.close_connection()
        msg = "Lorenz disconnesso." if ok else "Lorenz: nessuna connessione attiva."
        self.after(0, logging.getLogger().info if ok else logging.getLogger().warning, msg)

    def _lorenz_read_offset(self):
        self.lorenz_reader.read_offset()
        logging.getLogger().debug(f"Offset Lorenz: {self.lorenz_reader.offset:.4f}")
        self._conn_bar.set_offset(self.lorenz_reader.offset)
        self._save_settings()

    def _lorenz_avg_changed(self, value_str):
        try:
            new_avg = int(value_str)
            if new_avg > 0 and self.lorenz_reader.avg_dim != new_avg:
                self.lorenz_reader.avg_dim = new_avg
                logging.getLogger().debug(f"Media Lorenz impostata a {new_avg} campioni.")
                self._conn_bar.set_avg(new_avg)
                self._save_settings()
            elif new_avg <= 0:
                logging.getLogger().warning("La dimensione della media deve essere > 0.")
                self._conn_bar.set_avg(self.lorenz_reader.avg_dim)
        except ValueError:
            logging.getLogger().error("Valore media non valido.")
            self._conn_bar.set_avg(self.lorenz_reader.avg_dim)

    def _lorenz_invert_speed(self, inverted: bool):
        self.lorenz_reader.invert_speed = inverted
        logging.getLogger().debug(f"Inversione velocità Lorenz: {'Attiva' if inverted else 'Disattiva'}")
        self._save_settings()

    # ── Modbus / Banco ────────────────────────────────────────────────────────

    def _banco_connect(self, ip: str):
        logging.getLogger().info(f"Connessione Banco a {ip}...")
        self.executor.submit(self._banco_connect_worker, ip)

    def _banco_connect_worker(self, ip):
        try:
            self.modbus.connetti(ip, 502)
            if self.modbus.is_connesso():
                logging.getLogger().info(f"Banco connesso: {ip}")
            else:
                logging.getLogger().warning(f"Connessione Banco fallita: {ip} non raggiungibile.")
        except Exception as e:
            logging.getLogger().error(f"Errore connessione Banco: {e}")
        finally:
            self.after(0, self._check_modbus, True)

    def _banco_disconnect(self):
        logging.getLogger().info("Disconnessione Banco in corso...")
        self.executor.submit(self._banco_disconnect_worker)

    def _banco_disconnect_worker(self):
        try:
            self._modbus_was_connected = False
            self.modbus.disconnetti()
            logging.getLogger().info("Banco disconnesso.")
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione Banco: {e}")
        finally:
            self.after(0, self._check_modbus, True)

    def _set_banco_speed(self, speedkmh):
        logging.getLogger().debug(f"Velocità banco: {speedkmh} km/h (invio in corso...)")
        self.executor.submit(self._set_banco_speed_worker, speedkmh)

    def _set_banco_speed_worker(self, speedkmh):
        try:
            if speedkmh is None:
                raise ValueError("La velocità non può essere None")
            if speedkmh > 80:
                raise ValueError("Velocità > 80 km/h. Comando rifiutato.")
            if self.modbus.set_motor_speed(speedkmh * 10):
                logging.getLogger().info(f"Velocità banco {speedkmh} km/h impostata.")
            else:
                logging.getLogger().info("Comando velocità non riuscito.")
        except Exception as e:
            logging.getLogger().error(f"Errore velocità banco: {e}")

    # ── Serial (COM sensor) ───────────────────────────────────────────────────

    def _serial_connect(self, port: str):
        if not port:
            logging.getLogger().warning("Seleziona una COM port prima di connettere.")
            return
        logging.getLogger().info(f"Connessione sensore seriale su {port}...")
        self.executor.submit(self._serial_connect_worker, port)

    def _serial_connect_worker(self, port):
        ok = self.serial_reader.open_connection(port)
        if ok:
            self.after(0, logging.getLogger().info, "Sensore seriale connesso")
            self.after(0, self._start_serial_update)
        else:
            self.after(0, logging.getLogger().warning, "Sensore seriale non connesso.")

    def _start_serial_update(self):
        self._stop_serial_update()
        self._serial_update_tick()

    def _serial_update_tick(self):
        data = self.serial_reader.get_data()
        self._latest_data.update(data)
        self._sidebar.update_serial(data)
        self.serial_update_id = self.after(500, self._serial_update_tick)

    def _stop_serial_update(self):
        if self.serial_update_id is not None:
            self.after_cancel(self.serial_update_id)
            self.serial_update_id = None

    def _serial_disconnect(self):
        logging.getLogger().info("Disconnessione sensore seriale in corso...")
        self._serial_was_connected = False
        self._stop_serial_update()
        self.executor.submit(self._serial_disconnect_worker)

    def _serial_disconnect_worker(self):
        ok = self.serial_reader.close_connection()
        msg = "Sensore seriale disconnesso." if ok else "Sensore: nessuna connessione attiva."
        self.after(0, logging.getLogger().info if ok else logging.getLogger().warning, msg)

    # ── PSU (Alimentatore SCPI) ───────────────────────────────────────────────

    def _check_psu(self):
        connected = self.psu is not None and self.psu.is_connected()
        self._sidebar.set_psu('ok' if connected else 'err')
        if connected:
            self._psu_was_connected = True
        elif self._psu_was_connected:
            logging.getLogger().warning("=" * 55)
            logging.getLogger().warning("*** DISCONNESSIONE PSU - connessione persa ***")
            logging.getLogger().warning("=" * 55)
            self._stop_psu_update()
            self._psu_was_connected = False
            self.after(0, self._sidebar.update_psu, None, None, None)

    def _psu_connect(self, port: str):
        if not port:
            logging.getLogger().warning("Selezionare una porta COM per il PSU.")
            return
        logging.getLogger().info(f"Connessione PSU su {port}...")
        self.executor.submit(self._psu_connect_worker, port)

    def _psu_connect_worker(self, port):
        try:
            psu = Alimentatore(port)
            psu.connect()
            idn = psu.identify()
            self.psu = psu
            self.after(0, logging.getLogger().info, f"PSU connesso: {idn}")
            self.after(0, self._start_psu_update)
        except SCPIError as e:
            logging.getLogger().error(f"Errore connessione PSU: {e}")

    def _psu_disconnect(self):
        logging.getLogger().info("Disconnessione PSU in corso...")
        self._psu_was_connected = False
        self._stop_psu_update()
        self.executor.submit(self._psu_disconnect_worker)

    def _psu_disconnect_worker(self):
        try:
            if self.psu is not None:
                self.psu.disconnect()
                self.psu = None
                self.after(0, logging.getLogger().info, "PSU disconnesso.")
                self.after(0, self._sidebar.update_psu, None, None, None)
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione PSU: {e}")

    def _start_psu_update(self):
        self._stop_psu_update()
        self._psu_update_tick()

    def _stop_psu_update(self):
        if self.psu_update_id is not None:
            self.after_cancel(self.psu_update_id)
            self.psu_update_id = None

    def _psu_update_tick(self):
        if self.psu is not None and self.psu.is_connected():
            self.executor.submit(self._psu_measure_worker)
        self.psu_update_id = self.after(1000, self._psu_update_tick)

    def _psu_measure_worker(self):
        try:
            m = self.psu.measure_all()
            data = {
                'tensione_psu': m.tensione,
                'corrente_psu': m.corrente,
                'potenza_psu':  m.potenza,
            }
            self._latest_data.update(data)
            self.after(0, self._sidebar.update_psu, m.tensione, m.corrente, m.potenza)
        except Exception as e:
            logging.getLogger().debug(f"PSU misura fallita: {e}")

    def _open_psu_settings(self):
        if self.psu is None or not self.psu.is_connected():
            logging.getLogger().warning("PSU non connesso: impossibile aprire impostazioni.")
            return

        win = tk.Toplevel(self)
        win.title("Impostazioni Alimentatore PSU")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

        pad = dict(padx=10, pady=4)
        err_var = tk.StringVar()

        def _show_err(msg):
            err_var.set(msg)
            win.after(3000, lambda: err_var.set(""))

        # ── Uscita ────────────────────────────────────────────────────────────
        ttk.Label(win, text="Uscita", font=('Helvetica', 9, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', padx=10, pady=(12, 2))

        ttk.Label(win, text="Tensione [V]:").grid(row=1, column=0, sticky='e', **pad)
        e_volt = ttk.Entry(win, width=10, justify='right')
        e_volt.insert(0, "0.000")
        e_volt.grid(row=1, column=1, **pad)

        ttk.Label(win, text="Corrente [A]:").grid(row=2, column=0, sticky='e', **pad)
        e_curr = ttk.Entry(win, width=10, justify='right')
        e_curr.insert(0, "0.000")
        e_curr.grid(row=2, column=1, **pad)

        def _apply_vi():
            try:
                v, i = float(e_volt.get()), float(e_curr.get())
                self.executor.submit(lambda: self.psu.apply(v, i))
                logging.getLogger().info(f"PSU: apply({v:.3f} V, {i:.3f} A)")
            except Exception as ex:
                _show_err(str(ex))

        ttk.Button(win, text="⚡ Applica V+I", command=_apply_vi).grid(
            row=1, column=2, rowspan=2, sticky='nsew', padx=(2, 10), pady=4)

        rb = ttk.Frame(win)
        rb.grid(row=3, column=0, columnspan=3, pady=(2, 4))
        ttk.Button(rb, text="▶  Output ON",
                   command=lambda: self.executor.submit(self.psu.output_on)
                   ).grid(row=0, column=0, padx=6)
        ttk.Button(rb, text="■  Output OFF",
                   command=lambda: self.executor.submit(self.psu.output_off)
                   ).grid(row=0, column=1, padx=6)

        ttk.Separator(win, orient='horizontal').grid(
            row=4, column=0, columnspan=3, sticky='ew', padx=10, pady=6)

        # ── Protezioni ────────────────────────────────────────────────────────
        ttk.Label(win, text="Protezioni", font=('Helvetica', 9, 'bold')).grid(
            row=5, column=0, columnspan=3, sticky='w', padx=10, pady=(2, 2))

        ttk.Label(win, text="OVP [V]:").grid(row=6, column=0, sticky='e', **pad)
        e_ovp = ttk.Entry(win, width=10, justify='right')
        e_ovp.insert(0, "0.000")
        e_ovp.grid(row=6, column=1, **pad)
        ob = ttk.Frame(win)
        ob.grid(row=6, column=2, padx=(2, 10))
        ttk.Button(ob, text="Abilita",
                   command=lambda: self.executor.submit(
                       lambda: self.psu.set_ovp(float(e_ovp.get())))
                   ).grid(row=0, column=0, padx=(0, 2))
        ttk.Button(ob, text="Disab.",
                   command=lambda: self.executor.submit(self.psu.disable_ovp)
                   ).grid(row=0, column=1)

        ttk.Label(win, text="OCP [A]:").grid(row=7, column=0, sticky='e', **pad)
        e_ocp = ttk.Entry(win, width=10, justify='right')
        e_ocp.insert(0, "0.000")
        e_ocp.grid(row=7, column=1, **pad)
        ob2 = ttk.Frame(win)
        ob2.grid(row=7, column=2, padx=(2, 10))
        ttk.Button(ob2, text="Abilita",
                   command=lambda: self.executor.submit(
                       lambda: self.psu.set_ocp(float(e_ocp.get())))
                   ).grid(row=0, column=0, padx=(0, 2))
        ttk.Button(ob2, text="Disab.",
                   command=lambda: self.executor.submit(self.psu.disable_ocp)
                   ).grid(row=0, column=1)

        ttk.Separator(win, orient='horizontal').grid(
            row=8, column=0, columnspan=3, sticky='ew', padx=10, pady=6)

        # ── Identificazione ───────────────────────────────────────────────────
        idn_var = tk.StringVar(value="—")
        ttk.Label(win, text="IDN:").grid(row=9, column=0, sticky='e', **pad)
        ttk.Label(win, textvariable=idn_var, foreground='#555555',
                  font=('Helvetica', 8), wraplength=180, justify='left'
                  ).grid(row=9, column=1, sticky='w', **pad)
        ttk.Button(win, text="Leggi",
                   command=lambda: self.executor.submit(
                       lambda: idn_var.set(self.psu.identify()))
                   ).grid(row=9, column=2, padx=(2, 10))

        # ── Errori e chiudi ───────────────────────────────────────────────────
        ttk.Label(win, textvariable=err_var, foreground='#CC0000',
                  font=('Helvetica', 8)).grid(
            row=10, column=0, columnspan=3, padx=10, pady=(4, 0))
        ttk.Button(win, text="Chiudi", command=win.destroy).grid(
            row=11, column=0, columnspan=3, pady=(6, 14))

    # ── Calibrazione automatica da sequenza CSV ───────────────────────────────

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
        from shared_lib.bluetooth_manager import CalibrationPhase

        if not self.ble_manager.get_connection_status():
            logging.getLogger().warning("[Auto-Calib] BLE non connesso: calibrazione saltata.")
            resume_cb(False)
            return

        banco_ok = self.modbus.is_connesso()
        _RAMP_START = 10.0          # km/h avvio banco
        _MARGIN_KMH = 1.0           # km/h di margine sopra la velocità target
        _done = [False]             # flag anti-doppia-chiamata resume_cb

        def _safe_resume(success: bool):
            if _done[0]:
                return
            _done[0] = True
            self.after(0, lambda: resume_cb(success))

        def _on_phase(phase: CalibrationPhase, info: dict):
            if phase == CalibrationPhase.CTRL_REQ:
                if banco_ok:
                    self._set_banco_speed(_RAMP_START)
                    logging.getLogger().info(
                        f"[Auto-Calib] Banco avviato a {_RAMP_START:.0f} km/h")

            elif phase == CalibrationPhase.SPIN_UP:
                high = info.get('target_speed_high_kmh')
                if high is not None and banco_ok:
                    target = round(high + _MARGIN_KMH, 1)
                    self._set_banco_speed(target)
                    logging.getLogger().info(
                        f"[Auto-Calib] Banco portato a {target:.1f} km/h "
                        f"(target_high={high:.1f} + {_MARGIN_KMH:.0f} km/h margine)")

            elif phase == CalibrationPhase.COAST_DOWN:
                if banco_ok:
                    self._set_banco_speed(0)
                    logging.getLogger().info("[Auto-Calib] Banco fermato (coast-down)")

            elif phase == CalibrationPhase.SUCCESS:
                logging.getLogger().info("[Auto-Calib] Calibrazione completata con successo.")
                _safe_resume(True)

            elif phase == CalibrationPhase.FAILED:
                reason = info.get('reason', '?')
                logging.getLogger().warning(f"[Auto-Calib] Calibrazione fallita: {reason}")
                if banco_ok:
                    self._set_banco_speed(0)
                    logging.getLogger().info("[Auto-Calib] Banco fermato per sicurezza.")
                _safe_resume(False)

        self.executor.submit(self._run_spindown_auto_worker, _on_phase, _safe_resume)

    def _run_spindown_auto_worker(self, on_phase_cb, safe_resume):
        """Eseguito nel thread pool: lancia la coroutine sul loop BLE e attende."""
        from shared_lib.bluetooth_manager import CalibrationPhase
        fut = self._run_ble(
            self.ble_manager.start_spindown_calibration(
                status_callback=on_phase_cb,
                timeout_ctrl=5.0,
                timeout_spinup_request=60.0,   # parametro mantenuto per firma
                timeout_spinup=180.0,           # 3 min per raggiungere la velocità
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

    # ── Emergency stop ────────────────────────────────────────────────────────

    def _emergency_stop(self):
        try:
            if self._csv_panel.auto_commands_running:
                self._csv_panel.stop()
            self._set_banco_speed(0)
            self._csv_panel.flash_stop_button()
            logging.getLogger().warning("*** EMERGENCY STOP: speed=0, auto-cmd OFF ***")
        except Exception as e:
            logging.getLogger().error(f"Errore emergency_stop: {e}")

    # ── Menu ─────────────────────────────────────────────────────────────────

    # ── Registrazione dati ───────────────────────────────────────────────────

    def _rec_start_dialog(self):
        win = tk.Toplevel(self)
        win.title("Nuova sessione di registrazione")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

        ts_preview = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')

        ttk.Label(win, text="Nome sessione (opzionale):",
                  font=('Helvetica', 9, 'bold')
                  ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky='w')

        name_entry = ttk.Entry(win, width=20)
        name_entry.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 4), sticky='ew')
        name_entry.focus()

        preview_var = tk.StringVar(value=f"{ts_preview}_bike_data.xlsx")
        ttk.Label(win, text="File:").grid(row=2, column=0, padx=(16, 4), pady=(4, 2), sticky='e')
        ttk.Label(win, textvariable=preview_var, foreground='#0055aa',
                  font=('Helvetica', 8)
                  ).grid(row=2, column=1, padx=(0, 16), pady=(4, 2), sticky='w')
        # Nota esplicativa sotto la preview — tk.Label per supportare fg
        tk.Label(win, text="(senza nome → aggiunge _bike_data)",
                 font=('Helvetica', 7), fg='#888888'
                 ).grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 2))

        def _update_preview(*_):
            ts = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
            raw = name_entry.get().strip().replace(' ', '_')
            # Con nome: YYYYMMDD_HHMMSS_nome.xlsx — Senza: YYYYMMDD_HHMMSS_bike_data.xlsx
            fname = f"{ts}_{raw}.xlsx" if raw else f"{ts}_bike_data.xlsx"
            preview_var.set(fname)

        name_entry.bind('<KeyRelease>', _update_preview)

        err_var = tk.StringVar()
        ttk.Label(win, textvariable=err_var, foreground='#CC0000',
                  font=('Helvetica', 8)
                  ).grid(row=4, column=0, columnspan=2, padx=16, pady=(2, 0))

        def _start():
            try:
                self.data_processor.start_session(name_entry.get())
            except Exception as e:
                err_var.set(str(e))
                return
            fname = os.path.basename(self.data_processor.xlsx_filename)
            self._conn_bar.set_rec_state(True, fname)
            self._status_bar.set_rec(True)
            self._status_bar.set_rec_hz(self._rec_hz, active=True)
            self._rec_tick()
            logging.getLogger().info(f"Registrazione avviata: {fname}")
            win.destroy()

        bf = ttk.Frame(win)
        bf.grid(row=5, column=0, columnspan=2, pady=(8, 14))
        ttk.Button(bf, text="Avvia", command=_start).grid(row=0, column=0, padx=6)
        ttk.Button(bf, text="Annulla", command=win.destroy).grid(row=0, column=1, padx=6)
        win.bind('<Return>', lambda e: _start())

    def _rec_stop(self):
        self.executor.submit(self._rec_stop_worker)

    def _rec_stop_worker(self):
        self.data_processor.stop_session()
        self.after(0, self._rec_stop_ui)

    def _rec_stop_ui(self):
        if self._rec_timer_id is not None:
            self.after_cancel(self._rec_timer_id)
            self._rec_timer_id = None
        self._status_bar.set_rec(False)
        self._status_bar.set_rec_hz(self._rec_hz, active=False)
        fname = os.path.basename(self.data_processor.xlsx_filename) \
            if self.data_processor.xlsx_filename else "—"
        self._conn_bar.set_rec_state(False, f"OK {fname}")
        logging.getLogger().info(f"Registrazione terminata: {fname}")

    def _rec_tick(self):
        """Timer fisso per la scrittura dati. Indipendente da BLE."""
        if self.data_processor.is_recording:
            lorenz = self.lorenz_reader.get_data()
            serial = self.serial_reader.get_data() if self.serial_reader.connected else {}
            snapshot = {**self._latest_data, **lorenz, **serial}
            self.executor.submit(self.data_processor.handle_bike_data, snapshot)
        interval_ms = max(100, int(1000 / self._rec_hz))
        self._rec_timer_id = self.after(interval_ms, self._rec_tick)

    def _create_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # ── File ─────────────────────────────────────────────────────────────
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Cartella di lavoro",
                              command=self._open_working_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Forza salvataggio dati",
                              command=self._menu_flush_data)
        file_menu.add_separator()
        file_menu.add_command(label="Apri cartella output",
                              command=lambda: self._open_working_directory(
                                  os.path.join(self._get_application_path(), 'output')))

        # ── Impostazioni ─────────────────────────────────────────────────────
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Impostazioni", menu=settings_menu)
        settings_menu.add_command(label="Parametri delta e smoothing…",
                                  command=self._menu_open_settings)

        # ── Dispositivo ──────────────────────────────────────────────────────
        dispositivo_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Dispositivo", menu=dispositivo_menu)
        dispositivo_menu.add_command(
            label="Abilita cadenza simulata…",
            command=self._cmd_abilita_cadenza_simulata,
        )
        dispositivo_menu.add_separator()
        dispositivo_menu.add_command(
            label="Informazioni dispositivo…",
            command=self._cmd_show_device_info,
        )
        dispositivo_menu.add_command(
            label="Calibrazione spin-down…",
            command=self._cmd_spindown_calibration,
        )

        # ── Visualizza ───────────────────────────────────────────────────────
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Visualizza", menu=view_menu)
        view_menu.add_command(label="Mostra/Nascondi pannello COM",
                              command=self._sidebar.toggle)

        # ── Info ─────────────────────────────────────────────────────────────
        info_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Info", menu=info_menu)
        info_menu.add_command(label="Guida all'uso…",
                              command=self._menu_show_info)
        info_menu.add_separator()
        _is_dev = VERSION.endswith("-dev") or "unknown" in VERSION
        _ver_label = f"Versione: {VERSION}" + ("  ⚠ build di sviluppo" if _is_dev else "")
        info_menu.add_command(label=_ver_label, state="disabled")

    # ── Azioni menu File ──────────────────────────────────────────────────────

    def _menu_flush_data(self):
        if not self.data_processor.is_recording:
            logging.getLogger().debug("Flush richiesto: nessuna sessione attiva.")
            return
        self.data_processor.flush()
        logging.getLogger().debug("Flush manuale dati eseguito.")

    # ── Azioni menu Impostazioni ──────────────────────────────────────────────

    def _menu_open_settings(self):
        win = tk.Toplevel(self)
        win.title("Parametri delta e smoothing")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

        pad = dict(padx=12, pady=4)

        ttk.Label(win, text="Soglie Δ Velocità (km/h)",
                  font=('Helvetica', 9, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', padx=12, pady=(14, 2))
        ttk.Label(win, text="Verde  ≤").grid(row=1, column=0, sticky='e', **pad)
        spd_t1 = ttk.Entry(win, width=8, justify='right')
        spd_t1.insert(0, str(self.delta_speed_thresholds_kmh[0]))
        spd_t1.grid(row=1, column=1, **pad)
        ttk.Label(win, text="km/h").grid(row=1, column=2, sticky='w', padx=(0, 12))

        ttk.Label(win, text="Arancione  ≤").grid(row=2, column=0, sticky='e', **pad)
        spd_t2 = ttk.Entry(win, width=8, justify='right')
        spd_t2.insert(0, str(self.delta_speed_thresholds_kmh[1]))
        spd_t2.grid(row=2, column=1, **pad)
        ttk.Label(win, text="km/h").grid(row=2, column=2, sticky='w', padx=(0, 12))

        ttk.Separator(win, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky='ew', padx=12, pady=6)

        ttk.Label(win, text="Soglie Δ Potenza (%)",
                  font=('Helvetica', 9, 'bold')).grid(
            row=4, column=0, columnspan=3, sticky='w', padx=12, pady=(2, 2))
        ttk.Label(win, text="Verde  ≤").grid(row=5, column=0, sticky='e', **pad)
        pwr_t1 = ttk.Entry(win, width=8, justify='right')
        pwr_t1.insert(0, str(self.delta_power_thresholds_pct[0]))
        pwr_t1.grid(row=5, column=1, **pad)
        ttk.Label(win, text="%").grid(row=5, column=2, sticky='w', padx=(0, 12))

        ttk.Label(win, text="Arancione  ≤").grid(row=6, column=0, sticky='e', **pad)
        pwr_t2 = ttk.Entry(win, width=8, justify='right')
        pwr_t2.insert(0, str(self.delta_power_thresholds_pct[1]))
        pwr_t2.grid(row=6, column=1, **pad)
        ttk.Label(win, text="%").grid(row=6, column=2, sticky='w', padx=(0, 12))

        ttk.Separator(win, orient='horizontal').grid(
            row=7, column=0, columnspan=3, sticky='ew', padx=12, pady=6)

        ttk.Label(win, text="Smoothing window",
                  font=('Helvetica', 9, 'bold')).grid(
            row=8, column=0, columnspan=3, sticky='w', padx=12, pady=(2, 2))
        ttk.Label(win, text="Campioni (N)").grid(row=9, column=0, sticky='e', **pad)
        smw = ttk.Entry(win, width=8, justify='right')
        smw.insert(0, str(self.delta_smoothing_window))
        smw.grid(row=9, column=1, **pad)

        ttk.Separator(win, orient='horizontal').grid(
            row=10, column=0, columnspan=3, sticky='ew', padx=12, pady=6)
        ttk.Label(win, text="Frequenza registrazione",
                  font=('Helvetica', 9, 'bold')).grid(
            row=11, column=0, columnspan=3, sticky='w', padx=12, pady=(2, 2))
        ttk.Label(win, text="Frequenza [Hz]:").grid(row=12, column=0, sticky='e', **pad)
        rec_hz_cb = ttk.Combobox(win, values=['1', '2', '4', '10'], width=6,
                                 justify='right', state='readonly')
        rec_hz_cb.set(str(self._rec_hz))
        rec_hz_cb.grid(row=12, column=1, **pad)

        err_var = tk.StringVar()
        ttk.Label(win, textvariable=err_var, foreground='#CC0000',
                  font=('Helvetica', 8)).grid(
            row=14, column=0, columnspan=3, padx=12, pady=(2, 0))

        def _apply():
            try:
                s1 = float(spd_t1.get())
                s2 = float(spd_t2.get())
                p1 = float(pwr_t1.get())
                p2 = float(pwr_t2.get())
                n  = int(smw.get())
                if s1 <= 0 or s2 <= s1:
                    raise ValueError("Soglie velocità: richiede 0 < verde < arancione")
                if p1 <= 0 or p2 <= p1:
                    raise ValueError("Soglie potenza: richiede 0 < verde < arancione")
                if n < 1:
                    raise ValueError("Smoothing window deve essere ≥ 1")
                hz = int(rec_hz_cb.get())
            except ValueError as e:
                err_var.set(str(e))
                return

            self.delta_speed_thresholds_kmh = (s1, s2)
            self.delta_power_thresholds_pct = (p1, p2)
            self.delta_smoothing_window     = n
            self._rec_hz                    = hz
            self._live_panel.set_thresholds(
                self.delta_speed_thresholds_kmh,
                self.delta_power_thresholds_pct)
            self._live_panel.set_smoothing_window(n)
            self._save_settings()
            # Aggiorna immediatamente la label Hz nella status bar
            self._status_bar.set_rec_hz(hz, active=self.data_processor.is_recording)
            logging.getLogger().info(
                f"Settings updated - spd ({s1},{s2}) km/h | pwr ({p1},{p2})% | N={n} | REC {hz}Hz")

        bf = ttk.Frame(win)
        bf.grid(row=15, column=0, columnspan=3, pady=(8, 14))
        ttk.Button(bf, text="Applica", command=_apply).grid(
            row=0, column=0, padx=6)
        ttk.Button(bf, text="Annulla", command=win.destroy).grid(
            row=0, column=1, padx=6)

    # ── Azioni menu Info ──────────────────────────────────────────────────────

    def _menu_show_info(self):
        win = tk.Toplevel(self)
        win.title("Guida all'uso")
        win.resizable(True, True)
        win.transient(self)
        win.geometry("580x540")

        outer = ttk.Frame(win)
        outer.pack(fill='both', expand=True, padx=2, pady=2)

        sb = ttk.Scrollbar(outer, orient='vertical')
        sb.pack(side='right', fill='y')
        canvas = tk.Canvas(outer, yscrollcommand=sb.set,
                           highlightthickness=0, bg='white')
        canvas.pack(side='left', fill='both', expand=True)
        sb.config(command=canvas.yview)

        inner = tk.Frame(canvas, bg='white')
        canvas_win = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _on_resize(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind('<Configure>', _on_resize)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox('all')))
        canvas.bind_all('<MouseWheel>',
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), 'units'))

        def _on_info_close():
            canvas.unbind_all('<MouseWheel>')
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_info_close)

        _BG  = 'white'
        _H1  = ('Helvetica', 11, 'bold')
        _H2  = ('Helvetica', 10, 'bold')
        _TXT = ('Helvetica', 9)

        def h1(text):
            tk.Label(inner, text=text, font=_H1, bg=_BG,
                     fg='#1a1a2e', anchor='w'
                     ).pack(fill='x', padx=16, pady=(14, 2))
            tk.Frame(inner, bg='#aaaacc', height=1).pack(
                fill='x', padx=16, pady=(0, 6))

        def h2(text):
            tk.Label(inner, text=text, font=_H2, bg=_BG,
                     fg='#333366', anchor='w'
                     ).pack(fill='x', padx=20, pady=(8, 1))

        def body(text):
            tk.Label(inner, text=text, font=_TXT, bg=_BG,
                     fg='#333333', anchor='nw', justify='left',
                     wraplength=510
                     ).pack(fill='x', padx=24, pady=(0, 4))

        # ── Contenuto ─────────────────────────────────────────────────────
        h1("● Barra di Stato — LED")

        h2("APP  (primo LED a sinistra)")
        body("Indicatore per capire se il programma si è congelato. Fino a quanto lampeggia e il contatore incrementa tutto ok")

        h2("BLE / Lorenz / Banco / COM")
        body("Verde = dispositivo connesso e raggiungibile.\n"
             "Rosso = non connesso o connessione persa. ")

        h2("FTMS — frequenza dati")
        body("Mostra la frequenza (Hz) con cui arrivano i pacchetti dati dal "
             "trainer BLE. Attivo solo quando le notifiche FTMS sono abilitate. "
             "Si spegne automaticamente se i dati si interrompono per più di 2 secondi.")

        h2("Auto")
        body("Verde = sequenza automatica da CSV in esecuzione.\n"
             "Spento = nessuna sequenza attiva.")

        h2("REC")
        body("Rosso lampeggiante = la sessione è in registrazione.\n"
             "Spento = nessuna registazione in corso")

        h1("● Barra Connessioni")

        h2("REC")
        body("Avvia o ferma la registrazione dei dati. Vengono registrati tutti i dati disponibili in quel momento. "
             "La cartella di Output serve ad aprire dove sono i risultati. "
             "In caso di superamento dei 50 Mega di dimensioni del file verrà creato un nuovo file")

        h2("BLE")
        body("Cerca i dispositivi Bluetooth nelle vicinanze, seleziona il trainer "
             "dalla lista e premi Connetti. La barra di avanzamento indica che "
             "un'operazione è in corso. Una volta connesso, le notifiche FTMS "
             "vengono abilitate automaticamente dopo 4 secondi.")

        h2("Lorenz")
        body("Connette il sensore di coppia/potenza esterno sulla porta USB dedicata. "
             "'Leggi Offset' acquisisce il valore di offset attuale (eseguire a riposo). "
             "'Media' imposta quanti campioni usare per la media mobile. "
             "'Inverti Velocità' inverte il segno del canale B.")

        h2("Banco")
        body("Connette il motore tramite Modbus TCP. Inserire l'IP del banco e premere "
             "Connetti. La velocità viene impostata automaticamente durante le sequenze "
             "automatiche se specificata nel CSV.")

        h2("Sensore COM")
        body("Connette un sensore seriale aggiuntivo (fino a 4 valori numerici separati "
             "da ';'). Il pannello è collassabile con il pulsante '+COM'.")

        h1("● Comandi e Sequenza Automatica")

        h2("Comandi manuali")
        body("Inviano direttamente al trainer un livello di resistenza (0–200), "
             "una potenza target (W) o un profilo di simulazione (pendenza %). "
             "Usare per test rapidi o verifica risposta.")

        h2("Sequenza da CSV")
        body("Carica un file CSV con colonne: tempo_attesa; livello; potenza; "
             "simulazione; velocità_banco. Una sola colonna per riga deve essere "
             "valorizzata. Il programma esegue i comandi nell'ordine, aspettando "
             "il tempo indicato tra uno e l'altro. Al termine di tutti i cicli, "
             "vengono inviati automaticamente freno=0 e velocità banco=0 per sicurezza. "
             "Le notifiche FTMS restano attive e vanno disabilitate manualmente se necessario.")

        h2("Emergency Stop")
        body("Ferma immediatamente la sequenza automatica e imposta la velocità "
             "del banco a 0. Usare in caso di necessità.")

        h1("● Dati Live e Pannello Δ")

        body("Il pannello mostra in tempo reale i valori ricevuti dal trainer BLE "
             "e dal sensore Lorenz affiancati. Il Δ centrale indica la differenza "
             "tra le due sorgenti: verde se rientra nella soglia, arancione se "
             "moderato, rosso se elevato. Le soglie e la finestra di smoothing "
             "sono configurabili da Impostazioni → Parametri delta.")

        h1("● Salvataggio Dati")

        body("Per avviare la registrazione premere ⏺ REC: verrà chiesto un nome "
             "opzionale per la sessione. Senza nome il file sarà YYYYMMDD_HHMMSS_bike_data.xlsx; "
             "con nome personalizzato sarà YYYYMMDD_HHMMSS_nome.xlsx (senza suffisso _bike_data). "
             "Premere ⏹ STOP per terminare la sessione con flush finale garantito. "
             "È possibile avviare più sessioni consecutive senza riavviare il programma.")
        body("Il salvataggio avviene automaticamente ogni 30 secondi. Se il file supera "
             "100 MB viene creato un nuovo file (_part02, _part03…) con la stessa intestazione. "
             "Per forzare il salvataggio immediato usare File → Forza salvataggio dati. "
             "La frequenza di registrazione (default 2 Hz) è configurabile da "
             "Impostazioni → Parametri delta.")

        # ── Pulsante chiudi ────────────────────────────────────────────────
        ttk.Button(win, text="Chiudi", command=_on_info_close
                   ).pack(pady=10)


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

    def _cmd_abilita_cadenza_simulata(self):
        """
        Apre un dialog con indirizzo EEPROM (hex, default 0x0549) e valore
        (0-255, default 70) entrambi editabili. Conferma prima di scrivere.
        """
        from tkinter import messagebox

        if not self.ble_manager.get_connection_status():
            messagebox.showwarning(
                "Dispositivo non connesso",
                "Nessun trainer BLE connesso.\n"
                "Connetti il dispositivo prima di inviare questo comando.",
                parent=self,
            )
            return

        # ── Dialog ───────────────────────────────────────────────────────────
        win = tk.Toplevel(self)
        win.title("Scrittura EEPROM — cadenza simulata")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

        pad = dict(padx=14, pady=4)

        # Dispositivo connesso
        if self._connected_device_name or self._connected_device_address:
            dev_txt = (f"{self._connected_device_name or '?'}"
                       f"  [{self._connected_device_address or '?'}]")
            tk.Label(win, text=dev_txt, font=('Helvetica', 8), fg='#555555'
                     ).grid(row=0, column=0, columnspan=3,
                            padx=14, pady=(12, 4), sticky='w')

        # ── Riga indirizzo ────────────────────────────────────────────────────
        ttk.Label(win, text="Indirizzo EEPROM:").grid(
            row=1, column=0, sticky='e', **pad)
        addr_frame = ttk.Frame(win)
        addr_frame.grid(row=1, column=1, columnspan=2, sticky='w', **pad)
        tk.Label(addr_frame, text="0x", font=('Courier', 9),
                 fg='#555555').grid(row=0, column=0)
        addr_entry = ttk.Entry(addr_frame, width=6, justify='left',
                               font=('Courier', 9))
        addr_entry.insert(0, "0549")
        addr_entry.grid(row=0, column=1)
        tk.Label(addr_frame, text="(hex, 0000 – FFFF)",
                 font=('Helvetica', 8), fg='#888888'
                 ).grid(row=0, column=2, padx=(8, 0))

        # ── Riga valore ───────────────────────────────────────────────────────
        ttk.Label(win, text="Valore (0 – 255):").grid(
            row=2, column=0, sticky='e', **pad)
        spin = ttk.Spinbox(win, from_=0, to=255, increment=1,
                           width=6, justify='right')
        spin.set(70)
        spin.grid(row=2, column=1, sticky='w', **pad)

        hex_var = tk.StringVar(value="0x46")
        tk.Label(win, textvariable=hex_var, font=('Courier', 9),
                 fg='#888888').grid(row=2, column=2, sticky='w', padx=(0, 14))

        def _update_hex(*_):
            try:
                hex_var.set(f"0x{int(float(spin.get())):02X}")
            except Exception:
                hex_var.set("—")

        spin.bind('<KeyRelease>', _update_hex)
        spin.bind('<<Increment>>', _update_hex)
        spin.bind('<<Decrement>>', _update_hex)

        # ── Avviso ────────────────────────────────────────────────────────────
        ttk.Separator(win, orient='horizontal').grid(
            row=3, column=0, columnspan=3, sticky='ew', padx=14, pady=(6, 4))
        tk.Label(win,
                 text="⚠  Supportato solo su alcuni modelli di trainer.\n"
                      "Su modelli non compatibili il comportamento\n"
                      "potrebbe essere imprevisto.",
                 font=('Helvetica', 8), fg='#885500', justify='left'
                 ).grid(row=4, column=0, columnspan=3,
                        padx=14, pady=(0, 4), sticky='w')
        ttk.Separator(win, orient='horizontal').grid(
            row=5, column=0, columnspan=3, sticky='ew', padx=14, pady=(4, 2))

        # Errore di validazione
        err_var = tk.StringVar()
        tk.Label(win, textvariable=err_var, font=('Helvetica', 8),
                 fg='#CC0000').grid(row=6, column=0, columnspan=3,
                                    padx=14, pady=(2, 2))

        # ── Pulsanti ──────────────────────────────────────────────────────────
        def _confirm():
            # Valida indirizzo
            try:
                addr = int(addr_entry.get().strip(), 16)
                if not (0x0000 <= addr <= 0xFFFF):
                    raise ValueError
            except ValueError:
                err_var.set("Indirizzo non valido: inserire un valore hex tra 0000 e FFFF.")
                addr_entry.focus()
                return
            # Valida valore
            try:
                value = int(float(spin.get()))
                if not (0 <= value <= 255):
                    raise ValueError
            except ValueError:
                err_var.set("Valore non valido: inserire un intero tra 0 e 255.")
                spin.focus()
                return

            win.destroy()
            self.executor.submit(self._cmd_abilita_cadenza_simulata_worker, addr, value)

        bf = ttk.Frame(win)
        bf.grid(row=7, column=0, columnspan=3, pady=(4, 14))
        ttk.Button(bf, text="Scrivi",   command=_confirm   ).grid(row=0, column=0, padx=6)
        ttk.Button(bf, text="Annulla",  command=win.destroy).grid(row=0, column=1, padx=6)
        win.bind('<Return>', lambda e: _confirm())

    def _cmd_abilita_cadenza_simulata_worker(self, address: int, value: int):
        """Eseguito nel thread pool: chiama write_eeprom e riporta il risultato al main thread."""
        try:
            ok = self._run_ble(
                self.ble_manager.write_eeprom(address=address, data=bytearray([value]))
            ).result(timeout=10)
        except Exception as e:
            logging.getLogger().error(f"Errore scrittura EEPROM 0x{address:04X}: {e}")
            ok = False

        self.after(0, self._cmd_abilita_cadenza_simulata_result, ok, address, value)

    def _cmd_abilita_cadenza_simulata_result(self, ok: bool, address: int, value: int):
        """Chiamato sul main thread per mostrare l'esito all'utente."""
        from tkinter import messagebox
        if ok:
            logging.getLogger().info(
                f"EEPROM 0x{address:04X} = {value} (0x{value:02X}) — scrittura OK.")
        else:
            logging.getLogger().error(
                f"Scrittura EEPROM 0x{address:04X} = {value} fallita.")
            messagebox.showerror(
                "Scrittura fallita",
                "Impossibile scrivere nell'EEPROM del trainer.\n"
                "Verifica la connessione BLE e riprova.",
                parent=self,
            )

    def _cmd_show_device_info(self):
        """Mostra le informazioni DIS (Device Information Service) del dispositivo BLE connesso."""
        if not self.ble_manager.get_connection_status():
            from tkinter import messagebox
            messagebox.showwarning(
                "Dispositivo non connesso",
                "Nessun trainer BLE connesso.\n"
                "Connetti il dispositivo prima di leggere le informazioni.",
                parent=self,
            )
            return

        win = tk.Toplevel(self)
        win.title("Informazioni Dispositivo")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        win.geometry(f"420x360+{px + (pw - 420) // 2}+{py + (ph - 360) // 2}")

        # ── Header device ─────────────────────────────────────────────────────────
        hf = tk.Frame(win, bg='#1e1e2e')
        hf.pack(fill='x')
        tk.Label(hf, text=self._connected_device_name or "Dispositivo",
                 font=('Helvetica', 10, 'bold'), bg='#1e1e2e', fg='#88ffaa',
                 ).pack(side='left', padx=12, pady=(7, 2))
        tk.Label(hf, text=self._connected_device_address or "",
                 font=('Helvetica', 8), bg='#1e1e2e', fg='#888899',
                 ).pack(side='left', pady=(7, 2))

        # ── Griglia campi DIS ────────────────────────────────────────────────────
        _FIELD_LABELS = [
            ('manufacturer_name', 'Produttore'),
            ('model_number', 'Modello'),
            ('serial_number', 'N. Seriale'),
            ('firmware_revision', 'Firmware'),
            ('hardware_revision', 'Hardware Rev.'),
            ('software_revision', 'Software Rev.'),
            ('system_id', 'System ID'),
            ('pnp_id', 'PnP ID'),
        ]

        grid = ttk.Frame(win)
        grid.pack(fill='both', expand=True, padx=14, pady=10)
        grid.grid_columnconfigure(1, weight=1)

        status_var = tk.StringVar(value="Lettura in corso…")
        ttk.Label(grid, textvariable=status_var,
                  font=('Helvetica', 8, 'italic'), foreground='#888888',
                  ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))

        val_vars = {}
        for i, (key, label) in enumerate(_FIELD_LABELS, start=1):
            ttk.Label(grid, text=label + ":", font=('Helvetica', 9),
                      anchor='e', width=13,
                      ).grid(row=i, column=0, sticky='e', padx=(0, 8), pady=2)
            var = tk.StringVar(value="…")
            ttk.Label(grid, textvariable=var, font=('Helvetica', 9),
                      foreground='#222222', anchor='w',
                      ).grid(row=i, column=1, sticky='w', pady=2)
            val_vars[key] = var

        # ── Pulsanti ─────────────────────────────────────────────────────────────
        bf = ttk.Frame(win)
        bf.pack(fill='x', padx=14, pady=(4, 10))
        btn_refresh = ttk.Button(bf, text="🔄 Aggiorna", command=lambda: _fetch())
        btn_refresh.pack(side='left')
        ttk.Button(bf, text="Chiudi", command=win.destroy).pack(side='right')

        # ── Populate ─────────────────────────────────────────────────────────────
        def _populate(info: dict):
            data = info.get('data', {})
            missing = set(info.get('missing', []))
            for key, var in val_vars.items():
                if key in missing:
                    var.set("N/A")
                elif key in data:
                    v = data[key]
                    if isinstance(v, dict):
                        if key == 'system_id':
                            var.set(
                                f"Manuf: 0x{v.get('manufacturer_id', 0):010X}"
                                f"  OUI: 0x{v.get('oui', 0):06X}"
                            )
                        elif key == 'pnp_id':
                            var.set(
                                f"VID: 0x{v.get('vendor_id', 0):04X}"
                                f"  PID: 0x{v.get('product_id', 0):04X}"
                                f"  Rev: 0x{v.get('product_version', 0):04X}"
                            )
                        else:
                            var.set(str(v))
                    else:
                        var.set(str(v) if v else "—")
                else:
                    var.set("—")
            status_var.set("Aggiornato")
            btn_refresh.config(state='normal')

        def _fetch():
            btn_refresh.config(state='disabled')
            status_var.set("Lettura in corso…")
            for var in val_vars.values():
                var.set("…")

            def _worker():
                fut = self._run_ble(self.ble_manager.read_device_information(timeout=6.0))
                try:
                    info = fut.result(timeout=10)
                except Exception as e:
                    logging.getLogger().error(f"Errore lettura device info: {e}")
                    info = {'data': {}, 'missing': [k for k in val_vars], 'errors': {}}
                self.after(0, _populate, info)

            self.executor.submit(_worker)

        _fetch()

    def _cmd_spindown_calibration(self):
        """Dialog guidato per la calibrazione spin-down FTMS con controllo banco integrato."""
        from shared_lib.bluetooth_manager import CalibrationPhase

        if not self.ble_manager.get_connection_status():
            from tkinter import messagebox
            messagebox.showwarning(
                "Dispositivo non connesso",
                "Nessun trainer BLE connesso.\n"
                "Connetti il dispositivo prima di avviare la calibrazione.",
                parent=self,
            )
            return

        banco_ok = self.modbus.is_connesso()

        win = tk.Toplevel(self)
        win.title("Calibrazione Spin-Down")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        win.geometry(f"460x540+{px + (pw - 460) // 2}+{py + (ph - 540) // 2}")

        # ── Header ───────────────────────────────────────────────────────────────
        hf = tk.Frame(win, bg='#1e1e2e')
        hf.pack(fill='x')
        tk.Label(hf, text="Calibrazione Spin-Down",
                 font=('Helvetica', 11, 'bold'), bg='#1e1e2e', fg='#aaaaff',
                 ).pack(side='left', padx=12, pady=8)
        dev = (self._connected_device_name or "")
        if self._connected_device_address:
            dev += f"  [{self._connected_device_address}]"
        tk.Label(hf, text=dev, font=('Helvetica', 8),
                 bg='#1e1e2e', fg='#666688').pack(side='left', pady=8)

        # ── Avviso banco non connesso ─────────────────────────────────────────────
        if not banco_ok:
            warn_f = tk.Frame(win, bg='#FFF3CD')
            warn_f.pack(fill='x')
            tk.Label(warn_f,
                     text="⚠  Banco non connesso — velocità controllata manualmente.",
                     font=('Helvetica', 8), bg='#FFF3CD', fg='#7B4D00',
                     pady=4, padx=12).pack(anchor='w')

        # ── Indicatore fasi ───────────────────────────────────────────────────────
        _PHASES_DEF = [
            ("Avvio", "ctrl"),
            ("Spin-Up", "spinup"),
            ("Coast-Down", "coast"),
            ("Risultato", "result"),
        ]
        _C_IDLE = '#AAAAAA'
        _C_ACTIVE = '#E8A000'
        _C_OK = '#00BB44'
        _C_FAIL = '#CC2222'

        step_frame = tk.Frame(win, bg='white')
        step_frame.pack(fill='x', padx=16, pady=(10, 4))
        phase_leds = {}
        for i, (label, key) in enumerate(_PHASES_DEF):
            col = i * 2
            step_frame.grid_columnconfigure(col, weight=1)
            step_frame.grid_columnconfigure(col + 1, weight=0)
            led = tk.Label(step_frame, text='●', font=('Helvetica', 18),
                           bg='white', fg=_C_IDLE)
            led.grid(row=0, column=col, sticky='ew')
            tk.Label(step_frame, text=label, font=('Helvetica', 7),
                     bg='white', fg='#555555').grid(row=1, column=col, sticky='ew')
            if i < len(_PHASES_DEF) - 1:
                tk.Label(step_frame, text='──', font=('Helvetica', 9),
                         bg='white', fg='#cccccc').grid(row=0, column=col + 1)
            phase_leds[key] = led

        # ── Area istruzione ───────────────────────────────────────────────────────
        instr_var = tk.StringVar(value="Premi Avvia per iniziare.")
        instr_lbl = tk.Label(win, textvariable=instr_var,
                             font=('Helvetica', 11, 'bold'),
                             fg='#1a1a2e', bg='#F0F4FF',
                             justify='center', wraplength=420,
                             relief='groove', bd=1, pady=10, padx=10)
        instr_lbl.pack(fill='x', padx=16, pady=(4, 4))

        # ── Velocità: attuale (grande) + range target (low–high) ────────────────
        spd_outer = tk.Frame(win, bg='white', relief='sunken', bd=1)
        spd_outer.pack(fill='x', padx=16, pady=(2, 2))

        # Riga superiore: velocità attuale letta dal rullo BLE
        spd_top = tk.Frame(spd_outer, bg='white')
        spd_top.pack(fill='x', padx=8, pady=(6, 0))

        tk.Label(spd_top, text="Velocità attuale",
                 font=('Helvetica', 8), fg='#555555', bg='white',
                 anchor='w').pack(side='left')

        speed_var = tk.StringVar(value="—")
        tk.Label(spd_top, textvariable=speed_var,
                 font=('Courier', 28, 'bold'), fg='#003300', bg='white',
                 anchor='e').pack(side='right', padx=(0, 4))

        tk.Label(spd_top, text="km/h",
                 font=('Helvetica', 10), fg='#555555', bg='white',
                 ).pack(side='right')

        # Separatore
        tk.Frame(spd_outer, bg='#e0e0e0', height=1).pack(fill='x', padx=8, pady=2)

        # Riga inferiore: range target (min – max)
        spd_bot = tk.Frame(spd_outer, bg='white')
        spd_bot.pack(fill='x', padx=8, pady=(0, 6))

        tk.Label(spd_bot, text="Target",
                 font=('Helvetica', 8), fg='#555555', bg='white',
                 anchor='w').pack(side='left')

        # "min:" label
        tk.Label(spd_bot, text="min:",
                 font=('Helvetica', 8), fg='#885500', bg='white',
                 ).pack(side='left', padx=(8, 2))
        target_low_var = tk.StringVar(value="—")
        target_low_lbl = tk.Label(spd_bot, textvariable=target_low_var,
                                  font=('Courier', 13, 'bold'), fg='#885500', bg='white')
        target_low_lbl.pack(side='left')
        tk.Label(spd_bot, text="km/h",
                 font=('Helvetica', 8), fg='#885500', bg='white').pack(side='left', padx=(2, 10))

        # "max:" label
        tk.Label(spd_bot, text="max:",
                 font=('Helvetica', 8), fg='#006600', bg='white',
                 ).pack(side='left', padx=(0, 2))
        target_high_var = tk.StringVar(value="—")
        target_high_lbl = tk.Label(spd_bot, textvariable=target_high_var,
                                   font=('Courier', 13, 'bold'), fg='#006600', bg='white')
        target_high_lbl.pack(side='left')
        tk.Label(spd_bot, text="km/h",
                 font=('Helvetica', 8), fg='#006600', bg='white').pack(side='left', padx=(2, 0))

        # ── Progressbar coast-down + elapsed timer ────────────────────────────────
        pb_frame = tk.Frame(win, bg=win.cget('bg'))     # contenitore non visibile finché non serve
        pb = ttk.Progressbar(pb_frame, mode='indeterminate', length=400)
        pb.pack(fill='x', padx=0)
        _coast_elapsed_var = tk.StringVar(value="")
        _coast_elapsed_lbl = tk.Label(pb_frame, textvariable=_coast_elapsed_var,
                                      font=('Helvetica', 7), fg='#555577',
                                      bg=win.cget('bg'))
        _coast_elapsed_lbl.pack(anchor='e', padx=4)
        _coast_timer_id = [None]
        _coast_t0 = [0.0]

        def _start_coast_timer():
            import time as _time
            _coast_t0[0] = _time.monotonic()
            _coast_elapsed_var.set("coast-down: 0 s")

            def _tick():
                elapsed = int(_time.monotonic() - _coast_t0[0])
                _coast_elapsed_var.set(f"coast-down: {elapsed} s")
                _coast_timer_id[0] = win.after(1000, _tick)

            _tick()

        def _stop_coast_timer():
            if _coast_timer_id[0]:
                win.after_cancel(_coast_timer_id[0])
                _coast_timer_id[0] = None
            _coast_elapsed_var.set("")

        # ── Controllo Banco ───────────────────────────────────────────────────────
        banco_frame = ttk.LabelFrame(win, text="Controllo Banco")
        banco_frame.pack(fill='x', padx=16, pady=(6, 4))

        bf_inner = ttk.Frame(banco_frame)
        bf_inner.pack(fill='x', padx=8, pady=6)
        bf_inner.grid_columnconfigure(1, weight=1)

        ttk.Label(bf_inner, text="Velocità banco [km/h]:").grid(
            row=0, column=0, sticky='e', padx=(0, 6))

        banco_speed_var = tk.DoubleVar(value=0.0)
        banco_spin = ttk.Spinbox(bf_inner, from_=0.0, to=80.0, increment=0.5,
                                 format="%.1f", width=8,
                                 textvariable=banco_speed_var)
        banco_spin.grid(row=0, column=1, sticky='w')

        def _set_banco_manual():
            try:
                v = float(banco_speed_var.get())
            except (ValueError, tk.TclError):
                return
            self._set_banco_speed(v)
            logging.getLogger().info(
                f"[Calibrazione] Banco impostato manualmente a {v:.1f} km/h")

        def _stop_banco_now():
            banco_speed_var.set(0.0)
            self._set_banco_speed(0)
            logging.getLogger().info("[Calibrazione] Banco fermato manualmente.")

        ttk.Button(bf_inner, text="Set", width=5,
                   command=_set_banco_manual).grid(row=0, column=2, padx=(8, 4))
        tk.Button(bf_inner, text="■  Stop Banco",
                  font=('Helvetica', 9, 'bold'),
                  bg='#CC2222', fg='white',
                  activebackground='#AA0000', activeforeground='white',
                  relief='raised', bd=2, cursor='hand2', width=11,
                  command=_stop_banco_now,
                  ).grid(row=0, column=3, padx=(4, 0))

        banco_status_var = tk.StringVar(
            value="Banco connesso — pronto" if banco_ok else "Banco non connesso")
        tk.Label(banco_frame, textvariable=banco_status_var,
                 font=('Helvetica', 7, 'italic'), fg='#555555',
                 ).pack(anchor='w', padx=10, pady=(0, 4))

        # ── Pulsanti principali ───────────────────────────────────────────────────
        main_bf = ttk.Frame(win)
        main_bf.pack(fill='x', padx=16, pady=(4, 10))
        btn_start = tk.Button(
            main_bf, text="▶  Avvia",
            font=('Helvetica', 10, 'bold'),
            bg='#0D3B6E', fg='white',
            activebackground='#082B52', activeforeground='white',
            relief='raised', bd=2, cursor='hand2', width=10,
        )
        btn_start.pack(side='left')
        btn_close = ttk.Button(main_bf, text="Chiudi",
                               command=lambda: _on_close(), width=8)
        btn_close.pack(side='right')

        # ── Stato interno ─────────────────────────────────────────────────────────
        _calib_running = [False]
        _speed_poll_id = [None]

        def _set_phase_led(key, state):
            colors = {'active': _C_ACTIVE, 'ok': _C_OK, 'fail': _C_FAIL, 'idle': _C_IDLE}
            if key in phase_leds:
                phase_leds[key].config(fg=colors.get(state, _C_IDLE))

        # Polling velocità: parte subito all'apertura, non solo durante spin-up
        def _start_speed_poll():
            def _tick():
                spd = self._latest_data.get('Spd')
                speed_var.set(f"{spd:.1f}" if spd is not None else "—")
                _speed_poll_id[0] = win.after(200, _tick)

            _tick()

        def _stop_speed_poll():
            if _speed_poll_id[0]:
                win.after_cancel(_speed_poll_id[0])
                _speed_poll_id[0] = None

        # ── Callback calibrazione ─────────────────────────────────────────────────
        def _on_phase(phase: CalibrationPhase, info: dict):
            self.after(0, _apply_phase, phase, info)

        # Velocità di avvio automatico banco nella fase CTRL_REQ.
        # Usata solo se banco connesso; l'utente può sovrascriverla col Set.
        _RAMP_START_SPEED_KMH = 10.0

        def _apply_phase(phase: CalibrationPhase, info: dict):
            pb.stop()
            pb_frame.pack_forget()
            _stop_coast_timer()

            if phase == CalibrationPhase.CTRL_REQ:
                _set_phase_led('ctrl', 'active')
                if banco_ok:
                    banco_speed_var.set(_RAMP_START_SPEED_KMH)
                    self._set_banco_speed(_RAMP_START_SPEED_KMH)
                    banco_status_var.set(
                        f"✔  Banco avviato a {_RAMP_START_SPEED_KMH:.0f} km/h — aumenta gradualmente")
                    instr_var.set(
                        "Banco avviato — aumenta la velocità finché il rullo non risponde.\n"
                        "Il rullo segnalerà quando smettere.")
                else:
                    instr_var.set(
                        "Pedala fino alla velocità target.\n"
                        "Il rullo segnalerà quando smettere.")
                instr_lbl.config(fg='#885500', bg='#FFFBE6')

            elif phase == CalibrationPhase.SPIN_UP:
                _set_phase_led('ctrl', 'ok')
                _set_phase_led('spinup', 'active')
                low  = info.get('target_speed_low_kmh')
                high = info.get('target_speed_high_kmh')

                target_low_var.set(f"{low:.1f}"   if low  is not None else "—")
                target_high_var.set(f"{high:.1f}" if high is not None else "—")

                if high is not None:
                    if banco_ok:
                        target = round(high, 1)
                        banco_speed_var.set(target)
                        self._set_banco_speed(target)
                        banco_status_var.set(f"✔  Banco impostato a {target:.1f} km/h (automatico)")
                        instr_var.set(
                            f"Raggiungi {high:.1f} km/h\n"
                            f"(banco impostato automaticamente)")
                    else:
                        instr_var.set(
                            f"Raggiungi {high:.1f} km/h\n"
                            "Imposta il banco manualmente." if low is not None
                            else f"Raggiungi {high:.1f} km/h")
                else:
                    instr_var.set("Pedala fino alla velocità target.\n(target non ricevuto dal rullo)")
                instr_lbl.config(fg='#1a1a2e', bg='#E8F5E9')

            elif phase == CalibrationPhase.COAST_DOWN:
                # Il trainer può arrivare qui saltando la notifica SPIN_UP
                if phase_leds['ctrl'].cget('fg') == _C_ACTIVE:
                    _set_phase_led('ctrl', 'ok')
                if phase_leds['spinup'].cget('fg') in (_C_ACTIVE, _C_IDLE):
                    _set_phase_led('spinup', 'ok')
                _set_phase_led('coast', 'active')
                target_low_var.set("—")
                target_high_var.set("—")
                if banco_ok:
                    self._set_banco_speed(0)
                    banco_speed_var.set(0.0)
                    banco_status_var.set("✔  Banco fermato (coast-down automatico)")
                instr_var.set("⏸  Smetti di pedalare.\nCoast-down in corso, non toccare il banco…")
                instr_lbl.config(fg='#005580', bg='#E3F2FD')
                pb_frame.pack(fill='x', padx=16, pady=(0, 4))
                pb.start(10)
                _start_coast_timer()

            elif phase == CalibrationPhase.SUCCESS:
                _set_phase_led('coast', 'ok')
                _set_phase_led('result', 'ok')
                instr_var.set("✅  Calibrazione completata con successo!")
                instr_lbl.config(fg='#005500', bg='#E8F5E9')
                btn_start.config(state='normal', text='▶  Ripeti')
                btn_close.config(state='normal')
                _calib_running[0] = False
                logging.getLogger().info("[Calibrazione] Spin-down completato con successo.")

            elif phase == CalibrationPhase.FAILED:
                for key in ('ctrl', 'spinup', 'coast', 'result'):
                    if phase_leds[key].cget('fg') == _C_ACTIVE:
                        _set_phase_led(key, 'fail')
                _set_phase_led('result', 'fail')
                if banco_ok:
                    self._set_banco_speed(0)
                    banco_speed_var.set(0.0)
                    banco_status_var.set("■  Banco fermato (sicurezza)")
                    logging.getLogger().warning(
                        "[Calibrazione] Banco fermato per sicurezza dopo fallimento.")
                reason_map = {
                    'request_control_failed':    'Richiesta controllo fallita',
                    'spindown_cmd_failed':        'Comando spin-down rifiutato dal rullo',
                    'spinup_timeout':             'Timeout: velocità target non raggiunta in tempo',
                    'coastdown_timeout':          'Timeout: coast-down troppo lungo',
                }
                reason_raw = info.get('reason', 'errore sconosciuto')
                reason_txt = reason_map.get(reason_raw, reason_raw)
                instr_var.set(f"❌  Calibrazione fallita\n{reason_txt}")
                instr_lbl.config(fg='#880000', bg='#FFEBEE')
                btn_start.config(state='normal', text='▶  Riprova')
                btn_close.config(state='normal')
                _calib_running[0] = False

        def _on_phase(phase: CalibrationPhase, info: dict):
            """Callback dal loop BLE → rimanda sul main thread."""
            self.after(0, _apply_phase, phase, info)

        def _start_calib():
            if _calib_running[0]:
                return
            _calib_running[0] = True
            btn_start.config(state='disabled')
            btn_close.config(state='disabled')
            for key in phase_leds:
                _set_phase_led(key, 'idle')
            target_low_var.set("—")
            target_high_var.set("—")
            instr_var.set("Avvio in corso…")
            instr_lbl.config(fg='#1a1a2e', bg='#F0F4FF')
            self.executor.submit(_calib_worker)

        def _calib_worker():
            fut = self._run_ble(
                self.ble_manager.start_spindown_calibration(
                    status_callback=_on_phase,
                    timeout_ctrl=5.0,
                    timeout_spinup_request=60.0,
                    timeout_spinup=180.0,
                    timeout_coastdown=90.0,
                )
            )
            try:
                fut.result(timeout=400)
            except Exception as e:
                logging.getLogger().error(f"Errore calibrazione: {e}")
                self.after(0, _apply_phase,
                           CalibrationPhase.FAILED, {'reason': str(e)})

        def _on_close():
            _stop_speed_poll()
            _stop_coast_timer()
            pb.stop()
            if _calib_running[0] and banco_ok:
                self._set_banco_speed(0)
                logging.getLogger().warning(
                    "[Calibrazione] Finestra chiusa durante procedura — banco fermato.")
            win.destroy()

        btn_start.config(command=_start_calib)
        win.protocol("WM_DELETE_WINDOW", _on_close)

        # Polling velocità parte subito, indipendente dalla calibrazione
        _start_speed_poll()
    # ── Chiusura ──────────────────────────────────────────────────────────────

    def on_closing(self):
        if self.periodic_check_id:
            self.after_cancel(self.periodic_check_id);  self.periodic_check_id = None
        if self.lorenz_update_id:
            self.after_cancel(self.lorenz_update_id);   self.lorenz_update_id = None
        if self._ui_pulse_id:
            self.after_cancel(self._ui_pulse_id);       self._ui_pulse_id = None
        if self._rec_timer_id:
            self.after_cancel(self._rec_timer_id);      self._rec_timer_id = None
        if self._heartbeat_reset_id:
            self.after_cancel(self._heartbeat_reset_id); self._heartbeat_reset_id = None
        if self.psu_update_id:
            self.after_cancel(self.psu_update_id);      self.psu_update_id = None
        self._stop_serial_update()
        self._csv_panel.stop()

        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.title("Total Commander - Chiusura in corso...")

        shutdown_win = tk.Toplevel(self)
        shutdown_win.title("Chiusura")
        w, h = 300, 130
        shutdown_win.withdraw()
        self.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        if pw <= 1 or ph <= 1:
            x = (self.winfo_screenwidth()  - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        else:
            x = self.winfo_rootx() + (pw - w) // 2
            y = self.winfo_rooty() + (ph - h) // 2
        shutdown_win.geometry(f"{w}x{h}+{x}+{y}")

        status_var = tk.StringVar(value="Chiusura delle connessioni in corso...\nAttendere prego.")
        ttk.Label(shutdown_win, textvariable=status_var,
                  anchor="center", justify="center").pack(expand=True, padx=20, pady=(16, 6))
        pb = ttk.Progressbar(shutdown_win, mode='indeterminate', length=220)
        pb.pack(padx=20, pady=(0, 14), fill='x')
        pb.start(12)

        dots = [' ', '. ', '.. ', '...']
        idx  = [0]

        def _anim():
            status_var.set(f"Chiusura delle connessioni in corso{dots[idx[0]]}\nAttendere prego.")
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
        self._shutdown_pb  = pb
        self._shutdown_future = self.executor.submit(self._graceful_shutdown)
        self._poll_shutdown()

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
            self.data_processor.close()

            # 2. Disabilita notifiche FTMS prima di disconnettere BLE.
            #    Senza questo passo, disconnect_device() si blocca in attesa
            #    che Bleak chiuda il canale delle notifiche.
            if self.ble_manager.get_connection_status():
                if self.ble_manager.indoor_bike_data_notifications_enabled:
                    try:
                        self._run_ble(
                            self.ble_manager.disable_indoor_bike_data_notifications()
                        ).result(timeout=5)
                        logging.getLogger().info("Notifiche FTMS disabilitate (shutdown).")
                    except Exception as e:
                        logging.getLogger().warning(
                            f"Impossibile disabilitare notifiche FTMS: {e}")

            # 3. Disconnetti BLE — ora può uscire senza bloccarsi
            if self.ble_manager.get_connection_status():
                try:
                    self._run_ble(
                        self.ble_manager.disconnect_device()
                    ).result(timeout=10)
                except Exception as e:
                    logging.getLogger().error(f"Errore disconnessione BLE in shutdown: {e}")

            # 4. Chiudi gli altri dispositivi
            if self.lorenz_reader.connected:
                self.lorenz_reader.close_connection()
            if self.serial_reader.connected:
                self.serial_reader.close_connection()
            if self.modbus.is_connesso():
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
            self._shutdown_ble_loop(join_timeout=3.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    app = MainWindow()
    app.mainloop()