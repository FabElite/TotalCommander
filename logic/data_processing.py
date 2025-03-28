import csv
from datetime import datetime
import time

class DataProcessor:
    def __init__(self):
        self.start_time = time.time()
        self.csv_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bike_data_log.csv"
        self.initialize_csv()

    def initialize_csv(self):
        try:
            with open(self.csv_filename, mode='x', newline='') as file:
                writer = csv.writer(file, delimiter=';')
                writer.writerow(["timestamp", "ms", "speed", "cadence", "power", "total_distance", "resistance", "elapsed_time"])
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
            data.get("elapsed_time", "")
        ]
        with open(self.csv_filename, mode='a', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(row)