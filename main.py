import asyncio
import logging
import csv
import os
from datetime import datetime
import time
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILENAME = f"{timestamp}_bike_data_log.csv"

asyncio_worker = AsyncioWorker()
asyncio_worker.start()
ble_manager = BLEManager(asyncio_worker)
# Tempo di avvio del programma
start_time = time.time()

# Creiamo il file con intestazione se non esiste
def initialize_csv():
    try:
        with open(CSV_FILENAME, mode='x', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(["timestamp", "ms",  "ble speed", "ble cadence", "ble power", "ble total_distance", "ble resistance", "ble elapsed_time"])
    except FileExistsError:
        pass  # Il file esiste già, non facciamo nulla


# Funzione per scrivere i dati nel CSV
def handle_bike_data(data):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    elapsed_deciseconds = int((time.time() - start_time) * 10)  # Calcola i decimi di secondo trascorsi
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

    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow(row)


async def apply_brake(ble_manager, command_type, value, wait_time):
    if command_type == 1:
        await ble_manager.set_brake_percentage(value)
    elif command_type == 2:
        await ble_manager.set_brake_power(value)
    elif command_type == 3:
        await ble_manager.set_brake_simulation(grade = value)
    await asyncio.sleep(wait_time)

def read_brake_commands_from_csv(file_path):
    brake_commands = []
    try:
        with open(file_path, mode='r') as file:
            reader = csv.reader(file, delimiter=';')
            next(reader)  # Salta la prima riga (intestazione)
            for row in reader:
                if row[1]:  # Se c'è un valore nella seconda colonna
                    command_type = 1
                    value = int(row[1])
                elif row[2]:  # Se c'è un valore nella terza colonna
                    command_type = 2
                    value = int(row[2])
                elif row[3]:  # Se c'è un valore nella quarta colonna
                    command_type = 3
                    value = int(row[3])
                wait_time = int(row[4])
                brake_commands.append((command_type, value, wait_time))
    except Exception as e:
        logger.error(f"Errore durante la lettura del file CSV: {e}")
    return brake_commands

async def test_ble_brake(mac_address, brake_commands):
    ble_manager = BLEManager(AsyncioWorker())  # Usa il worker dello script

    if await ble_manager.connect_to_device(mac_address):
        await ble_manager.enable_indoor_bike_data_notifications(handle_bike_data)  # Passiamo la callback
    else:
        print("Connessione fallita.")
        return

    await ble_manager.enable_fitness_machine_status_notifications()
    await ble_manager.enable_indoor_bike_data_notifications()
    await asyncio.sleep(5)

    # Invia il primo comando di freno (ad esempio 0%)
    await ble_manager.set_brake_percentage(0)

    # Creare e avviare tutte le attività di applicazione dei freni
    for command_type, value, wait_time in brake_commands:
        # Avviare il task in modo asincrono senza bloccare
        await apply_brake(ble_manager, command_type, value, wait_time)

    await ble_manager.set_brake_percentage(0)
    await asyncio.sleep(5)

    await ble_manager.disconnect_device()

if __name__ == "__main__":
    LOG_FILENAME = "app.log"
    log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Handler per file rotativo
    file_handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(log_formatter)

    # Handler per la console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    # Creazione del logger principale
    logger = logging.getLogger()  # Ottieni il root logger
    logger.setLevel(logging.INFO)  # Imposta il livello di logging
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Esempio di log nel main
    logger.info("Avvio del programma...")

    serial_n1 = "F0:F5:BD:31:FE:C6"
    serial_n2 = "F4:a7:72:f0:9c:84"

    serial = serial_n2

    initialize_csv()

    # Leggi i comandi di freno dal file CSV
    brake_commands_file = "brake_commands.csv"
    brake_commands = read_brake_commands_from_csv(brake_commands_file)
    try:
        asyncio.run(test_ble_brake(serial, brake_commands))  # Usa asyncio.run() solo se non c'è già un loop attivo
    except RuntimeError as e:
        print(f"Errore nell'esecuzione di asyncio: {e}")
