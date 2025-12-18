from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from datetime import datetime
import time
import os

class DataProcessor:
    def __init__(self):
        self.start_time = time.time()
        self.output_dir = "output"
        self.create_output_dir()
        self.xlsx_filename = os.path.join(self.output_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bike_data_log.xlsx")
        self.initialize_xlsx()

    def create_output_dir(self):
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def initialize_xlsx(self):
        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Bike Data"
        headers = [
            "timestamp", "s", "speed_trainer", "cadence_trainer", "power_trainer",
            "total_distance_trainer", "resistance_trainer", "elapsed_time_trainer",
            "offset_lorenz", "speed_avg_lorenz", "torque_lorenz", "power_lorenz",
            "Valore1", "Valore2", "Valore3", "Valore4"
        ]
        self.sheet.append(headers)
        self.workbook.save(self.xlsx_filename)

    @staticmethod
    def _format_value(value):
        """Converte numeri in stringhe con virgola come separatore decimale."""
        if isinstance(value, (float, int)):
            return str(value).replace('.', ',')
        return str(value)

    def handle_bike_data(self, data):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed_seconds = round(time.time() - self.start_time, 2)
        row = [
            timestamp,
            elapsed_seconds,
            data.get("Spd", ""),
            data.get("Cad", ""),
            data.get("Pwr", ""),
            data.get("TotDist", ""),
            data.get("Res", ""),
            data.get("ElaTime", ""),
            data.get("offset_lorenz", ""),
            data.get("speed_avg_lorenz", ""),
            data.get("torque_lorenz", ""),
            data.get("power_lorenz", ""),
            data.get("Valore1", ""),
            data.get("Valore2", ""),
            data.get("Valore3", ""),
            data.get("Valore4", "")
        ]
        formatted_row = [self._format_value(v) for v in row]
        workbook = load_workbook(self.xlsx_filename)
        sheet = workbook.active
        sheet.append(formatted_row)
        workbook.save(self.xlsx_filename)

    @staticmethod
    def read_brake_commands_from_csv(file_path):
        import csv
        brake_commands = []
        try:
            with open(file_path, mode='r') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader) # Salta la prima riga (intestazione)
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