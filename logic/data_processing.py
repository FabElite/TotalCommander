import csv
import logging
import os
import threading
import time
from datetime import datetime

from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter


# Intervallo di flush automatico su disco (secondi)
FLUSH_INTERVAL_SECONDS = 30


class DataProcessor:
    """
    Raccoglie i dati del banco prova e li persiste su file Excel.

    Strategia di scrittura:
    - Le righe nuove vengono accumulate in un buffer in RAM (semplici liste Python).
    - Un thread di background ogni FLUSH_INTERVAL_SECONDS apre il file, appende
      le righe del buffer, salva e svuota il buffer.
    - Il workbook NON viene tenuto in memoria: la RAM occupata è proporzionale
      solo alle righe dell'ultimo intervallo (~30s), mai all'intera durata del test.
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
        self._buffer = []          # righe in attesa di flush — solo liste Python
        self._closed = False

        self._create_output_dir()
        self.xlsx_filename = os.path.join(
            self.output_dir,
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bike_data_log.xlsx"
        )
        self._initialize_file()

        # Thread di flush periodico (daemon: si chiude con il programma)
        self._flush_stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._periodic_flush_worker,
            name="DataProcessor-FlushWorker",
            daemon=True
        )
        self._flush_thread.start()
        self.log.info(
            f"DataProcessor avviato. File: {self.xlsx_filename} "
            f"— flush ogni {FLUSH_INTERVAL_SECONDS}s"
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _create_output_dir(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            self.log.error(f"Impossibile creare la cartella di output '{self.output_dir}': {e}")
            raise

    def _initialize_file(self):
        """Crea il file xlsx su disco con la sola riga di intestazione."""
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Bike Data"
            ws.append(self.HEADERS)
            wb.save(self.xlsx_filename)
            self.log.info(f"File inizializzato: {self.xlsx_filename}")
        except Exception as e:
            self.log.error(f"Errore nella creazione del file Excel: {e}")
            raise

    # ------------------------------------------------------------------
    # Scrittura dati
    # ------------------------------------------------------------------

    def handle_bike_data(self, data: dict):
        """
        Aggiunge una riga al buffer in RAM. Leggerissimo, thread-safe.
        Non tocca il disco.
        """
        if self._closed:
            self.log.warning("handle_bike_data chiamato dopo close() — riga ignorata.")
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
    # Flush su disco
    # ------------------------------------------------------------------

    def _flush_buffer(self):
        """
        Preleva le righe dal buffer, le appende al file su disco e svuota il buffer.
        Deve essere chiamato con il lock GIÀ ACQUISITO dal chiamante.
        """
        if not self._buffer:
            return

        rows_to_write = self._buffer[:]   # copia locale
        self._buffer.clear()              # svuota subito il buffer

        n = len(rows_to_write)
        try:
            wb = load_workbook(self.xlsx_filename)
            ws = wb.active
            for row in rows_to_write:
                ws.append(row)
            wb.save(self.xlsx_filename)
            self.log.debug(f"Flush completato: {n} righe scritte su '{self.xlsx_filename}'")
        except Exception as e:
            self.log.error(f"Errore nel flush su disco: {e} — le {n} righe vengono rimesse nel buffer")
            # In caso di errore rimette le righe in testa al buffer per non perderle
            with threading.Lock():
                self._buffer[:0] = rows_to_write

    def flush(self):
        """Forza un flush immediato. Thread-safe, utilizzabile dall'esterno."""
        with self._lock:
            self._flush_buffer()

    def _periodic_flush_worker(self):
        """Thread di background: esegue flush ogni FLUSH_INTERVAL_SECONDS."""
        while not self._flush_stop_event.wait(timeout=FLUSH_INTERVAL_SECONDS):
            if self._closed:
                break
            with self._lock:
                if self._buffer:
                    self.log.info(
                        f"Flush periodico: {len(self._buffer)} righe in coda."
                    )
                    self._flush_buffer()

    # ------------------------------------------------------------------
    # Chiusura
    # ------------------------------------------------------------------

    def close(self):
        """
        Ferma il thread di flush e scarica su disco tutte le righe rimaste nel buffer.
        Da chiamare esplicitamente alla chiusura del programma o fine test.
        Idempotente: sicuro da chiamare più volte.
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

        self.log.info(f"DataProcessor chiuso. File: {self.xlsx_filename}")

    # ------------------------------------------------------------------
    # Lettura comandi CSV
    # ------------------------------------------------------------------

    @staticmethod
    def read_brake_commands_from_csv(file_path: str) -> list:
        """
        Legge i comandi freno da un file CSV.
        Formato atteso: wait_time ; livelli ; potenza ; simulazione ; speed_banco
        """
        log = logging.getLogger(__name__)
        brake_commands = []
        try:
            with open(file_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)  # Salta intestazione
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



class DataProcessor:
    """
    Raccoglie i dati del banco prova e li persiste su file Excel.

    Strategia di scrittura:
    - Il workbook viene tenuto interamente in RAM.
    - Un thread di background esegue il flush su disco ogni FLUSH_INTERVAL_SECONDS.
    - Un flush finale garantito viene eseguito esplicitamente chiamando close().
    - Tutte le operazioni sul workbook sono protette da un lock per evitare
      race condition in caso di chiamate concorrenti dall'executor.
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
        self._rows_since_last_flush = 0
        self._closed = False

        self._create_output_dir()
        self.xlsx_filename = os.path.join(
            self.output_dir,
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_bike_data_log.xlsx"
        )
        self._initialize_workbook()

        # Avvia il thread di flush periodico (daemon: si chiude con il programma)
        self._flush_thread = threading.Thread(
            target=self._periodic_flush_worker,
            name="DataProcessor-FlushWorker",
            daemon=True
        )
        self._flush_stop_event = threading.Event()
        self._flush_thread.start()
        self.log.info(f"DataProcessor avviato. File: {self.xlsx_filename} — flush ogni {FLUSH_INTERVAL_SECONDS}s")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _create_output_dir(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            self.log.error(f"Impossibile creare la cartella di output '{self.output_dir}': {e}")
            raise

    def _initialize_workbook(self):
        """Crea il workbook in memoria e aggiunge l'intestazione."""
        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Bike Data"
        self.sheet.append(self.HEADERS)
        # Prima scrittura su disco per creare il file subito
        self._save_to_disk()

    # ------------------------------------------------------------------
    # Scrittura dati
    # ------------------------------------------------------------------

    def handle_bike_data(self, data: dict):
        """
        Aggiunge una riga di dati al workbook in memoria.
        Chiamabile da qualsiasi thread. Thread-safe.
        """
        if self._closed:
            self.log.warning("handle_bike_data chiamato dopo close() — riga ignorata.")
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

        # I valori None vengono lasciati come None: openpyxl scrive cella vuota
        # I valori numerici restano numerici per permettere formule/grafici in Excel
        try:
            with self._lock:
                self.sheet.append(row)
                self._rows_since_last_flush += 1
        except Exception as e:
            self.log.error(f"Errore nell'aggiunta della riga al workbook: {e}")

    # ------------------------------------------------------------------
    # Flush su disco
    # ------------------------------------------------------------------

    def _save_to_disk(self):
        """
        Salva il workbook su disco. Deve essere chiamato con il lock già acquisito,
        oppure dall'interno di un contesto protetto.
        """
        try:
            self.workbook.save(self.xlsx_filename)
            self.log.debug(f"Flush su disco completato ({self._rows_since_last_flush} righe nuove). File: {self.xlsx_filename}")
            self._rows_since_last_flush = 0
        except Exception as e:
            self.log.error(f"Errore nel salvataggio del file Excel '{self.xlsx_filename}': {e}")

    def flush(self):
        """Forza un salvataggio su disco immediato. Thread-safe."""
        with self._lock:
            self._save_to_disk()

    def _periodic_flush_worker(self):
        """Thread di background: esegue flush ogni FLUSH_INTERVAL_SECONDS."""
        while not self._flush_stop_event.wait(timeout=FLUSH_INTERVAL_SECONDS):
            if self._closed:
                break
            with self._lock:
                if self._rows_since_last_flush > 0:
                    self.log.info(f"Flush periodico: salvataggio {self._rows_since_last_flush} righe nuove.")
                    self._save_to_disk()

    # ------------------------------------------------------------------
    # Chiusura
    # ------------------------------------------------------------------

    def close(self):
        """
        Ferma il thread di flush e salva il file una ultima volta.
        Da chiamare esplicitamente alla chiusura del programma o fine test.
        """
        if self._closed:
            return
        self._closed = True
        self._flush_stop_event.set()
        self._flush_thread.join(timeout=5.0)

        with self._lock:
            self.log.info(f"Flush finale: salvataggio dati prima della chiusura.")
            self._save_to_disk()

        self.log.info(f"DataProcessor chiuso. File salvato: {self.xlsx_filename}")

    # ------------------------------------------------------------------
    # Lettura comandi CSV
    # ------------------------------------------------------------------

    @staticmethod
    def read_brake_commands_from_csv(file_path: str) -> list:
        """
        Legge i comandi freno da un file CSV.
        Formato atteso: wait_time ; livelli ; potenza ; simulazione ; speed_banco
        """
        log = logging.getLogger(__name__)
        brake_commands = []
        try:
            with open(file_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.reader(file, delimiter=';')
                next(reader)  # Salta intestazione
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