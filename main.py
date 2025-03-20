import asyncio
from shared_lib.bluetooth_manager import AsyncioWorker, BLEManager

asyncio_worker = AsyncioWorker()
asyncio_worker.start()
ble_manager = BLEManager(asyncio_worker)

async def apply_brake(ble_manager, percentage, wait_time):
    await ble_manager.set_brake_percentage(percentage)
    await asyncio.sleep(wait_time)

async def test_ble_brake(serial_number):
    ble_manager = BLEManager(AsyncioWorker())  # Usa il worker dello script

    success = await ble_manager.connect_to_device(serial_number)
    if not success:
        print("Connessione fallita.")
        return

    await ble_manager.enable_fitness_machine_status_notifications()
    await ble_manager.enable_indoor_bike_data_notifications()
    await asyncio.sleep(5)

    # Invia il primo comando di freno (ad esempio 0%)
    await ble_manager.set_brake_percentage(0)

    # Array con percentuali di freno e tempi di attesa in secondi
    brake_commands = [
        (25, 3),
        (50, 3),
        (75, 5),
        (100, 3)
    ]

    # Creare e avviare tutte le attività di applicazione dei freni
    for percentage, wait_time in brake_commands:
        # Avviare il task in modo asincrono senza bloccare
        await apply_brake(ble_manager, percentage, wait_time)

    await ble_manager.set_brake_percentage(0)
    await asyncio.sleep(5)

    await ble_manager.disconnect_device()

if __name__ == "__main__":
    serial_n1 = "F0:F5:BD:31:FE:C6"
    serial_n2 = "F4:a7:72:f0:9c:84"

    serial = serial_n1

    try:
        asyncio.run(test_ble_brake(serial))  # Usa asyncio.run() solo se non c'è già un loop attivo
    except RuntimeError as e:
        print(f"Errore nell'esecuzione di asyncio: {e}")
