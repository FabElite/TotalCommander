import csv
import logging
import os
import threading
import time
from datetime import datetime

from openpyxl import load_workbook, Workbook


# Intervallo di flush automatico su disco (secondi)
FLUSH_INTERVAL_SECONDS = 60

# Dimensione massima del file xlsx prima della rotazione. Default: 100 MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


class DataProcessor:
    """
    Raccoglie i dati del banco prova e li persiste su file Excel.

    Strategia di scrittura:
    - Le sessioni sono esplicite: start_session(name) / stop_session().
    - Le righe nuove vengono accumulate in un buffer in RAM (semplici liste Python).
    - Un thread di background ogni FLUSH_INTERVAL_SECONDS appende le righe al file
      su disco e svuota il buffer.
    - Se dopo il flush il file supera MAX_FILE_SIZE_BYTES, viene creato un nuovo
      file con suffisso _part02, _part03, ... con la stessa intestazione.
    - Un flush finale garantito viene eseguito da stop_session() / close().
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
        self.output_dir = "output"
        self._lock = threading.Lock()
        self._buffer = []
        self._recording = False
        self._file_index = 1
        self._base_name = ""
        self.xlsx_filename = None
        self.start_time = None
        self._flush_stop_event = threading.Event()
        self._flush_thread = None
        self._create_output_dir()
        self.log.info("DataProcessor pronto. Nessuna sessione attiva.")

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ------------------------------------------------------------------
    # Gestione sessioni
    # ------------------------------------------------------------------

    def start_session(self, session_name: str = ""):
        """
        Avvia una nuova sessione di registrazione.
        Se una sessione e' gia' attiva, la chiude prima con flush finale.
        Nome file:
          - senza nome personalizzato: YYYYMMDD_HHMMSS_bike_data.xlsx
          - con nome personalizzato:   YYYYMMDD_HHMMSS_<nome>.xlsx
        """
        if self._recording:
            self.log.debug("Sessione precedente in corso: chiusura automatica.")
            self.stop_session()

        self._file_index = 1
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe = session_name.strip().replace(' ', '_') if session_name.strip() else ""
        # Con nome custom: YYYYMMDD_HHMMSS_nome (il suffisso _bike_data non serve)
        # Senza nome:      YYYYMMDD_HHMMSS_bike_data
        self._base_name = f"{ts}_{safe}" if safe else f"{ts}_bike_data"
        self._has_custom_name = bool(safe)
        self.start_time = time.time()

        with self._lock:
            self._buffer.clear()

        self.xlsx_filename = self._make_filename(self._file_index)
        self._initialize_file(self.xlsx_filename)

        self._flush_stop_event.clear()
        self._flush_thread = threading.Thread(
            target=self._periodic_flush_worker,
            name="DataProcessor-FlushWorker",
            daemon=True
        )
        self._flush_thread.start()
        self._recording = True
        self.log.info(
            f"Sessione avviata: {self.xlsx_filename} -- "
            f"flush ogni {FLUSH_INTERVAL_SECONDS}s -- "
            f"rotazione a {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB"
        )

    def stop_session(self):
        """
        Ferma la sessione corrente con flush finale garantito.
        Idempotente: sicuro da chiamare piu' volte.
        """
        if not self._recording:
            return
        self._recording = False
        self._flush_stop_event.set()
        if self._flush_thread is not None:
            self._flush_thread.join(timeout=5.0)
            self._flush_thread = None

        with self._lock:
            pending = len(self._buffer)
            if pending:
                self.log.debug(f"Flush finale: {pending} righe scritte.")
            self._flush_buffer()

        self.log.info(f"Sessione terminata. File: {self.xlsx_filename}")

    # ------------------------------------------------------------------
    # Setup / helpers
    # ------------------------------------------------------------------

    def _make_filename(self, index: int) -> str:
        suffix = f"_part{index:02d}" if index > 1 else ""
        return os.path.join(
            self.output_dir,
            f"{self._base_name}{suffix}.xlsx"
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
            self.log.debug(f"File xlsx inizializzato: {filename}")
        except Exception as e:
            self.log.error(f"Errore nella creazione del file Excel '{filename}': {e}")
            raise

    # ------------------------------------------------------------------
    # Scrittura dati
    # ------------------------------------------------------------------

    def handle_bike_data(self, data: dict):
        if not self._recording:
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
        INTERNAL: deve essere chiamato con self._lock già acquisito dal chiamante.
        """
        if not self._buffer or self.xlsx_filename is None:
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
        """Forza un flush immediato. Thread-safe. No-op se non sta registrando."""
        if not self._recording:
            return
        with self._lock:
            self._flush_buffer()

    def _periodic_flush_worker(self):
        while not self._flush_stop_event.wait(timeout=FLUSH_INTERVAL_SECONDS):
            if not self._recording:
                break
            with self._lock:
                if self._buffer:
                    self.log.debug(f"Flush periodico: {len(self._buffer)} righe in coda.")
                    self._flush_buffer()

    # ------------------------------------------------------------------
    # Chiusura programma
    # ------------------------------------------------------------------

    def close(self):
        """Alias di stop_session() — chiamato da on_closing. Idempotente."""
        self.stop_session()

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