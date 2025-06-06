import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor
import logging
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager  # Assuming these are correct
from shared_lib.LorenzLib import LorenzReader  # Assuming this is correct
from shared_lib.funzioni_accessorie import trova_porta_usb_serial  # Assuming this is correct
from shared_lib.modbus_utils import ModbusBancoCollaudo  # Assuming this is correct
from logic.data_processing import DataProcessor
from tkinter import filedialog


class TextHandler(logging.Handler):
    """Custom logging handler that sends log messages to a Tkinter Text widget."""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.config(state='normal')
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.config(state='disabled')
        self.text_widget.yview(tk.END)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.lorenz_update_id = None
        self.title("Total Commander")
        self.geometry("1350x760")
        self.worker = AsyncioWorker()
        self.worker.start()
        self.ble_manager = BLEManager(self.worker)
        self.data_processor = DataProcessor()
        self.modbus = ModbusBancoCollaudo()
        self.executor = ThreadPoolExecutor(max_workers=1)  # Max workers = 1 serializes submitted tasks
        self.auto_commands_running = False

        # Frame principale
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=0, sticky="nsew")

        # Frame sinistro per ricerca, stato connessione e comandi
        self.left_frame = ttk.Frame(self.main_frame)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=10)
        self.left_frame.grid_columnconfigure(0, weight=1)

        # Frame per la ricerca e la connessione
        self.frame_search = ttk.LabelFrame(self.left_frame, text="Ricerca Dispositivi BLE")
        self.frame_search.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.frame_search.grid_columnconfigure(0, weight=1)

        self.device_list = tk.Listbox(self.frame_search)
        self.device_list.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
        self.btn_search = ttk.Button(self.frame_search, text="Cerca Dispositivi", command=self.search_devices)
        self.btn_search.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        self.btn_connect = ttk.Button(self.frame_search, text="Connetti", command=self.connect_device)
        self.btn_connect.grid(row=2, column=0, sticky="ew", padx=10, pady=2)
        self.btn_disconnect = ttk.Button(self.frame_search, text="Disconnetti", command=self.disconnect_device)
        self.btn_disconnect.grid(row=3, column=0, sticky="ew", padx=10, pady=4)

        # Frame per lo stato della connessione
        self.frame_status = ttk.LabelFrame(self.left_frame, text="Stato Connessione")
        self.frame_status.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.frame_status.grid_columnconfigure(0, weight=1)
        self.frame_status.grid_columnconfigure(1, weight=1)
        self.connection_status = tk.Label(self.frame_status, text="Non Connesso", fg="red")
        self.connection_status.grid(row=0, column=0, padx=5, pady=10)
        self.progress = ttk.Progressbar(self.frame_status, mode='indeterminate')
        self.progress.grid(row=0, column=1, columnspan=2, sticky="ew", padx=10, pady=10)

        # Frame per i comandi manuali
        self.frame_commands = ttk.LabelFrame(self.left_frame, text="Comandi manuali")
        self.frame_commands.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        self.create_command_controls()

        # Frame contenitore per la seconda colonna
        self.middle_left_frame = ttk.Frame(self.main_frame)
        self.middle_left_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.middle_left_frame.grid_rowconfigure(0, weight=1)  # Allow commands_table to expand
        self.middle_left_frame.grid_columnconfigure(0, weight=1)

        # Frame comandi da CSV
        self.automatic_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi da CSV")
        self.automatic_commands.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)  # Changed from middle_left_frame
        self.automatic_commands.grid_rowconfigure(0, weight=1)
        self.automatic_commands.grid_columnconfigure(0, weight=1)

        self.scrollbar = ttk.Scrollbar(self.automatic_commands, orient="vertical")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.commands_table = ttk.Treeview(self.automatic_commands,
                                           columns=("Comando", "Valore", "Tempo [s]", "Vel Banco [km/h]"),
                                           show='headings',
                                           yscrollcommand=self.scrollbar.set)
        self.commands_table.heading("Comando", text="Comando")
        self.commands_table.heading("Valore", text="Valore")
        self.commands_table.heading("Tempo [s]", text="Tempo [s]")
        self.commands_table.heading("Vel Banco [km/h]", text="Vel Banco [km/h]")
        self.commands_table.column("Comando", width=100)
        self.commands_table.column("Valore", width=100)
        self.commands_table.column("Tempo [s]", width=100)
        self.commands_table.column("Vel Banco [km/h]", width=100)
        self.commands_table.grid(row=0, column=0, sticky="nsew", padx=(10, 0),
                                 pady=10)  # padx to prevent overlap with scrollbar
        self.scrollbar.config(command=self.commands_table.yview)
        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')

        # Frame per i comandi automatici
        self.frame_auto_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi automatici")
        self.frame_auto_commands.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        self.frame_auto_commands.grid_columnconfigure(0, weight=1)
        self.frame_auto_commands.grid_columnconfigure(1, weight=1)
        self.led_status = tk.Label(self.frame_auto_commands, text="Comandi Automatici: OFF", fg="red")
        self.led_status.grid(row=1, column=0, padx=10, pady=5)
        self.btn_load_commands = ttk.Button(self.frame_auto_commands, text="Carica Comandi da CSV",
                                            command=self.load_commands_from_csv)
        self.btn_load_commands.grid(row=0, column=1, padx=10, pady=2)
        self.btn_auto_commands = ttk.Button(self.frame_auto_commands, text="Lancia Comandi Automatici",
                                            command=self.launch_auto_commands)
        self.btn_auto_commands.grid(row=1, column=1, padx=10, pady=2)
        self.btn_stop_auto_commands = ttk.Button(self.frame_auto_commands, text="Ferma Comandi Automatici",
                                                 command=self.stop_auto_commands)
        self.btn_stop_auto_commands.grid(row=2, column=1, padx=10, pady=2)

        # Frame destro per la visualizzazione dei dati BLE
        self.frame_data = ttk.LabelFrame(self.main_frame, text="Dati BLE FTMS")
        self.frame_data.grid(row=0, column=2, sticky="nsew", padx=10, pady=5)
        self.create_data_fields()

        self.right_frame = ttk.Frame(self.main_frame)
        self.right_frame.grid(row=0, column=3, sticky="nsew", padx=10, pady=10)
        self.create_lorenz_controls()
        self.create_banco_controls()

        # Frame per il log delle attività
        self.frame_log = ttk.LabelFrame(self, text="Log delle Attività")
        self.frame_log.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=10, pady=10)
        self.frame_log.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(self.frame_log, state='disabled', height=13)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.periodic_connection_check()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_command_controls(self):
        commands = [("Livello [/200]", self.send_level_command), ("Potenza [W]", self.send_power_command),
                    ("Simulazione [%]", self.send_simulation_command)]
        self.frame_commands.grid_columnconfigure(0, weight=2)
        self.frame_commands.grid_columnconfigure(1, weight=1)
        self.frame_commands.grid_columnconfigure(2, weight=1)
        for i, (label, command) in enumerate(commands):
            lbl = ttk.Label(self.frame_commands, text=label)
            lbl.grid(row=i, column=0, padx=5, sticky="ew")
            entry = ttk.Entry(self.frame_commands)
            entry.grid(row=i, column=1, padx=5, sticky="ew")
            if "Livello" in label:
                self.livello_entry = entry
            elif "Potenza" in label:
                self.potenza_entry = entry
            elif "Simulazione" in label:
                self.simulazione_entry = entry
            btn = ttk.Button(self.frame_commands, text="Invia", command=command)
            btn.grid(row=i, column=2, padx=5, sticky="ew")

    def create_data_fields(self):
        fields = ["power", "cadence", "speed", "resistance", "total_distance", "elapsed_time"]
        self.data_entries = {}
        self.data_controls = ttk.Frame(self.frame_data)
        self.data_controls.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        for i, field in enumerate(fields):
            frame = ttk.Frame(self.data_controls)
            frame.grid(row=i, column=0, sticky="e", padx=5, pady=5)
            lbl = ttk.Label(frame, text=field.capitalize())
            lbl.grid(row=0, column=0, padx=5)
            entry = ttk.Entry(frame, state='readonly', justify='right')
            entry.grid(row=0, column=1, padx=5)
            self.data_entries[field.lower().replace(" ", "_")] = entry
        self.btn_toggle_data = ttk.Button(self.data_controls, text="Abilita Dati", command=self.toggle_data)
        self.btn_toggle_data.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=5)

    def periodic_connection_check(self):
        self.worker.run_coroutine(self._async_check_ble_status())
        self._check_and_update_modbus_status()
        self.after(1000, self.periodic_connection_check)

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

    def search_devices(self):
        logging.getLogger().info("Richiesta ricerca dispositivi")
        self.progress.start()
        self.btn_search.config(state=tk.DISABLED)
        self.executor.submit(self._search_devices)

    def _search_devices(self):
        devices = {}
        try:
            devices = self.worker.run_coroutine(self.ble_manager.scan_devices(timeout=5)).result()
        except Exception as e:
            logging.getLogger().error(f"Errore durante la scansione BLE: {e}")
        finally:
            self.after(0, self._update_device_list_ui, devices)

    def _update_device_list_ui(self, devices):
        self.device_list.delete(0, tk.END)
        for address, (name, rssi) in devices.items():
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
            if rssi > -50:  # Note: Typically higher RSSI (less negative) is better.
                # If you want to highlight strong signals, this is okay.
                # If you meant weak signals (e.g. < -70), adjust the condition.
                self.device_list.itemconfig(tk.END, {'bg': 'lightcoral'})  # Assuming lightcoral for > -50 RSSI
            logging.getLogger().info(f"Dispositivo trovato: {name} - {address} - RSSI: {rssi}")
        self.progress.stop()
        self.btn_search.config(state=tk.NORMAL)

    def connect_device(self):
        selected_device_index = self.device_list.curselection()
        if not selected_device_index:
            logging.getLogger().warning("Nessun dispositivo selezionato per la connessione.")
            return
        self.progress.start()
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.executor.submit(self._connect_device, self.device_list.get(selected_device_index[0]))

    def _connect_device(self, selected_device_string):
        # selected_device = self.device_list.get(tk.ACTIVE) # This is not thread-safe
        success = False
        if selected_device_string:
            try:
                address = selected_device_string.split(" - ")[1]
                logging.getLogger().info(f"Tentativo connessione a {address}")
                self.worker.run_coroutine(self.ble_manager.connect_to_device(address)).result()
                success = True  # Assume success if no exception
            except Exception as e:
                logging.getLogger().error(f"Errore durante la connessione BLE a {selected_device_string}: {e}")
                success = False

        self.after(0, self._update_connect_device_ui, success)

    def _update_connect_device_ui(self, success):
        self.progress.stop()
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.NORMAL)
        # Status update is handled by periodic_connection_check

    def disconnect_device(self):
        self.progress.start()
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.DISABLED)
        logging.getLogger().info("Richiesta Disconnessione")
        self.executor.submit(self._disconnect_device)

    def _disconnect_device(self):
        disconnected = False
        try:
            disconnected = self.worker.run_coroutine(self.ble_manager.disconnect_device()).result()
        except Exception as e:
            logging.getLogger().error(f"Errore durante la disconnessione BLE: {e}")

        self.after(0, self._update_disconnect_device_ui, disconnected)

    def _update_disconnect_device_ui(self, disconnected):
        if disconnected:
            self.connection_status.config(text="Non Connesso", fg="red")  # Immediate feedback
        self.progress.stop()
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.NORMAL)

    def send_level_command(self, level=None):
        if level is None: level = self.livello_entry.get()
        if level:
            self.executor.submit(self._send_level_command, level)
        else:
            logging.getLogger().warning("Livello non specificato.")

    def _send_level_command(self, level):
        try:
            logging.getLogger().info(f"Invio comando livello: {level}/200")
            self.worker.run_coroutine(self.ble_manager.set_brake_percentage(int(level)))
        except Exception as e:
            logging.getLogger().error(f"Errore invio comando livello: {e}")

    def send_power_command(self, power=None):
        if power is None: power = self.potenza_entry.get()
        if power:
            self.executor.submit(self._send_power_command, power)
        else:
            logging.getLogger().warning("Potenza non specificata.")

    def _send_power_command(self, power):
        try:
            logging.getLogger().info(f"Invio comando potenza: {power}W")
            self.worker.run_coroutine(self.ble_manager.set_brake_power(int(power)))
        except Exception as e:
            logging.getLogger().error(f"Errore invio comando potenza: {e}")

    def send_simulation_command(self, simulation=None):
        if simulation is None: simulation = self.simulazione_entry.get()
        if simulation:
            self.executor.submit(self._send_simulation_command, simulation)
        else:
            logging.getLogger().warning("Simulazione non specificata.")

    def _send_simulation_command(self, simulation):
        try:
            logging.getLogger().info(f"Invio comando simulazione: {simulation}%")
            self.worker.run_coroutine(self.ble_manager.set_brake_simulation(grade=int(simulation)))
        except Exception as e:
            logging.getLogger().error(f"Errore invio comando simulazione: {e}")

    def toggle_data(self):
        if self.btn_toggle_data.cget('text') == 'Abilita Dati':
            self.btn_toggle_data.config(text='Disabilita Dati')
            logging.getLogger().info("Dati BLE abilitati")
            self.worker.run_coroutine(self.ble_manager.enable_indoor_bike_data_notifications(self.update_data_fields))
        else:
            self.btn_toggle_data.config(text='Abilita Dati')
            self.worker.run_coroutine(self.ble_manager.disable_indoor_bike_data_notifications())

    def update_data_fields(self, bike_data):
        for key, value in bike_data.items():
            if value is not None and key in self.data_entries:  # Check if key exists
                self.data_entries[key.replace(" ", "_")].config(state='normal')
                self.data_entries[key.replace(" ", "_")].delete(0, tk.END)
                self.data_entries[key.replace(" ", "_")].insert(0, str(value))
                self.data_entries[key.replace(" ", "_")].config(state='readonly')

        lorenz_data = {}
        if self.lorenz_reader and self.lorenz_reader.is_connected():  # Check if Lorenz reader is initialized and connected
            lorenz_data = self.lorenz_reader.get_data()
        else:  # Provide default empty Lorenz data if not connected
            lorenz_data = {"speed_avg": None, "torque_lorenz": None, "power_lorenz": None, "offset_lorenz": None}

        combined_data = {**bike_data, **lorenz_data}
        self.data_processor.handle_bike_data(combined_data)

    def load_commands_from_csv(self):
        if self.auto_commands_running:
            logging.getLogger().warning("Comandi automatici in corso. Impossibile caricare il file CSV.")
            return
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            for item in self.commands_table.get_children(): self.commands_table.delete(item)
            commands = DataProcessor.read_brake_commands_from_csv(file_path)
            for i, command in enumerate(commands):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                self.commands_table.insert("", "end", values=command, tags=(tag,))

    def launch_auto_commands(self):
        if not self.commands_table.get_children():
            logging.getLogger().info("La tabella dei comandi è vuota.")
            return
        if self.auto_commands_running:
            logging.getLogger().info("Comandi automatici già in corso.")
            return

        commands = [self.commands_table.item(item, 'values') for item in self.commands_table.get_children()]
        command_items = self.commands_table.get_children()
        for index, item in enumerate(command_items):
            self.commands_table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

        def send_next_command(index):
            if index < len(commands) and self.auto_commands_running:
                command_type, value, wait_time, speed_banco = commands[index]
                try:
                    wait_time = int(float(wait_time))  # More robust conversion
                except ValueError:
                    logging.error(f"Tempo di attesa non valido: {wait_time} per comando {index}. Interruzione.")
                    self.stop_auto_commands()  # Stop if wait_time is invalid
                    return

                if index > 0: self.commands_table.item(command_items[index - 1],
                                                       tags=('evenrow' if (index - 1) % 2 == 0 else 'oddrow',))
                self.commands_table.item(command_items[index], tags=('currentrow',))

                if command_type == "potenza":
                    self.send_power_command(value)
                elif command_type == "livelli":
                    self.send_level_command(value)
                elif command_type == "simulazione":
                    self.send_simulation_command(value)

                if speed_banco is not None and speed_banco.lower() != "none" and speed_banco.strip() != "":
                    try:
                        self.setspeed_modbus(float(speed_banco))
                    except ValueError:
                        logging.error(f"Velocità banco non valida: {speed_banco}")
                else:
                    logging.info("Nessuna impostazione velocità banco per questo comando.")

                self.auto_command_id = self.after(wait_time * 1000, lambda: send_next_command(index + 1))
            else:
                self.auto_commands_running = False
                self.led_status.config(text="Comandi Automatici: Completati", fg="blue")
                if command_items and index > 0:  # Ensure last command highlighting is removed if loop completed
                    self.commands_table.item(command_items[min(index, len(command_items) - 1)], tags=(
                    'evenrow' if (min(index, len(command_items) - 1)) % 2 == 0 else 'oddrow',))
                logging.getLogger().info("Comandi automatici completati")

        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')
        self.auto_commands_running = True
        self.led_status.config(text="Comandi Automatici: ON", fg="green")
        send_next_command(0)

    def stop_auto_commands(self):
        if self.auto_commands_running:
            self.auto_commands_running = False
            self.led_status.config(text="Comandi Automatici: OFF", fg="red")
            if hasattr(self, 'auto_command_id') and self.auto_command_id:
                self.after_cancel(self.auto_command_id)
                self.auto_command_id = None
            logging.getLogger().info("Comandi automatici interrotti")
            for item_id in self.commands_table.get_children():  # Use item_id
                if 'currentrow' in self.commands_table.item(item_id, 'tags'):
                    index = self.commands_table.index(item_id)
                    self.commands_table.item(item_id, tags=('evenrow' if index % 2 == 0 else 'oddrow',))
                    break
        else:
            logging.getLogger().info("Non ci sono comandi automatici attivi")

    def create_lorenz_controls(self):
        self.frame_lorenz = ttk.LabelFrame(self.right_frame, text="Gestione Lorenz")
        self.frame_lorenz.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.lorenz_reader = LorenzReader()  # Make sure LorenzReader has an is_connected() method
        self.lorenz_controls = ttk.Frame(self.frame_lorenz)
        self.lorenz_controls.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.lorenz_status = tk.Label(self.lorenz_controls, text="Lorenz: Non Connesso", fg="red")
        self.lorenz_status.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        self.btn_connect_lorenz = ttk.Button(self.lorenz_controls, text="Connetti Lorenz",
                                             command=self.initiate_lorenz_connection)
        self.btn_connect_lorenz.grid(row=1, column=0, padx=5, pady=5)

        self.btn_disconnect_lorenz = ttk.Button(self.lorenz_controls, text="Disconnetti Lorenz",
                                                command=self.disconnect_lorenz, state=tk.DISABLED)
        self.btn_disconnect_lorenz.grid(row=1, column=1, padx=5, pady=5)

        self.btn_read_offset = ttk.Button(self.lorenz_controls, text="Leggi Offset",
                                          command=self.initiate_read_lorenz_offset, state=tk.DISABLED)
        self.btn_read_offset.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        self.offset_label = self.create_labeled_entry(self.lorenz_controls, "Offset", 3)
        self.speed_avg_label = self.create_labeled_entry(self.lorenz_controls, "Speed Avg", 4)
        self.torque_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Torque Lorenz", 5)
        self.power_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Power Lorenz", 6)

    def create_banco_controls(self):
        self.banco_controls = ttk.LabelFrame(self.right_frame, text="Gestione Banco")
        self.banco_controls.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        lbl_ip = ttk.Label(self.banco_controls, text="PORTA IP:")
        lbl_ip.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.entry_ip = ttk.Entry(self.banco_controls, width=12);
        self.entry_ip.insert(0, "192.168.0.10")
        self.entry_ip.grid(row=0, column=1, padx=5, pady=5)
        self.btn_connect_banco = ttk.Button(self.banco_controls, text="Connetti",
                                            command=self.clicked_button_connection_modbus)
        self.btn_connect_banco.grid(row=1, column=0, padx=5, pady=5)
        self.banco_status = tk.Label(self.banco_controls, text="Non Connesso", fg="red")
        self.banco_status.grid(row=1, column=1, padx=5, pady=5)
        self.btn_set_speed = ttk.Button(self.banco_controls, text="Set Velocità [km/h]:",
                                        command=self.clicked_button_setspeed_modbus)
        self.btn_set_speed.grid(row=2, column=0, padx=5, pady=5)
        self.speed_banco_entry = ttk.Entry(self.banco_controls, width=12)
        self.speed_banco_entry.grid(row=2, column=1, padx=5, pady=5)
        self.btn_zero_speed = ttk.Button(self.banco_controls, text="ZERO SPEED",
                                         command=lambda: self.setspeed_modbus(0))
        self.btn_zero_speed.grid(row=4, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

    def create_labeled_entry(self, parent, label_text, row):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0, sticky="e", padx=5, pady=2)
        entry = ttk.Entry(parent, width=15, state='readonly', justify='right')
        entry.grid(row=row, column=1, padx=5, pady=2)
        return entry

    def update_lorenz_data(self):
        if not (self.lorenz_reader and self.lorenz_reader.is_connected()):
            # Ensure we don't try to get data if not connected or reader not init
            if self.lorenz_update_id:  # If update was running, stop it
                self.after_cancel(self.lorenz_update_id)
                self.lorenz_update_id = None
            return

        data = self.lorenz_reader.get_data()
        values = {
            self.speed_avg_label: data.get("speed_avg"),
            self.torque_lorenz_label: data.get("torque_lorenz"),
            self.power_lorenz_label: data.get("power_lorenz"),
            self.offset_label: data.get("offset_lorenz"),
        }
        for entry, val in values.items():
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.insert(0, f"{val:.2f}" if isinstance(val, (int, float)) else "N/A")
            entry.config(state='readonly')

    def initiate_lorenz_connection(self):
        logging.getLogger().info("Avvio connessione Lorenz...")
        self.btn_connect_lorenz.config(state=tk.DISABLED)
        self.btn_disconnect_lorenz.config(state=tk.DISABLED)  # Disable disconnect during connection attempt
        self.executor.submit(self._execute_lorenz_connection)

    def _execute_lorenz_connection(self):
        porta_com_lorenz = trova_porta_usb_serial("Lorenz USB sensor interface Port")
        success = False
        if porta_com_lorenz:
            try:
                logging.getLogger().info(f"Trovata porta Lorenz: {porta_com_lorenz}")
                success = self.lorenz_reader.open_connection(int(porta_com_lorenz.split("COM")[-1]))
            except Exception as e:
                logging.getLogger().error(f"Errore durante la connessione al Lorenz: {e}")
                success = False
        else:
            logging.getLogger().warning("Porta Lorenz non trovata.")
        self.after(0, self._update_lorenz_ui_after_connection, success)

    def _update_lorenz_ui_after_connection(self, success):
        if success:
            self.lorenz_status.config(text="Lorenz: Connesso", fg="green")
            logging.getLogger().info("Lorenz Connesso")
            self.btn_connect_lorenz.config(state=tk.DISABLED)
            self.btn_disconnect_lorenz.config(state=tk.NORMAL)
            self.btn_read_offset.config(state=tk.NORMAL)
            self.start_lorenz_update()
        else:
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            logging.getLogger().warning("Impossibile connettersi al Lorenz.")
            self.btn_connect_lorenz.config(state=tk.NORMAL)  # Re-enable connect button if failed
            self.btn_disconnect_lorenz.config(state=tk.DISABLED)
            self.btn_read_offset.config(state=tk.DISABLED)
            self.clear_lorenz_data_fields()  # Clear data if connection failed

    def start_lorenz_update(self):
        if self.lorenz_reader and self.lorenz_reader.is_connected():
            try:
                self.update_lorenz_data()
                self.lorenz_update_id = self.after(500, self.start_lorenz_update)
            except Exception as e:
                logging.getLogger().error(f"Errore durante aggiornamento Lorenz: {e}")
                self.disconnect_lorenz()  # Attempt to disconnect if updates fail
        else:  # Stop if not connected
            self.stop_lorenz_update()

    def stop_lorenz_update(self):
        if self.lorenz_update_id is not None:
            self.after_cancel(self.lorenz_update_id)
            self.lorenz_update_id = None
            logging.getLogger().info("Aggiornamento dati Lorenz fermato.")

    def disconnect_lorenz(self):
        # Consider running close_connection in a thread if it can block
        # For now, assuming it's quick.
        if self.lorenz_reader and self.lorenz_reader.is_connected():
            if self.lorenz_reader.close_connection():
                logging.getLogger().info("Lorenz Disconnesso")
            else:
                logging.getLogger().warning("Problema durante la disconnessione del Lorenz.")
        else:
            logging.getLogger().info("Lorenz già disconnesso o non inizializzato.")

        self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
        self.stop_lorenz_update()
        self.btn_connect_lorenz.config(state=tk.NORMAL)
        self.btn_disconnect_lorenz.config(state=tk.DISABLED)
        self.btn_read_offset.config(state=tk.DISABLED)
        self.clear_lorenz_data_fields()

    def clear_lorenz_data_fields(self):
        # Method to clear Lorenz data fields
        na_fields = [self.offset_label, self.speed_avg_label, self.torque_lorenz_label, self.power_lorenz_label]
        for entry_widget in na_fields:
            if entry_widget:  # Check if widget exists
                entry_widget.config(state='normal')
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, "N/A")
                entry_widget.config(state='readonly')

    def initiate_read_lorenz_offset(self):
        if self.lorenz_reader and self.lorenz_reader.is_connected():
            logging.getLogger().info("Avvio lettura offset Lorenz...")
            self.btn_read_offset.config(state=tk.DISABLED)
            self.executor.submit(self._execute_read_lorenz_offset)
        else:
            logging.getLogger().warning("Lorenz non connesso. Impossibile leggere l'offset.")

    def _execute_read_lorenz_offset(self):
        success = False
        try:
            # Assuming read_offset() updates an internal value picked up by get_data()
            self.lorenz_reader.read_offset()
            logging.getLogger().info(f"Comando lettura offset Lorenz inviato.")
            success = True
            # The periodic update_lorenz_data will show the new offset.
            # If immediate update is desired and read_offset returns the value or get_data can be called:
            # new_offset_data = self.lorenz_reader.get_data() # Or specific call for offset
            # self.after(0, self.update_lorenz_data) # Force an immediate refresh of all lorenz data
        except Exception as e:
            logging.getLogger().error(f"Errore durante la lettura dell'offset Lorenz: {e}")

        # Re-enable button via main thread
        self.after(0, self._finalize_read_lorenz_offset, success)

    def _finalize_read_lorenz_offset(self, success):
        self.btn_read_offset.config(state=tk.NORMAL)
        if success:
            # Force an update to reflect new offset if necessary
            # This ensures the UI shows the new offset value quickly.
            if self.lorenz_reader and self.lorenz_reader.is_connected():
                self.update_lorenz_data()
        else:
            logging.getLogger().warning("Lettura offset Lorenz fallita o Lorenz non connesso.")

    def clicked_button_connection_modbus(self):
        # This could also benefit from threading if connection is slow,
        # but typically Modbus/TCP connections are faster than serial.
        if not self.modbus.is_connesso():
            self.modbus.connetti(self.entry_ip.get(), 502)
        else:
            self.modbus.disconnetti()
        self._check_and_update_modbus_status()  # Update UI immediately

    def clicked_button_setspeed_modbus(self):
        try:
            speed_val = self.speed_banco_entry.get()
            if not speed_val:
                logging.warning("Velocità banco non specificata.")
                return
            self.setspeed_modbus(float(speed_val))  # Use float for more flexibility
        except ValueError:
            logging.error(f"Valore velocità banco non valido: {self.speed_banco_entry.get()}")

    def setspeed_modbus(self, speedkmh):
        try:
            if speedkmh is None:
                raise ValueError("La velocità non può essere None")
            if not (0 <= speedkmh <= 80):  # Allow 0 km/h
                raise ValueError(
                    f"La velocità richiesta ({speedkmh} km/h) è fuori dal range consentito (0-80 km/h). Comando rifiutato.")
            logging.getLogger().info(f"Impostazione velocità banco a {speedkmh} km/h")
            self.modbus.set_motor_speed(int(speedkmh * 10))  # Assuming API needs speed * 10
        except ValueError as ve:
            logging.getLogger().error(f"Errore valore velocità banco: {ve}")
        except Exception as e:
            logging.getLogger().error(f"Errore nell'invio della velocità del banco: {e}")

    def on_closing(self):
        logging.getLogger().info("Chiusura applicazione...")
        if hasattr(self, 'lorenz_reader') and self.lorenz_reader.is_connected():
            self.lorenz_reader.close_connection()
        if hasattr(self, 'ble_manager') and self.ble_manager.get_connection_status():
            # Ensure disconnect is called, might need to be async and waited for briefly
            # For simplicity here, direct call. If it blocks, needs care.
            self.worker.run_coroutine(self.ble_manager.disconnect_device())

        if hasattr(self, 'modbus') and self.modbus.is_connesso():
            self.modbus.disconnetti()

        if hasattr(self, 'worker'):
            self.worker.stop()  # Ensure asyncio worker is stopped

        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)  # Wait for pending tasks

        self.destroy()


if __name__ == "__main__":
    # Setup basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    root = MainWindow()

    # Create and add the custom TextHandler to the root logger
    text_handler = TextHandler(root.log_text)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    text_handler.setFormatter(formatter)
    logging.getLogger().addHandler(text_handler)
    logging.getLogger().setLevel(logging.INFO)  # Ensure root logger level is appropriate

    try:
        root.mainloop()
    except KeyboardInterrupt:
        logging.getLogger().info("Applicazione interrotta da tastiera.")
        root.on_closing()