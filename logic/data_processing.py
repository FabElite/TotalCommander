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
                writer.writerow([
                    "timestamp", "ms", "speed_trainer", "cadence_trainer", "power_trainer",
                    "total_distance_trainer", "resistance_trainer", "elapsed_time_trainer",
                    "offset_lorenz", "speed_avg_lorenz", "torque_lorenz", "power_lorenz"
                ])
        except FileExistsError:
            pass

    @staticmethod
    def _format_value(value):
        """Converte numeri in stringhe con virgola come separatore decimale."""
        if isinstance(value, (float, int)):
            return str(value).replace('.', ',')
        return str(value)

    def handle_bike_data(self, data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed_deciseconds = int((time.time() - self.start_time) * 10)
        row = [
            timestamp,
            elapsed_deciseconds,
            data.get("Spd", ""),
            data.get("Cad", ""),
            data.get("Pwr", ""),
            data.get("TotDist", ""),
            data.get("Res", ""),
            data.get("ElaTime", ""),
            data.get("offset_lorenz", ""),
            data.get("speed_avg", ""),
            data.get("torque_lorenz", ""),
            data.get("power_lorenz", "")
        ]
        # Applica formattazione a tutti i campi
        formatted_row = [self._format_value(v) for v in row]

        with open(self.csv_filename, mode='a', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(formatted_row)

    @staticmethod
    def read_brake_commands_from_csv(file_path):
        brake_commands = []
        try:
            with open(file_path, mode='r') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)  # Salta la prima riga (intestazione)
                for row in reader:
                    if row[1]:
                        command_type = "livelli"
                        value = int(row[1])
                    elif row[2]:
                        command_type = "potenza"
                        value = int(row[2])
                    elif row[3]:
                        command_type = "simulazione"
                        value = int(row[3])
                    else:
                        continue

                    speed_banco = None
                    if len(row) >= 5:
                        speed_banco = int(row[4]) if row[4] else None

                    wait_time = int(row[0])
                    brake_commands.append((command_type, value, wait_time, speed_banco))
        except Exception as e:
            print(e)
        return brake_commands
