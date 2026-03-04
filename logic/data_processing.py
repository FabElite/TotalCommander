import csv
import logging
import os
import threading
import time
from datetime import datetime

from openpyxl import load_workbook, Workbook


# Intervallo di flush automatico su disco (secondi)
FLUSH_INTERVAL_SECONDS = 30

# Dimensione massima del file xlsx prima della rotazione. Default: 100 MB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024


class DataProcessor:
    """
    Raccoglie i dati del banco prova e li persiste su file Excel.

    Strategia di scrittura:
    - Le righe nuove vengono accumulate in un buffer in RAM (semplici liste Python).
    - Un thread di background ogni FLUSH_INTERVAL_SECONDS appende le righe al file
      su disco e svuota il buffer. La RAM occupata e' proporzionale solo agli ultimi
      30 secondi di dati, indipendentemente dalla durata del test.
    - Se dopo il flush il file supera MAX_FILE_SIZE_BYTES, viene creato un nuovo
      file con suffisso _part02, _part03, ... con la stessa intestazione.
    - Un flush finale garantito viene eseguito chiamando close().
    - Tutte le operazioni sul buffer sono protette da lock.
    """

    HEADERS = [
        "timestamp", "s",
        "speed_trainer", "cadence_trainer", "power_trainer",
        "total_distance_trainer", "resistance_trainer", "elapsed_time_trainer",
        "offset_lorenz", "speed_avg_lorenz", "torque_lorenz", "power_lorenz",
        "Valore1", "Valore2", "Valore3", "Valore4"
    ]

    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.start_time = time.time()
        self.output_dir = "output"
        self._lock = threading.Lock()
        self._buffer = []
        self._closed = False
        self._file_index = 1
        self._base_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        self._create_output_dir()
        self.xlsx_filename = self._make_filename(self._file_index)
        self._initialize_file(self.xlsx_filename)

        self._flush_stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._periodic_flush_worker,
            name="DataProcessor-FlushWorker",
            daemon=True
        )
        self._flush_thread.start()
        self.log.info(
            f"DataProcessor avviato. File: {self.xlsx_filename} -- "
            f"flush ogni {FLUSH_INTERVAL_SECONDS}s -- "
            f"rotazione a {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB"
        )

    # ------------------------------------------------------------------
    # Setup / helpers
    # ------------------------------------------------------------------

    def _make_filename(self, index: int) -> str:
        suffix = f"_part{index:02d}" if index > 1 else ""
        return os.path.join(
            self.output_dir,
            f"{self._base_timestamp}_bike_data_log{suffix}.xlsx"
        )

    def _create_output_dir(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            self.log.error(f"Impossibile creare la cartella di output: {e}")
            raise

    def _initialize_file(self, filename: str):
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Bike Data"
            ws.append(self.HEADERS)
            wb.save(filename)
            self.log.info(f"File inizializzato: {filename}")
        except Exception as e:
            self.log.error(f"Errore nella creazione del file Excel '{filename}': {e}")
            raise

    # ------------------------------------------------------------------
    # Scrittura dati
    # ------------------------------------------------------------------

    def handle_bike_data(self, data: dict):
        if self._closed:
            self.log.warning("handle_bike_data chiamato dopo close() -- riga ignorata.")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        elapsed_seconds = round(time.time() - self.start_time, 3)

        row = [
            timestamp,
            elapsed_seconds,
            data.get("Spd"),
            data.get("Cad"),
            data.get("Pwr"),
            data.get("TotDist"),
            data.get("Res"),
            data.get("ElaTime"),
            data.get("offset_lorenz"),
            data.get("speed_avg_lorenz"),
            data.get("torque_lorenz"),
            data.get("power_lorenz"),
            data.get("Valore1"),
            data.get("Valore2"),
            data.get("Valore3"),
            data.get("Valore4"),
        ]

        try:
            with self._lock:
                self._buffer.append(row)
        except Exception as e:
            self.log.error(f"Errore nell'aggiunta della riga al buffer: {e}")

    # ------------------------------------------------------------------
    # Flush e rotazione
    # ------------------------------------------------------------------

    def _flush_buffer(self):
        """
        Appende le righe del buffer al file corrente, svuota il buffer,
        poi verifica se occorre ruotare il file.
        DEVE essere chiamato con self._lock gia' acquisito.
        """
        if not self._buffer:
            return

        rows_to_write = self._buffer[:]
        self._buffer.clear()
        n = len(rows_to_write)

        try:
            wb = load_workbook(self.xlsx_filename)
            ws = wb.active
            for row in rows_to_write:
                ws.append(row)
            wb.save(self.xlsx_filename)
            self.log.debug(
                f"Flush: {n} righe scritte su '{os.path.basename(self.xlsx_filename)}'"
            )
        except Exception as e:
            self.log.error(
                f"Errore nel flush su disco: {e} -- "
                f"le {n} righe vengono rimesse nel buffer"
            )
            self._buffer[:0] = rows_to_write
            return

        self._check_rotation()

    def _check_rotation(self):
        """
        Se il file corrente supera MAX_FILE_SIZE_BYTES crea un nuovo file.
        DEVE essere chiamato con self._lock gia' acquisito.
        """
        try:
            size = os.path.getsize(self.xlsx_filename)
        except OSError:
            return

        if size >= MAX_FILE_SIZE_BYTES:
            self._file_index += 1
            new_filename = self._make_filename(self._file_index)
            self.log.info(
                f"Rotazione file: '{os.path.basename(self.xlsx_filename)}' "
                f"ha raggiunto {size / (1024 * 1024):.1f} MB. "
                f"Nuovo file: '{os.path.basename(new_filename)}'"
            )
            self._initialize_file(new_filename)
            self.xlsx_filename = new_filename

    def flush(self):
        """Forza un flush immediato. Thread-safe."""
        with self._lock:
            self._flush_buffer()

    def _periodic_flush_worker(self):
        while not self._flush_stop_event.wait(timeout=FLUSH_INTERVAL_SECONDS):
            if self._closed:
                break
            with self._lock:
                if self._buffer:
                    self.log.info(f"Flush periodico: {len(self._buffer)} righe in coda.")
                    self._flush_buffer()

    # ------------------------------------------------------------------
    # Chiusura
    # ------------------------------------------------------------------

    def close(self):
        """
        Ferma il thread di flush e garantisce il salvataggio di tutte le righe.
        Idempotente: sicuro da chiamare piu' volte.
        """
        if self._closed:
            return
        self._closed = True
        self._flush_stop_event.set()
        self._flush_thread.join(timeout=5.0)

        with self._lock:
            pending = len(self._buffer)
            if pending:
                self.log.info(f"Flush finale: {pending} righe rimaste nel buffer.")
            self._flush_buffer()

        self.log.info(f"DataProcessor chiuso. Ultimo file: {self.xlsx_filename}")

    # ------------------------------------------------------------------
    # Lettura comandi CSV
    # ------------------------------------------------------------------

    @staticmethod
    def read_brake_commands_from_csv(file_path: str) -> list:
        log = logging.getLogger(__name__)
        brake_commands = []
        try:
            with open(file_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)
                for line_num, row in enumerate(reader, start=2):
                    try:
                        if len(row) < 4:
                            log.warning(f"CSV riga {line_num}: meno di 4 colonne, saltata.")
                            continue

                        if row[1].strip():
                            command_type = "livelli"
                            value = int(row[1].strip())
                        elif row[2].strip():
                            command_type = "potenza"
                            value = int(row[2].strip())
                        elif row[3].strip():
                            command_type = "simulazione"
                            value = int(row[3].strip())
                        else:
                            log.warning(f"CSV riga {line_num}: nessun comando valido, saltata.")
                            continue

                        wait_time = int(row[0].strip())
                        speed_banco = None
                        if len(row) >= 5 and row[4].strip():
                            speed_banco = int(row[4].strip())

                        brake_commands.append((command_type, value, wait_time, speed_banco))

                    except (ValueError, IndexError) as e:
                        log.warning(f"CSV riga {line_num}: errore di parsing ({e}), saltata.")

        except FileNotFoundError:
            log.error(f"File CSV non trovato: {file_path}")
        except Exception as e:
            log.error(f"Errore nella lettura del CSV '{file_path}': {e}")

        log.info(f"Letti {len(brake_commands)} comandi da '{file_path}'")
        return brake_commands