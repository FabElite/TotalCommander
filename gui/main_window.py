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
from logic.data_processing import DataProcessor
from logic import settings_manager

from gui.panels.status_bar      import StatusBar
from gui.panels.connections_bar import ConnectionsBar
from gui.panels.csv_panel       import CsvPanel
from gui.panels.live_data_panel import LiveDataPanel
from gui.panels.log_panel       import LogPanel


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Total Commander IV")
        self.geometry("1150x850")

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
        self.executor       = ThreadPoolExecutor(max_workers=5)

        # ── Stato connessioni (per rilevare disconnessioni inattese) ──────────
        self._ble_was_connected    = False
        self._lorenz_was_connected = False
        self._serial_was_connected = False
        self._modbus_was_connected = False
        self._connected_device_name    = None
        self._connected_device_address = None

        # ── Settings ──────────────────────────────────────────────────────────
        self.settings_file = "settings.json"
        self.delta_speed_thresholds_kmh = (1.0, 3.0)
        self.delta_power_thresholds_pct = (2.0, 5.0)
        self.delta_smoothing_window = 5
        self._rec_hz = 1
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
        self._heartbeat_reset_id = None
        self._last_packet_time   = None
        self._ui_pulse_id    = None
        self._rec_timer_id   = None
        self._latest_data    = {}
        self._shutdown_win    = None
        self._shutdown_anim_id = None
        self._shutdown_pb      = None

        # ── Layout root ───────────────────────────────────────────────────────
        self.grid_rowconfigure(0, weight=0)   # status bar
        self.grid_rowconfigure(1, weight=0)   # connections bar
        self.grid_rowconfigure(2, weight=1)   # content
        self.grid_rowconfigure(3, weight=0)   # log
        self.grid_columnconfigure(0, weight=1)

        # ── Pannelli ──────────────────────────────────────────────────────────
        self._status_bar = StatusBar(self)
        self._status_bar.grid(row=0, column=0, sticky="ew")

        self._conn_bar = ConnectionsBar(
            self, self.lorenz_reader,
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
            on_serial_connect    = self._serial_connect,
            on_serial_disconnect = self._serial_disconnect,
            on_com_toggle        = self._on_com_toggle,
        )
        self._conn_bar.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 2))

        # Content area (2 colonne)
        content = ttk.Frame(self)
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

        self._log_panel = LogPanel(self)
        self._log_panel.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.log_queue = self._log_panel.log_queue   # esposto per main.py

        # Aggiorna offset al primo avvio
        self._conn_bar.set_offset(self.lorenz_reader.offset)

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
        self._rec_hz = 1
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
            if not self._ble_was_connected:
                self.after(3000, self._auto_enable_ftms)
            self._ble_was_connected = True
        else:
            if self._ble_was_connected:
                self._on_ble_unexpected_disconnect()
            self._status_bar.set_ble('err')
            self._ble_was_connected = False

    def _auto_enable_ftms(self):
        if self.ble_manager.get_connection_status() and not self._live_panel.is_ftms_enabled():
            logging.getLogger().info("BLE connesso — abilito notifiche FTMS automaticamente.")
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
        self._status_bar.set_com('ok' if connected else 'err')
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
                logging.getLogger().info("Modbus connesso.")
            self._modbus_was_connected = True
        else:
            if self._modbus_was_connected:
                logging.getLogger().warning("=" * 55)
                logging.getLogger().warning("*** DISCONNESSIONE MODBUS - connessione persa ***")
                logging.getLogger().warning("=" * 55)
            elif from_user_action:
                logging.getLogger().warning("Modbus: nessuna connessione attiva da chiudere.")
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
        logging.getLogger().info(f"Connessione BLE a {address}...")
        fut = self._run_ble(self.ble_manager.connect_to_device(address, connection_timeout=15.0))
        try:
            if fut.result():
                self._connected_device_name    = name
                self._connected_device_address = address
                self.after(0, self._status_bar.set_device_info, name, address)
        except Exception as e:
            logging.getLogger().error(f"Errore connessione BLE: {e}")
        finally:
            self.after(0, self._conn_bar.set_progress, False)

    def _ble_disconnect(self):
        if not self.ble_manager.get_connection_status():
            logging.getLogger().info("Nessun dispositivo BLE connesso.")
            return
        self._conn_bar.set_progress(True)
        logging.getLogger().info("Disconnessione BLE...")
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
                logging.getLogger().info("Flush dati eseguito dopo disconnessione BLE.")
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
        logging.getLogger().info(f"Invio livello: {level}/200")
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
        logging.getLogger().info(f"Invio potenza: {power}W")
        try:
            self._run_ble(self.ble_manager.set_brake_power(power)).result()
        except Exception as e:
            logging.getLogger().error(f"Errore invio potenza: {e}")

    def _send_simulation(self, value):
        self.executor.submit(self._send_simulation_worker, value)

    def _send_simulation_worker(self, value):
        logging.getLogger().info(f"Invio simulazione: {value}%")
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
        if self._live_panel.is_ftms_enabled():
            logging.getLogger().info("Comandi automatici terminati, disabilito le notifiche dati.")
            self._toggle_ftms()

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
                logging.getLogger().info("Abilitate notifiche FTMS")
                self._status_bar.set_ftms(0)
                self.executor.submit(self._enable_ftms_worker)
            else:
                logging.getLogger().info("Nessun dispositivo connesso, FTMS non abilitabile")
        else:
            self._live_panel.set_ftms_button(False)
            self._live_panel.clear_ble()
            logging.getLogger().info("Disabilitate notifiche FTMS")
            self._reset_ftms_state()
            self.executor.submit(self._disable_ftms_worker)

    def _enable_ftms_worker(self):
        try:
            self._run_ble(
                self.ble_manager.enable_indoor_bike_data_notifications(self._on_ble_data)
            ).result()
        except Exception as e:
            logging.getLogger().error(f"Errore abilitazione FTMS: {e}")

    def _disable_ftms_worker(self):
        try:
            self._run_ble(self.ble_manager.disable_indoor_bike_data_notifications()).result()
            self.data_processor.flush()
            logging.getLogger().info("Flush dati eseguito dopo disabilitazione FTMS.")
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
        logging.getLogger().info("Connessione Lorenz...")
        self.executor.submit(self._lorenz_connect_worker)

    def _lorenz_connect_worker(self):
        try:
            port = trova_porta_usb_serial("Lorenz USB sensor interface Port")
            if port:
                ok = self.lorenz_reader.open_connection(int(port.split("COM")[-1]))
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
        logging.getLogger().info("Disconnessione Lorenz...")
        self._lorenz_was_connected = False
        self._stop_lorenz_update()
        self.executor.submit(self._lorenz_disconnect_worker)

    def _lorenz_disconnect_worker(self):
        ok = self.lorenz_reader.close_connection()
        msg = "Lorenz disconnesso." if ok else "Lorenz: nessuna connessione attiva."
        self.after(0, logging.getLogger().info if ok else logging.getLogger().warning, msg)

    def _lorenz_read_offset(self):
        self.lorenz_reader.read_offset()
        logging.getLogger().info(f"Offset letto: {self.lorenz_reader.offset}")
        self._conn_bar.set_offset(self.lorenz_reader.offset)
        self._save_settings()

    def _lorenz_avg_changed(self, value_str):
        try:
            new_avg = int(value_str)
            if new_avg > 0 and self.lorenz_reader.avg_dim != new_avg:
                self.lorenz_reader.avg_dim = new_avg
                logging.getLogger().info(f"Media Lorenz impostata a: {new_avg}")
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
        logging.getLogger().info(f"Inversione velocità Lorenz: {'Attiva' if inverted else 'Disattiva'}")
        self._save_settings()

    # ── Modbus / Banco ────────────────────────────────────────────────────────

    def _banco_connect(self, ip: str):
        logging.getLogger().info(f"Connessione Banco a {ip}...")
        self.executor.submit(self._banco_connect_worker, ip)

    def _banco_connect_worker(self, ip):
        try:
            self.modbus.connetti(ip, 502)
        except Exception as e:
            logging.getLogger().error(f"Errore connessione Banco: {e}")
        finally:
            self.after(0, self._check_modbus, True)

    def _banco_disconnect(self):
        logging.getLogger().info("Disconnessione Banco...")
        self.executor.submit(self._banco_disconnect_worker)

    def _banco_disconnect_worker(self):
        try:
            self._modbus_was_connected = False
            self.modbus.disconnetti()
        except Exception as e:
            logging.getLogger().error(f"Errore disconnessione Banco: {e}")
        finally:
            self.after(0, self._check_modbus, True)

    def _set_banco_speed(self, speedkmh):
        logging.getLogger().info(f"Velocità banco: {speedkmh} km/h")
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


    def _on_com_toggle(self, visible: bool):
        """Sincronizza visibilità COM tra ConnectionsBar e LiveDataPanel."""
        self._live_panel.set_com_visible(visible)

    def _serial_connect(self, port: str):
        if not port:
            logging.getLogger().warning("Seleziona una COM port prima di connettere.")
            return
        logging.getLogger().info(f"Connessione sensore su {port}...")
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
        self._live_panel.update_serial(data)
        self.serial_update_id = self.after(500, self._serial_update_tick)

    def _stop_serial_update(self):
        if self.serial_update_id is not None:
            self.after_cancel(self.serial_update_id)
            self.serial_update_id = None

    def _serial_disconnect(self):
        logging.getLogger().info("Disconnessione sensore seriale...")
        self._serial_was_connected = False
        self._stop_serial_update()
        self.executor.submit(self._serial_disconnect_worker)

    def _serial_disconnect_worker(self):
        ok = self.serial_reader.close_connection()
        msg = "Sensore seriale disconnesso." if ok else "Sensore: nessuna connessione attiva."
        self.after(0, logging.getLogger().info if ok else logging.getLogger().warning, msg)

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

        ts_preview = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')

        ttk.Label(win, text="Nome sessione (opzionale):",
                  font=('Helvetica', 9, 'bold')
                  ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky='w')

        name_entry = ttk.Entry(win, width=30)
        name_entry.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 4), sticky='ew')
        name_entry.focus()

        preview_var = tk.StringVar(value=f"{ts_preview}_bike_data.xlsx")
        ttk.Label(win, text="File:").grid(row=2, column=0, padx=(16, 4), pady=(4, 2), sticky='e')
        ttk.Label(win, textvariable=preview_var, foreground='#0055aa',
                  font=('Helvetica', 8)
                  ).grid(row=2, column=1, padx=(0, 16), pady=(4, 2), sticky='w')

        def _update_preview(*_):
            ts = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
            raw = name_entry.get().strip().replace(' ', '_')
            fname = f"{ts}_{raw}_bike_data.xlsx" if raw else f"{ts}_bike_data.xlsx"
            preview_var.set(fname)

        name_entry.bind('<KeyRelease>', _update_preview)

        err_var = tk.StringVar()
        ttk.Label(win, textvariable=err_var, foreground='#CC0000',
                  font=('Helvetica', 8)
                  ).grid(row=3, column=0, columnspan=2, padx=16, pady=(2, 0))

        def _start():
            try:
                self.data_processor.start_session(name_entry.get())
            except Exception as e:
                err_var.set(str(e))
                return
            fname = os.path.basename(self.data_processor.xlsx_filename)
            self._conn_bar.set_rec_state(True, fname)
            self._status_bar.set_rec(True)
            self._rec_tick()
            logging.getLogger().info(f"Registrazione avviata: {fname}")
            win.destroy()

        bf = ttk.Frame(win)
        bf.grid(row=4, column=0, columnspan=2, pady=(8, 14))
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
        file_menu.add_command(label="File dati corrente",
                              command=self._menu_show_current_file)
        file_menu.add_separator()
        file_menu.add_command(label="Apri cartella output",
                              command=lambda: self._open_working_directory(
                                  os.path.join(self._get_application_path(), 'output')))

        # ── Impostazioni ─────────────────────────────────────────────────────
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Impostazioni", menu=settings_menu)
        settings_menu.add_command(label="Parametri delta e smoothing…",
                                  command=self._menu_open_settings)

        # ── Visualizza ───────────────────────────────────────────────────────
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Visualizza", menu=view_menu)
        view_menu.add_command(label="Mostra/Nascondi pannello COM",
                              command=self._menu_toggle_com)

        # ── Info ─────────────────────────────────────────────────────────────
        info_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Info", menu=info_menu)
        info_menu.add_command(label="Guida all'uso…",
                              command=self._menu_show_info)

    # ── Azioni menu File ──────────────────────────────────────────────────────

    def _menu_flush_data(self):
        if not self.data_processor.is_recording:
            logging.getLogger().warning("Nessuna sessione attiva — flush non necessario.")
            return
        self.data_processor.flush()
        logging.getLogger().info("Flush manuale dati eseguito.")

    def _menu_show_current_file(self):
        if not self.data_processor.xlsx_filename:
            import tkinter.messagebox as mb
            mb.showinfo("File dati corrente", "Nessuna sessione attiva.")
            return
        fname = os.path.basename(self.data_processor.xlsx_filename)
        fpath = os.path.abspath(self.data_processor.xlsx_filename)
        win = tk.Toplevel(self)
        win.title("File dati corrente")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        ttk.Label(win, text="File in uso:", font=('Helvetica', 9, 'bold')
                  ).pack(padx=20, pady=(16, 4))
        ttk.Label(win, text=fname, foreground='#0055aa'
                  ).pack(padx=20, pady=(0, 4))
        ttk.Label(win, text=fpath, foreground='#555555', font=('Helvetica', 8),
                  wraplength=420, justify='center'
                  ).pack(padx=20, pady=(0, 12))
        ttk.Button(win, text="Chiudi", command=win.destroy
                   ).pack(pady=(0, 14))

    # ── Azioni menu Impostazioni ──────────────────────────────────────────────

    def _menu_open_settings(self):
        win = tk.Toplevel(self)
        win.title("Parametri delta e smoothing")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

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
        ttk.Label(win, text="default: 1").grid(row=13, column=0, columnspan=3,
                                               sticky='w', padx=24, pady=(0, 4))

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
            logging.getLogger().info(
                f"Settings updated - spd ({s1},{s2}) km/h | pwr ({p1},{p2})% | N={n} | REC {hz}Hz")

        bf = ttk.Frame(win)
        bf.grid(row=15, column=0, columnspan=3, pady=(8, 14))
        ttk.Button(bf, text="Applica", command=_apply).grid(
            row=0, column=0, padx=6)
        ttk.Button(bf, text="Annulla", command=win.destroy).grid(
            row=0, column=1, padx=6)

    # ── Azioni menu Visualizza ────────────────────────────────────────────────

    def _menu_toggle_com(self):
        new_state = not self._conn_bar._com_visible
        self._conn_bar.set_com_visible(new_state)
        self._on_com_toggle(new_state)

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

        h2("UI  (primo LED a sinistra)")
        body("Pulsa ogni 500 ms. Finché alterna colore e il contatore sale, "
             "l'interfaccia è attiva e risponde. Se si blocca su un colore fisso "
             "significa che il programma è congelato.")

        h2("BLE / Lorenz / Banco / COM")
        body("Verde = dispositivo connesso e raggiungibile. "
             "Rosso = non connesso o connessione persa. "
             "La perdita improvvisa viene segnalata anche nel log.")

        h2("HB — Heartbeat dati")
        body("Mostra la frequenza (Hz) con cui arrivano i pacchetti dati dal "
             "trainer BLE. Attivo solo quando le notifiche FTMS sono abilitate. "
             "Si spegne automaticamente se i dati si interrompono per più di 2 secondi.")

        h2("Auto")
        body("Verde = sequenza automatica da CSV in esecuzione. "
             "Spento = nessuna sequenza attiva.")

        h1("● Barra Connessioni")

        h2("BLE")
        body("Cerca i dispositivi Bluetooth nelle vicinanze, seleziona il trainer "
             "dalla lista e premi Connetti. La barra di avanzamento indica che "
             "un'operazione è in corso. Una volta connesso, le notifiche FTMS "
             "vengono abilitate automaticamente dopo 3 secondi.")

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
             "il tempo indicato tra uno e l'altro. Al termine, le notifiche FTMS "
             "vengono disabilitate automaticamente.")

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
             "opzionale per la sessione. Il file verrà creato nella cartella 'output/' "
             "con nome YYYYMMDD_HHMMSS_nome_bike_data.xlsx, ordinato cronologicamente "
             "in automatico. Premere ⏹ STOP per terminare la sessione con flush finale garantito. "
             "È possibile avviare più sessioni consecutive senza riavviare il programma.")
        body("Il salvataggio avviene automaticamente ogni 30 secondi. Se il file supera "
             "100 MB viene creato un nuovo file (_part02, _part03…) con la stessa intestazione. "
             "Per forzare il salvataggio immediato usare File → Forza salvataggio dati. "
             "La frequenza di registrazione (default 1 Hz) è configurabile da "
             "Impostazioni → Parametri delta.")

        # ── Pulsante chiudi ────────────────────────────────────────────────
        ttk.Button(win, text="Chiudi", command=win.destroy
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

        except Exception as e:
            logging.getLogger().error(f"Errore durante lo spegnimento: {e}")
        finally:
            self._shutdown_ble_loop(join_timeout=3.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    app = MainWindow()
    app.mainloop()