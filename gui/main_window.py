import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor
import logging
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager

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
        self.title("BLE Device Manager")
        self.geometry("800x700")  # Aumentato la larghezza della finestra per includere il nuovo blocco

        self.worker = AsyncioWorker()
        self.worker.start()
        self.ble_manager = BLEManager(self.worker)
        self.executor = ThreadPoolExecutor(max_workers=1)

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

        # Barra di avanzamento
        self.progress = ttk.Progressbar(self.frame_status, mode='indeterminate')
        self.progress.pack(side="left", fill="x", expand=True, padx=10, pady=10)

        # Frame per i comandi
        self.frame_commands = ttk.LabelFrame(self.left_frame, text="Comandi")
        self.frame_commands.pack(fill="x", padx=10, pady=10)

        self.create_command_controls()

        # Frame destro per la visualizzazione dei dati BLE
        self.frame_data = ttk.LabelFrame(self.main_frame, text="Dati BLE FTMS")
        self.frame_data.pack(side="left", fill="y", padx=10, pady=10)

        self.create_data_fields()

        self.btn_toggle_data = ttk.Button(self.frame_data, text="Abilita Dati", command=self.toggle_data)
        self.btn_toggle_data.pack(side="top", padx=10, pady=10)

        # Frame per il log delle attività
        self.frame_log = ttk.LabelFrame(self, text="Log delle Attività")
        self.frame_log.pack(fill="both", expand=True, padx=10, pady=10)

        self.log_text = tk.Text(self.frame_log, state='disabled', height=8)
        self.log_text.pack(fill="both", expand=True)

        # Avvia il monitoraggio dello stato della connessione
        self.monitor_connection_status()

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
            # Usa nomi di attributi specifici
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

    def send_level_command(self):
        self.executor.submit(self._send_level_command)

    def _send_level_command(self):
        level = self.livello_entry.get()
        logging.getLogger().info(f"Invio comando livello: {level}/200")
        self.worker.run_coroutine(self.ble_manager.set_brake_percentage(int(level)))

    def send_power_command(self):
        self.executor.submit(self._send_power_command)

    def _send_power_command(self):
        power = self.potenza_entry.get()
        logging.getLogger().info(f"Invio comando potenza: {power}W")
        self.worker.run_coroutine(self.ble_manager.set_brake_power(int(power)))

    def send_simulation_command(self):
        self.executor.submit(self._send_simulation_command)

    def _send_simulation_command(self):
        simulation = self.simulazione_entry.get()
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
            # Aggiungi qui il codice per disabilitare le notifiche

    def update_data_fields(self, bike_data):
        for key, value in bike_data.items():
            if value is not None:
                self.data_entries[key.replace(" ", "_")].config(state='normal')
                self.data_entries[key.replace(" ", "_")].delete(0, tk.END)
                self.data_entries[key.replace(" ", "_")].insert(0, str(value))
                self.data_entries[key.replace(" ", "_")].config(state='readonly')

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()