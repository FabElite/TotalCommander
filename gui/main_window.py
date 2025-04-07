import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor
import logging
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager
from shared_lib.LorenzLib import LorenzReader
from shared_lib.funzioni_accessorie import trova_porta_usb_serial
from logic.data_processing import DataProcessor
from tkinter import filedialog
import csv
import functools

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
        self.geometry("1200x700")  # Aumentato la larghezza della finestra per includere il nuovo blocco
        self.worker = AsyncioWorker()
        self.worker.start()
        self.ble_manager = BLEManager(self.worker)
        self.data_processor = DataProcessor()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.auto_commands_running = False  # Stato dei comandi automatici
        # Frame principale
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill="both", expand=True)

        # Frame sinistro per ricerca, stato connessione e comandi
        self.left_frame = ttk.Frame(self.main_frame)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)

        # Frame per la ricerca e la connessione
        self.frame_search = ttk.LabelFrame(self.left_frame, text="Ricerca Dispositivi BLE")
        self.frame_search.pack(fill="x", padx=10, pady=10)
        self.device_list = tk.Listbox(self.frame_search)
        self.device_list.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        self.btn_search = ttk.Button(self.frame_search, text="Cerca Dispositivi", command=self.search_devices)
        self.btn_search.pack(side="top", padx=10, pady=10)
        self.btn_connect = ttk.Button(self.frame_search, text="Connetti", command=self.connect_device)
        self.btn_connect.pack(side="top", padx=10, pady=10)
        self.btn_disconnect = ttk.Button(self.frame_search, text="Disconnetti", command=self.disconnect_device)
        self.btn_disconnect.pack(side="top", padx=10, pady=10)

        # Frame per lo stato della connessione
        self.frame_status = ttk.LabelFrame(self.left_frame, text="Stato Connessione")
        self.frame_status.pack(fill="x", padx=10, pady=10)
        self.connection_status = tk.Label(self.frame_status, text="Non Connesso", fg="red")
        self.connection_status.pack(side="left", padx=10, pady=10)
        self.progress = ttk.Progressbar(self.frame_status, mode='indeterminate')
        self.progress.pack(side="left", fill="x", expand=True, padx=10, pady=10)

        # Frame per i comandi manuali
        self.frame_commands = ttk.LabelFrame(self.left_frame, text="Comandi manuali")
        self.frame_commands.pack(fill="x", padx=10, pady=10)
        self.create_command_controls()

        # Frame contenitore per la seconda colonna
        self.middle_frame = ttk.Frame(self.main_frame)
        self.middle_frame.pack(side="left", fill="y", padx=10, pady=10)

        # Frame comandi da CSV
        self.automatic_commands = ttk.LabelFrame(self.middle_frame, text="Comandi da CSV")
        self.automatic_commands.pack(side="top", fill="y", padx=10, pady=10, expand=False)

        # Aggiungi una barra di scorrimento verticale alla tabella
        self.scrollbar = ttk.Scrollbar(self.automatic_commands, orient="vertical")
        self.scrollbar.pack(side="right", fill="y")

        # Aggiungi una tabella per visualizzare i comandi caricati
        self.commands_table = ttk.Treeview(self.automatic_commands,
                                           columns=("Comando", "Valore", "Tempo [s]"), show='headings',
                                           yscrollcommand=self.scrollbar.set)
        self.commands_table.heading("Comando", text="Comando")
        self.commands_table.heading("Valore", text="Valore")
        self.commands_table.heading("Tempo [s]", text="Tempo [s]")
        self.commands_table.column("Comando", width=100)
        self.commands_table.column("Valore", width=100)
        self.commands_table.column("Tempo [s]", width=100)
        self.commands_table.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        self.scrollbar.config(command=self.commands_table.yview)

        # Configura i colori alternati delle righe
        self.commands_table.tag_configure('oddrow', background='lightgrey')
        self.commands_table.tag_configure('evenrow', background='white')
        self.commands_table.tag_configure('currentrow', background='yellow')

        # Frame per i comandi automatici
        self.frame_auto_commands = ttk.LabelFrame(self.middle_frame, text="Comandi automatici")
        self.frame_auto_commands.pack(side="top", fill="x", padx=10, pady=10)

        # Pulsante per caricare i comandi dal CSV
        self.btn_load_commands = ttk.Button(self.frame_auto_commands, text="Carica Comandi da CSV",
                                            command=self.load_commands_from_csv)
        self.btn_load_commands.pack(side="top", padx=10, pady=5)

        # Pulsante per lanciare comandi automatici
        self.btn_auto_commands = ttk.Button(self.frame_auto_commands, text="Lancia Comandi Automatici",
                                            command=self.launch_auto_commands)
        self.btn_auto_commands.pack(side="top", padx=10, pady=5)

        # Pulsante per fermare comandi automatici
        self.btn_stop_auto_commands = ttk.Button(self.frame_auto_commands, text="Ferma Comandi Automatici",
                                                 command=self.stop_auto_commands)
        self.btn_stop_auto_commands.pack(side="top", padx=10, pady=5)

        # LED di stato per comandi automatici
        self.led_status = tk.Label(self.frame_auto_commands, text="Comandi Automatici: OFF", fg="red")
        self.led_status.pack(side="top", padx=10, pady=5)

        # Frame destro per la visualizzazione dei dati BLE
        self.frame_data = ttk.LabelFrame(self.main_frame, text="Dati BLE FTMS")
        self.frame_data.pack(side="left", fill="y", padx=10, pady=10, expand=True)
        self.create_data_fields()
        self.btn_toggle_data = ttk.Button(self.frame_data, text="Abilita Dati", command=self.toggle_data)
        self.btn_toggle_data.pack(side="top", padx=10, pady=10)

        # Frame per la gestione del Lorenz
        self.frame_lorenz = ttk.LabelFrame(self.main_frame, text="Gestione Lorenz")
        self.frame_lorenz.pack(side="left", fill="y", padx=10, pady=10, expand=True)
        self.create_lorenz_controls()

        # Frame per il log delle attività
        self.frame_log = ttk.LabelFrame(self, text="Log delle Attività")
        self.frame_log.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text = tk.Text(self.frame_log, state='disabled', height=8)
        self.log_text.pack(fill="both", expand=True)

        # Avvia il monitoraggio dello stato della connessione
        self.monitor_connection_status()

        # Sovrascrivi il protocollo di chiusura della finestra
        self.protocol("WM_DELETE_WINDOW", self.on_closing)


    def create_command_controls(self):
        commands = [("Livello [/200]", self.send_level_command), ("Potenza [W]", self.send_power_command),
                    ("Simulazione [%]", self.send_simulation_command)]
        for i, (label, command) in enumerate(commands):
            frame = ttk.Frame(self.frame_commands)
            frame.pack(fill="x", padx=5, pady=5)
            lbl = ttk.Label(frame, text=label)
            lbl.pack(side="left", padx=5)
            entry = ttk.Entry(frame)
            entry.pack(side="left", padx=5)
            if "Livello" in label:
                self.livello_entry = entry
            elif "Potenza" in label:
                self.potenza_entry = entry
            elif "Simulazione" in label:
                self.simulazione_entry = entry
            btn = ttk.Button(frame, text="Invia", command=command)
            btn.pack(side="left", padx=5)

    def create_data_fields(self):
        fields = ["power", "cadence", "speed", "resistance", "total_distance", "elapsed_time"]
        self.data_entries = {}
        for field in fields:
            frame = ttk.Frame(self.frame_data)
            frame.pack(fill="x", padx=5, pady=5)
            lbl = ttk.Label(frame, text=field)
            lbl.pack(side="left", padx=5)
            entry = ttk.Entry(frame, state='readonly')
            entry.pack(side="left", padx=5)
            self.data_entries[field.lower().replace(" ", "_")] = entry

    def monitor_connection_status(self):
        """Monitora lo stato della connessione e aggiorna l'etichetta."""
        if self.ble_manager.get_connection_status():
            self.connection_status.config(text="Connesso", fg="green")
        else:
            self.connection_status.config(text="Non Connesso", fg="red")
        self.after(1000, self.monitor_connection_status)  # Controlla lo stato ogni secondo

    def search_devices(self):
        logging.getLogger().info("Richiesta ricerca dispositivi")
        self.progress.start()
        self.executor.submit(self._search_devices)

    def _search_devices(self):
        devices = self.worker.run_coroutine(self.ble_manager.scan_devices()).result()
        self.device_list.delete(0, tk.END)
        for name, (address, rssi) in devices.items():
            self.device_list.insert(tk.END, f"{name} - {address} - RSSI: {rssi}")
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
            self.btn_toggle_data.config(text='Disabilita Dati')
            logging.getLogger().info("Dati BLE abilitati")
            self.worker.run_coroutine(self.ble_manager.enable_indoor_bike_data_notifications(self.update_data_fields))
        else:
            self.btn_toggle_data.config(text='Abilita Dati')
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
            commands = self.data_processor.read_brake_commands_from_csv(file_path)
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
                command_type, value, wait_time = commands[index]
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
        self.lorenz_reader = LorenzReader()
        self.lorenz_controls = ttk.Frame(self.frame_lorenz)
        self.lorenz_controls.pack(fill="x", padx=5, pady=5)
        self.lorenz_status = tk.Label(self.lorenz_controls, text="Lorenz: Non Connesso", fg="red")
        self.lorenz_status.pack(side="top", padx=5, pady=5)
        self.btn_connect_lorenz = ttk.Button(self.lorenz_controls, text="Connetti Lorenz", command=self.connect_lorenz)
        self.btn_connect_lorenz.pack(side="top", padx=5, pady=5)
        self.btn_disconnect_lorenz = ttk.Button(self.lorenz_controls, text="Disconnetti Lorenz",
                                                command=self.disconnect_lorenz)
        self.btn_disconnect_lorenz.pack(side="top", padx=5, pady=5)
        self.btn_read_offset = ttk.Button(self.lorenz_controls, text="Leggi Offset", command=self.read_lorenz_offset)
        self.btn_read_offset.pack(side="top", padx=5, pady=5)

        # Campi di visualizzazione per i dati Lorenz
        self.offset_label = self.create_data_field(self.lorenz_controls, "Offset")
        self.speed_avg_label = self.create_data_field(self.lorenz_controls, "Speed Avg")
        self.torque_lorenz_label = self.create_data_field(self.lorenz_controls, "Torque Lorenz")
        self.power_lorenz_label = self.create_data_field(self.lorenz_controls, "Power Lorenz")

    def create_data_field(self, parent, label_text):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", padx=5, pady=5)
        lbl = ttk.Label(frame, text=label_text)
        lbl.pack(side="left", padx=5)
        entry = ttk.Entry(frame, state='readonly')
        entry.pack(side="left", padx=5)
        return entry

    def update_lorenz_data(self):
        offset = self.lorenz_reader.get_offset()
        data = self.lorenz_reader.get_data()

        self.offset_label.config(state='normal')
        self.offset_label.delete(0, tk.END)
        self.offset_label.insert(0, f"{offset:.2f}" if offset is not None else "N/A")
        self.offset_label.config(state='readonly')

        self.speed_avg_label.config(state='normal')
        self.speed_avg_label.delete(0, tk.END)
        self.speed_avg_label.insert(0, f"{data['speed_avg']:.2f}" if data['speed_avg'] is not None else "N/A")
        self.speed_avg_label.config(state='readonly')

        self.torque_lorenz_label.config(state='normal')
        self.torque_lorenz_label.delete(0, tk.END)
        self.torque_lorenz_label.insert(0,
                                        f"{data['torque_lorenz']:.2f}" if data['torque_lorenz'] is not None else "N/A")
        self.torque_lorenz_label.config(state='readonly')

        self.power_lorenz_label.config(state='normal')
        self.power_lorenz_label.delete(0, tk.END)
        self.power_lorenz_label.insert(0, f"{data['power_lorenz']:.2f}" if data['power_lorenz'] is not None else "N/A")
        self.power_lorenz_label.config(state='readonly')

    def connect_lorenz(self):
        porta_com_lorenz = trova_porta_usb_serial("Lorenz USB sensor interface Port")
        if porta_com_lorenz:
            if self.lorenz_reader.open_connection(int(porta_com_lorenz.split("COM")[-1])):
                self.lorenz_status.config(text="Lorenz: Connesso", fg="green")
                logging.getLogger().info("Lorenz Connesso")
                self.start_lorenz_update()  # Avvia l'aggiornamento periodico
            else:
                self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
                logging.getLogger().info("Lorenz non connesso")
        else:
            self.lorenz_status.config(text="Lorenz: Non Connesso", fg="red")
            logging.getLogger().info("Lorenz non connesso")

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


    def on_closing(self):
        if self.lorenz_reader.connected:
            self.lorenz_reader.close_connection()
        self.destroy()


if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
