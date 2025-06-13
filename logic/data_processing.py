import csv
from datetime import datetime
import time
import os

class DataProcessor:
    def __init__(self):
        self.start_time = time.time()
        self.output_dir = "output"
        self.create_output_dir()
        self.csv_filename = os.path.join(self.output_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bike_data_log.csv")
        self.initialize_csv()

    def create_output_dir(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def initialize_csv(self):
        try:
            with open(self.csv_filename, mode='x', newline='') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(["timestamp", "ms", "speed", "cadence", "power", "total_distance", "resistance", "elapsed_time", "offset", "speed_avg", "torque_lorenz", "power_lorenz"])
        except FileExistsError:
            pass

    def handle_bike_data(self, data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed_deciseconds = int((time.time() - self.start_time) * 10)
        row = [
            timestamp,
            elapsed_deciseconds,
            data.get("speed", ""),
            data.get("cadence", ""),
            data.get("power", ""),
            data.get("total_distance", ""),
            data.get("resistance", ""),
            data.get("elapsed_time", ""),
            data.get("offset_lorenz", ""),
            data.get("speed_avg", ""),
            data.get("torque_lorenz", ""),
            data.get("power_lorenz", "")
        ]
        with open(self.csv_filename, mode='a', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(row)

    @staticmethod
    def read_brake_commands_from_csv(file_path):
        brake_commands = []
        try:
            with open(file_path, mode='r') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)  # Salta la prima riga (intestazione)
                for row in reader:
                    if row[1]:  # Se c'è un valore nella seconda colonna
                        command_type = "livelli"
                        value = int(row[1])
                    elif row[2]:  # Se c'è un valore nella terza colonna
                        command_type = "potenza"
                        value = int(row[2])
                    elif row[3]:  # Se c'è un valore nella quarta colonna
                        command_type = "simulazione"
                        value = int(row[3])

                    speed_banco = None
                    if len(row) >= 5: # Assicurati che la riga abbia almeno 5 colonne
                        speed_banco = int(row[4]) if row[4] else None

                    wait_time = int(row[0])
                    brake_commands.append((command_type, value, wait_time, speed_banco))
        except Exception as e:
            print(e)
        return brake_commands
