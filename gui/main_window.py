import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor
import logging
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager
from shared_lib.LorenzLib import LorenzReader
from shared_lib.funzioni_accessorie import trova_porta_usb_serial
from shared_lib.modbus_utils import ModbusBancoCollaudo
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
        self.lorenz_update_id = None  # Variabile per gestire l'aggiornamento periodico
        self.title("Total Commander")
        self.geometry("1350x760")  # Aumentato la larghezza della finestra per includere il nuovo blocco
        self.worker = AsyncioWorker()
        self.worker.start()
        self.ble_manager = BLEManager(self.worker)
        self.data_processor = DataProcessor()
        self.modbus = ModbusBancoCollaudo()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.auto_commands_running = False  # Stato dei comandi automatici

        # Frame principale
        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=0, column=0, sticky="nsew")

        # Frame sinistro per ricerca, stato connessione e comandi
        self.left_frame = ttk.Frame(self.main_frame)
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=10)

        # Frame per la ricerca e la connessione
        self.frame_search = ttk.LabelFrame(self.left_frame, text="Ricerca Dispositivi BLE")
        self.frame_search.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Configura la colonna del left_frame per espandersi
        self.left_frame.grid_columnconfigure(0, weight=1)
        # Configura la colonna del frame_search per espandersi
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

        # Configura la colonna del frame_status per espandersi
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

        # Frame comandi da CSV
        self.automatic_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi da CSV")
        self.automatic_commands.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.middle_left_frame.grid_rowconfigure(0, weight=1)
        self.middle_left_frame.grid_columnconfigure(0, weight=1)
        self.automatic_commands.grid_rowconfigure(0, weight=1)
        self.automatic_commands.grid_columnconfigure(0, weight=1)

        # Aggiungi una barra di scorrimento verticale alla tabella
        self.scrollbar = ttk.Scrollbar(self.automatic_commands, orient="vertical")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # Aggiungi una tabella per visualizzare i comandi caricati
        self.commands_table = ttk.Treeview(self.automatic_commands,
                                           columns=("Comando", "Valore", "Tempo [s]", "Vel Banco [km/h]"), show='headings',
                                           yscrollcommand=self.scrollbar.set)

        self.commands_table.heading("Comando", text="Comando")
        self.commands_table.heading("Valore", text="Valore")
        self.commands_table.heading("Tempo [s]", text="Tempo [s]")
        self.commands_table.heading("Vel Banco [km/h]", text="Vel Banco [km/h]")
        self.commands_table.column("Comando", width=100)
        self.commands_table.column("Valore", width=100)
        self.commands_table.column("Tempo [s]", width=100)
        self.commands_table.column("Vel Banco [km/h]", width=100)
        self.commands_table.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.scrollbar.config(command=self.commands_table.yview)

        # Configura i colori alternati delle righe
        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')


        # Frame per i comandi automatici
        self.frame_auto_commands = ttk.LabelFrame(self.middle_left_frame, text="Comandi automatici")
        self.frame_auto_commands.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        # Configura la colonna del frame_status per espandersi
        self.frame_auto_commands.grid_columnconfigure(0, weight=1)
        self.frame_auto_commands.grid_columnconfigure(1, weight=1)

        # LED di stato per comandi automatici
        self.led_status = tk.Label(self.frame_auto_commands, text="Comandi Automatici: OFF", fg="red")
        self.led_status.grid(row=1, column=0, padx=10, pady=5)

        # Pulsante per caricare i comandi dal CSV
        self.btn_load_commands = ttk.Button(self.frame_auto_commands, text="Carica Comandi da CSV",
                                            command=self.load_commands_from_csv)
        self.btn_load_commands.grid(row=0, column=1, padx=10, pady=2)

        # Pulsante per lanciare comandi automatici
        self.btn_auto_commands = ttk.Button(self.frame_auto_commands, text="Lancia Comandi Automatici",
                                            command=self.launch_auto_commands)
        self.btn_auto_commands.grid(row=1, column=1, padx=10, pady=2)

        # Pulsante per fermare comandi automatici
        self.btn_stop_auto_commands = ttk.Button(self.frame_auto_commands, text="Ferma Comandi Automatici",
                                                 command=self.stop_auto_commands)
        self.btn_stop_auto_commands.grid(row=2, column=1, padx=10, pady=2)


        # Frame destro per la visualizzazione dei dati BLE
        self.frame_data = ttk.LabelFrame(self.main_frame, text="Dati BLE FTMS")
        self.frame_data.grid(row=0, column=2, sticky="nsew", padx=10, pady=5)
        self.create_data_fields()


        self.right_frame = ttk.Frame(self.main_frame)
        self.right_frame.grid(row=0, column=3, sticky="nsew", padx=10, pady=10)
        # Frame per la gestione del Lorenz
        self.create_lorenz_controls()
        self.create_banco_controls()

        # Frame per il log delle attività
        self.frame_log = ttk.LabelFrame(self, text="Log delle Attività")
        self.frame_log.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=10, pady=10)
        # Configura la colonna del frame_log per espandersi
        self.frame_log.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(self.frame_log, state='disabled', height=13)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)


        # Avvia il monitoraggio dello stato della connessione
        self.periodic_connection_check()

        # Sovrascrivi il protocollo di chiusura della finestra
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_command_controls(self):
        commands = [("Livello [/200]", self.send_level_command), ("Potenza [W]", self.send_power_command),
                    ("Simulazione [%]", self.send_simulation_command)]

        # Configura le colonne per avere la suddivisione desiderata
        self.frame_commands.grid_columnconfigure(0, weight=2)  # Colonna delle etichette
        self.frame_commands.grid_columnconfigure(1, weight=1)  # Colonna delle entry
        self.frame_commands.grid_columnconfigure(2, weight=1)  # Colonna dei bottoni

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

        # Pulsante per abilitare/disabilitare i dati
        self.btn_toggle_data = ttk.Button(self.data_controls, text="Abilita Dati", command=self.toggle_data)
        self.btn_toggle_data.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=5)

    def periodic_connection_check(self):
        """
        Funzione sincrona chiamata periodicamente da Tkinter.
        Avvia i controlli di stato per BLE (asincrono) e Modbus (sincrono).
        """
        # Avvia il controllo asincrono per lo stato BLE
        # Assumiamo che self.worker.run_coroutine() esegua la coroutine
        # nel loop asyncio del worker senza bloccare il thread principale.
        self.worker.run_coroutine(self._async_check_ble_status())

        # Controlla e aggiorna lo stato Modbus (sincrono)
        self._check_and_update_modbus_status()

        # Schedula il prossimo controllo
        self.after(1000, self.periodic_connection_check)

    async def _async_check_ble_status(self):
        """
        Corotuine asincrona per controllare lo stato della connessione BLE.
        Schedula l'aggiornamento dell'UI nel thread principale di Tkinter.
        """
        try:
            is_connected = self.ble_manager.get_connection_status()
            # Schedula l'aggiornamento dell'UI nel thread principale di Tkinter
            self.after(0, self._update_ble_status_ui, is_connected, False)
        except Exception as e:
            logging.getLogger().error(f"Errore durante il controllo dello stato BLE: {e}")
            # Opzionale: aggiorna l'UI per mostrare uno stato di errore
            self.after(0, self._update_ble_status_ui, None, True)  # Passa un flag di errore

    def _update_ble_status_ui(self, is_connected, error=False):
        """
        Aggiorna l'etichetta dello stato della connessione BLE nell'UI.
        Questa funzione viene eseguita nel thread principale di Tkinter.
        """
        if error:
            self.connection_status.config(text="Errore BLE", fg="orange")
        elif is_connected:
            self.connection_status.config(text="Connesso", fg="green")
        else:
            self.connection_status.config(text="Non Connesso", fg="red")

    def _check_and_update_modbus_status(self):
        """
        Controlla e aggiorna lo stato della connessione Modbus nell'UI.
        Questa funzione è sincrona e viene chiamata dal thread principale di Tkinter.
        """
        if self.modbus.is_connesso():
            self.btn_connect_banco.config(text="Disconnetti")
            self.banco_status.config(text="Connesso", fg="green")
        else:
            self.btn_connect_banco.config(text="Connetti")
            self.banco_status.config(text="Non Connesso", fg="red")

    def search_devices(self):
        logging.getLogger().info("Richiesta ricerca dispositivi")
        self.progress.start()
        self.executor.submit(self._search_devices)

    def _search_devices(self):
        devices = self.worker.run_coroutine(self.ble_manager.scan_devices(timeout=5)).result()
        self.device_list.delete(0, tk.END)
        for address, (name, rssi) in devices.items():
            # Inserisci il dispositivo nella lista
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
            # Cambia il colore di sfondo se l'RSSI è inferiore a 50
            if rssi > -50:
                self.device_list.itemconfig(tk.END, {'bg': 'lightcoral'})
            logging.getLogger().info(f"Dispositivo trovato: {name} - {address} - RSSI: {rssi}")
        self.progress.stop()

    def connect_device(self):
        self.progress.start()
        self.executor.submit(self._connect_device)

    def _connect_device(self):
        selected_device = self.device_list.get(tk.ACTIVE)
        if selected_device:
            address = selected_device.split(" - ")[1]
            logging.getLogger().info(f"Tentativo connessione a {address}")
            self.worker.run_coroutine(self.ble_manager.connect_to_device(address)).result()
        self.progress.stop()

    def disconnect_device(self):
        self.progress.start()
        logging.getLogger().info("Richiesta Disconnessione")
        self.executor.submit(self._disconnect_device)

    def _disconnect_device(self):
        if self.worker.run_coroutine(self.ble_manager.disconnect_device()).result():
            self.connection_status.config(text="Non Connesso", fg="red")
        self.progress.stop()

    def send_level_command(self, level=None):
        if level is None:
            level = self.livello_entry.get()
        self.executor.submit(self._send_level_command, level)

    def _send_level_command(self, level):
        logging.getLogger().info(f"Invio comando livello: {level}/200")
        self.worker.run_coroutine(self.ble_manager.set_brake_percentage(int(level)))

    def send_power_command(self, power=None):
        if power is None:
            power = self.potenza_entry.get()
        self.executor.submit(self._send_power_command, power)

    def _send_power_command(self, power):
        logging.getLogger().info(f"Invio comando potenza: {power}W")
        self.worker.run_coroutine(self.ble_manager.set_brake_power(int(power)))

    def send_simulation_command(self, simulation=None):
        if simulation is None:
            simulation = self.simulazione_entry.get()
        self.executor.submit(self._send_simulation_command, simulation)

    def _send_simulation_command(self, simulation):
        logging.getLogger().info(f"Invio comando simulazione: {simulation}%")
        self.worker.run_coroutine(self.ble_manager.set_brake_simulation(grade=int(simulation)))

    def toggle_data(self):
        if self.btn_toggle_data.cget('text') == 'Abilita Dati':
            if self.ble_manager.get_connection_status():
                self.btn_toggle_data.config(text='Disabilita Dati')
                logging.getLogger().info("Abilitate notifiche FTMS")
                self.worker.run_coroutine(self.ble_manager.enable_indoor_bike_data_notifications(self.update_data_fields))
            else:
                logging.getLogger().info("Nessun dispositivo connesso, abilitazione FTMS non possibile")
        else:
            self.btn_toggle_data.config(text='Abilita Dati')
            logging.getLogger().info("Disabilitate notifiche FTMS")
            self.worker.run_coroutine(self.ble_manager.disable_indoor_bike_data_notifications())

    def update_data_fields(self, bike_data):
        for key, value in bike_data.items():
            if value is not None:
                self.data_entries[key.replace(" ", "_")].config(state='normal')
                self.data_entries[key.replace(" ", "_")].delete(0, tk.END)
                self.data_entries[key.replace(" ", "_")].insert(0, str(value))
                self.data_entries[key.replace(" ", "_")].config(state='readonly')
        # Aggiungi la lettura dei dati del Lorenz
        lorenz_data = self.lorenz_reader.get_data()
        combined_data = {**bike_data, **lorenz_data}
        # Passa i dati combinati al data processor
        self.data_processor.handle_bike_data(combined_data)

    def load_commands_from_csv(self):
        # Controlla se ci sono comandi automatici in corso
        if self.auto_commands_running:
            logging.getLogger().warning("Comandi automatici in corso. Impossibile caricare il file CSV.")
            return
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            # Elimina i valori precedenti dalla tabella
            for item in self.commands_table.get_children():
                self.commands_table.delete(item)
            # Carica i nuovi comandi dal file CSV
            commands = DataProcessor.read_brake_commands_from_csv(file_path)
            for i, command in enumerate(commands):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                self.commands_table.insert("", "end", values=command, tags=(tag,))

    def launch_auto_commands(self):
        # Controlla se la tabella "Comandi da CSV" non è vuota
        if not self.commands_table.get_children():
            logging.getLogger().info("La tabella dei comandi è vuota.")
            return
        # Ottieni tutti i comandi dalla tabella
        commands = [self.commands_table.item(item, 'values') for item in self.commands_table.get_children()]
        command_items = self.commands_table.get_children()
        # Resetta i colori delle righe
        for index, item in enumerate(command_items):
            self.commands_table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))

        # Funzione ricorsiva per inviare i comandi uno alla volta
        def send_next_command(index):
            if index < len(commands) and self.auto_commands_running:
                command_type, value, wait_time, speed_banco = commands[index]
                wait_time = int(wait_time)  # Converti wait_time in intero
                # Rimuovi il colore speciale dalla riga precedente
                if index > 0:
                    self.commands_table.item(command_items[index - 1],
                                             tags=('evenrow' if (index - 1) % 2 == 0 else 'oddrow',))
                # Applica il colore speciale alla riga corrente
                self.commands_table.item(command_items[index], tags=('currentrow',))
                # Invia il comando appropriato in base al tipo di comando
                if command_type == "potenza":
                    self.send_power_command(value)
                elif command_type == "livelli":
                    self.send_level_command(value)
                elif command_type == "simulazione":
                    self.send_simulation_command(value)

                if speed_banco is not None and speed_banco != "None":
                    self.setspeed_modbus(float(speed_banco))
                else:
                    # Gestisci il caso in cui speed_banco sia None o "None"
                    print("speed_banco is None or 'None'")

                # Attendi il tempo specificato prima di inviare il prossimo comando
                self.auto_command_id = self.after(wait_time * 1000, lambda: send_next_command(index + 1))
            else:
                # Comandi automatici completati
                self.auto_commands_running = False
                self.led_status.config(text="Comandi Automatici: Completati", fg="blue")
                logging.getLogger().info("Comandi automatici completati")
        # Configura i colori delle righe
        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')
        # Inizia l'invio dei comandi dal primo comando
        self.auto_commands_running = True
        self.led_status.config(text="Comandi Automatici: ON", fg="green")
        send_next_command(0)

    def stop_auto_commands(self):
        if self.auto_commands_running:
            self.auto_commands_running = False
            self.led_status.config(text="Comandi Automatici: OFF", fg="red")
            if hasattr(self, 'auto_command_id'):
                self.after_cancel(self.auto_command_id)  # Ferma l'invio dei comandi automatici
            logging.getLogger().info("Comandi automatici interrotti")
            # Rimuovi il colore speciale dalla riga corrente
            for item in self.commands_table.get_children():
                if 'currentrow' in self.commands_table.item(item, 'tags'):
                    index = self.commands_table.index(item)
                    self.commands_table.item(item, tags=('evenrow' if index % 2 == 0 else 'oddrow',))
                    break
        else:
            logging.getLogger().info("Non ci sono comandi automatici attivi")

    def create_lorenz_controls(self):
        self.frame_lorenz = ttk.LabelFrame(self.right_frame, text="Gestione Lorenz")
        self.frame_lorenz.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.lorenz_reader = LorenzReader()
        self.lorenz_controls = ttk.Frame(self.frame_lorenz)
        self.lorenz_controls.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        self.lorenz_status = tk.Label(self.lorenz_controls, text="Lorenz: Non Connesso", fg="red")
        self.lorenz_status.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        self.btn_connect_lorenz = ttk.Button(self.lorenz_controls, text="Connetti Lorenz", command=self.connect_lorenz)
        self.btn_connect_lorenz.grid(row=1, column=0, padx=5, pady=5)
        self.btn_disconnect_lorenz = ttk.Button(self.lorenz_controls, text="Disconnetti Lorenz",
                                                command=self.disconnect_lorenz)
        self.btn_disconnect_lorenz.grid(row=1, column=1, padx=5, pady=5)
        self.btn_read_offset = ttk.Button(self.lorenz_controls, text="Leggi Offset", command=self.read_lorenz_offset)
        self.btn_read_offset.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        # Campi di visualizzazione con etichetta e Entry su due colonne
        self.offset_label = self.create_labeled_entry(self.lorenz_controls, "Offset", 3)
        self.speed_avg_label = self.create_labeled_entry(self.lorenz_controls, "Speed Avg", 4)
        self.torque_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Torque Lorenz", 5)
        self.power_lorenz_label = self.create_labeled_entry(self.lorenz_controls, "Power Lorenz", 6)

    def create_banco_controls(self):
        self.banco_controls = ttk.LabelFrame(self.right_frame, text="Gestione Banco")
        self.banco_controls.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        # Porta IP
        lbl_ip = ttk.Label(self.banco_controls, text="PORTA IP:")
        lbl_ip.grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.entry_ip = ttk.Entry(self.banco_controls, width=12)
        self.entry_ip.insert(0, "192.168.0.10")
        self.entry_ip.grid(row=0, column=1, padx=5, pady=5)

        # Pulsante Connetti e stato connessione
        self.btn_connect_banco = ttk.Button(self.banco_controls, text="Connetti",
                                            command=self.toggle_modbus_connection) # MODIFICATO
        self.btn_connect_banco.grid(row=1, column=0, padx=5, pady=5)
        self.banco_status = tk.Label(self.banco_controls, text="Non Connesso", fg="red")
        self.banco_status.grid(row=1, column=1, padx=5, pady=5)

        # Pulsante Set Velocità
        self.btn_set_speed = ttk.Button(self.banco_controls, text="Set Velocità [km/h]:",
                                        command=self.clicked_button_setspeed_modbus)
        self.btn_set_speed.grid(row=2, column=0, padx=5, pady=5)
        self.speed_banco_entry = ttk.Entry(self.banco_controls, width=12)
        self.speed_banco_entry.grid(row=2, column=1, padx=5, pady=5)

        # Pulsante Zero Speed
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
        data = self.lorenz_reader.get_data()

        # Dizionario campo-nome_entry per renderlo più gestibile
        values = {
            self.offset_label: data.get("offset_lorenz"),
            self.speed_avg_label: data.get("speed_avg"),
            self.torque_lorenz_label: data.get("torque_lorenz"),
            self.power_lorenz_label: data.get("power_lorenz"),
        }
        for entry, val in values.items():
            entry.config(state='normal')
            entry.delete(0, tk.END)
            entry.insert(0, f"{val:.2f}" if val is not None else "N/A")
            entry.config(state='readonly')

    def connect_lorenz(self):
        """
        Questa funzione viene chiamata dal pulsante "Connetti Lorenz".
        Avvia la connessione in un thread separato per non bloccare la GUI.
        """
        logging.getLogger().info("Richiesta connessione a Lorenz...")
        # Aggiungi un feedback visivo se lo desideri, es. progress bar o disabilitare il pulsante
        self.executor.submit(self._connect_lorenz_worker)

    def _connect_lorenz_worker(self):
        """
        Esegue le operazioni bloccanti di ricerca e connessione al Lorenz.
        Questa funzione viene eseguita in un thread del ThreadPoolExecutor.
        """
        try:
            porta_com_lorenz = trova_porta_usb_serial("Lorenz USB sensor interface Port")
            if porta_com_lorenz:
                if self.lorenz_reader.open_connection(int(porta_com_lorenz.split("COM")[-1])):
                    # Se la connessione ha successo, schedula l'aggiornamento della GUI
                    # nel thread principale usando self.after
                    self.after(0, self._update_lorenz_ui, True)
                else:
                    # Connessione fallita
                    self.after(0, self._update_lorenz_ui, False)
            else:
                # Porta non trovata
                self.after(0, self._update_lorenz_ui, False)
        except Exception as e:
            logging.getLogger().error(f"Errore durante la connessione a Lorenz: {e}")
            self.after(0, self._update_lorenz_ui, False)

    def _update_lorenz_ui(self, is_connected):
        """
        Aggiorna la GUI dello stato del Lorenz.
        Questa funzione viene eseguita nel thread principale di Tkinter.
        """
        if is_connected:
            self.lorenz_status.config(text="Lorenz: Connesso", fg="green")
            logging.getLogger().info("Lorenz Connesso")
            self.start_lorenz_update()  # Avvia l'aggiornamento periodico
        else:
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            logging.getLogger().warning("Lorenz non connesso o connessione fallita.")

    def start_lorenz_update(self):
        self.update_lorenz_data()
        self.lorenz_update_id = self.after(500, self.start_lorenz_update)  # Richiama ogni 500 ms (2 volte al secondo)

    def stop_lorenz_update(self):
        if self.lorenz_update_id is not None:
            self.after_cancel(self.lorenz_update_id)
            self.lorenz_update_id = None

    def disconnect_lorenz(self):
        if self.lorenz_reader.close_connection():
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            self.stop_lorenz_update()  # Ferma l'aggiornamento periodico

    def read_lorenz_offset(self):
        self.lorenz_reader.read_offset()
        logging.getLogger().info(f"Offset letto: {self.lorenz_reader.offset}")

    def toggle_modbus_connection(self):
        """
        Avvia la connessione/disconnessione Modbus in un thread separato.
        """
        logging.getLogger().info("Richiesta connessione/disconnessione Modbus...")
        # Aggiungi un feedback visivo se vuoi, es. disabilitare il pulsante
        self.btn_connect_banco.config(state='disabled')
        self.executor.submit(self._toggle_modbus_worker)

    def _toggle_modbus_worker(self):
        """
        Esegue le operazioni bloccanti di connessione/disconnessione Modbus.
        Questa funzione viene eseguita in un thread del ThreadPoolExecutor.
        """
        try:
            if not self.modbus.is_connesso():
                ip_address = self.entry_ip.get()
                self.modbus.connetti(ip_address, 502)
            else:
                self.modbus.disconnetti()
        except Exception as e:
            logging.getLogger().error(f"Errore durante l'operazione Modbus: {e}")
        finally:
            # Schedula l'aggiornamento della UI nel thread principale,
            # indipendentemente dall'esito, e riabilita il pulsante.
            self.after(0, self._check_and_update_modbus_status)
            self.after(0, lambda: self.btn_connect_banco.config(state='normal'))

    def clicked_button_setspeed_modbus(self):
        """
        Metodo chiamato dal click del pulsante per impostare la velocità.
        """
        try:
            speed_value = float(self.speed_banco_entry.get())
            self.setspeed_modbus(speed_value)
        except (ValueError, TypeError):
            logging.getLogger().error(f"Valore velocità non valido: {self.speed_banco_entry.get()}")

    def setspeed_modbus(self, speedkmh):
        """
        Sottomette l'impostazione della velocità a un thread separato.
        Questo metodo ora non è più bloccante.
        """
        logging.getLogger().info(f"Invio comando velocità banco: {speedkmh} km/h")
        self.executor.submit(self._setspeed_modbus_worker, speedkmh)

    def _setspeed_modbus_worker(self, speedkmh):
        """
        Esegue l'operazione bloccante di impostazione velocità Modbus.
        Questa funzione viene eseguita in un thread del ThreadPoolExecutor.
        """
        try:
            if speedkmh is None:
                raise ValueError("La velocità non può essere None")
            if speedkmh > 80:
                raise ValueError("La velocità richiesta è superiore a 80km/h. Comando rifiutato.")

            # Questa è la chiamata bloccante
            self.modbus.set_motor_speed(speedkmh * 10)
            logging.getLogger().info(f"Comando velocità {speedkmh} km/h inviato con successo.")

        except Exception as e:
            logging.getLogger().error(f"Errore nell'invio della velocità del banco: {e}")

    def on_closing(self):
        #if self.ble_manager.get_connection_status():
        #    self.disconnect_device()
        if self.lorenz_reader.connected:
            self.lorenz_reader.close_connection()
        if self.modbus.is_connesso():
            self.modbus.disconnetti()
        self.destroy()

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
