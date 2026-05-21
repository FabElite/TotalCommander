import csv
import logging
import os
import threading
import time
from datetime import datetime

from openpyxl import load_workbook, Workbook


# Intervallo di flush automatico su disco (secondi)
FLUSH_INTERVAL_SECONDS = 60

# Dimensione massima del file xlsx prima della rotazione. Default: 50 MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# ── Schema comandi sequenza automatica ───────────────────────────────────────
# Formato file (CSV o xlsx):
#   col 0: comando      → nome del comando (stringa)
#   col 1: tempo_s      → attesa dopo il comando in secondi (int); per spindown
#                         il rullo gestisce i propri tempi, il valore è ignorato
#   col 2: valore_rullo → livello 0-200 / potenza [W] / pendenza [%] (int)
#   col 3: banco_kmh    → velocità banco [km/h] (float, opzionale)
#
# Per aggiungere un nuovo comando: aggiungere una voce qui e il relativo handler
# in main_window._dispatch_command. Nessun'altra parte del codice va toccata.
COMMAND_SCHEMA = {
    #  comando         richiede_valore  richiede_tempo
    "livelli":     {"requires_valore": True,  "requires_tempo": True},
    "potenza":     {"requires_valore": True,  "requires_tempo": True},
    "simulazione": {"requires_valore": True,  "requires_tempo": True},
    "spindown":    {"requires_valore": False, "requires_tempo": False},
}


class DataProcessor:
    """
    Raccoglie i dati del banco prova e li persiste su file Excel.
    """

    HEADERS = [
        "timestamp", "s",
        "speed_trainer", "cadence_trainer", "power_trainer",
        "total_distance_trainer", "resistance_trainer", "elapsed_time_trainer",
        "offset_lorenz", "speed_avg_lorenz", "torque_lorenz", "power_lorenz",
        "Valore1", "Valore2", "Valore3", "Valore4",
        "tensione_psu", "corrente_psu", "potenza_psu"
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

    def start_session(self, session_name: str = ""):
        if self._recording:
            self.log.debug("Sessione precedente in corso: chiusura automatica.")
            self.stop_session()

        self._file_index = 1
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe = session_name.strip().replace(' ', '_') if session_name.strip() else ""
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

    def _make_filename(self, index: int) -> str:
        suffix = f"_part{index:02d}" if index > 1 else ""
        return os.path.join(self.output_dir, f"{self._base_name}{suffix}.xlsx")

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
            data.get("tensione_psu"),
            data.get("corrente_psu"),
            data.get("potenza_psu"),
        ]

        try:
            with self._lock:
                self._buffer.append(row)
        except Exception as e:
            self.log.error(f"Errore nell'aggiunta della riga al buffer: {e}")

    def _flush_buffer(self):
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

    def close(self):
        self.stop_session()

    @staticmethod
    def _parse_command_row(row: list, line_num: int, log) -> tuple | None:
        """
        Interpreta una riga nel nuovo formato standard:
          col 0  comando       → nome comando (stringa)
          col 1  tempo_s       → secondi di attesa / finestra (int)
          col 2  valore_rullo  → livello / potenza / pendenza  (int, se richiesto)
          col 3  banco_kmh     → velocità banco km/h           (float, opzionale)

        Restituisce (command_type, tempo_s, valore_rullo, banco_kmh) o None.
        """
        # Normalizza a stringa pulita
        row = [str(c).strip() if c is not None else "" for c in row]

        if not row or not row[0]:
            return None  # riga vuota o comando assente

        command_type = row[0].lower()

        if command_type not in COMMAND_SCHEMA:
            log.warning(f"Riga {line_num}: comando sconosciuto '{row[0]}', saltata.")
            return None

        schema = COMMAND_SCHEMA[command_type]

        # ── tempo_s ────────────────────────────────────────────────────────────
        tempo_s = 0
        if len(row) > 1 and row[1]:
            try:
                tempo_s = int(float(row[1]))
            except ValueError:
                log.warning(f"Riga {line_num}: tempo_s non valido '{row[1]}', usato 0.")
        elif schema["requires_tempo"]:
            log.warning(f"Riga {line_num}: {command_type} richiede tempo_s, usato 0.")

        # ── valore_rullo ───────────────────────────────────────────────────────
        valore_rullo = None
        if len(row) > 2 and row[2]:
            try:
                valore_rullo = int(float(row[2]))
            except ValueError:
                log.warning(f"Riga {line_num}: valore_rullo non valido '{row[2]}', ignorato.")
        if schema["requires_valore"] and valore_rullo is None:
            log.warning(f"Riga {line_num}: {command_type} richiede valore_rullo, saltata.")
            return None

        # ── banco_kmh ──────────────────────────────────────────────────────────
        banco_kmh = None
        if len(row) > 3 and row[3]:
            try:
                banco_kmh = float(row[3])
            except ValueError:
                log.warning(f"Riga {line_num}: banco_kmh non valido '{row[3]}', ignorato.")

        return (command_type, tempo_s, valore_rullo, banco_kmh)

    @staticmethod
    def _detect_csv_delimiter(file_path: str) -> str:
        """
        Usa csv.Sniffer per rilevare il delimitatore nelle prime righe.
        Candidati: ; , TAB |  — fallback: ';'.
        """
        candidates = [';', ',', '\t', '|']
        try:
            with open(file_path, mode='r', encoding='utf-8-sig') as f:
                sample = f.read(4096)
            dialect = csv.Sniffer().sniff(sample, delimiters=''.join(candidates))
            return dialect.delimiter
        except csv.Error:
            try:
                with open(file_path, mode='r', encoding='utf-8-sig') as f:
                    first_line = next(f, "")
                counts = {d: first_line.count(d) for d in candidates}
                best = max(counts, key=counts.get)
                if counts[best] > 0:
                    return best
            except Exception:
                pass
        return ';'

    @staticmethod
    def read_brake_commands_from_file(file_path: str) -> list:
        """
        Carica la sequenza comandi da CSV (qualsiasi separatore) o Excel (.xlsx/.xls).

        Formato atteso (riga 1 = intestazione, ignorata):
          col 0  comando       → livelli | potenza | simulazione | spindown | …
          col 1  tempo_s       → secondi attesa (int)
          col 2  valore_rullo  → livello / potenza / pendenza (int, se richiesto)
          col 3  banco_kmh     → velocità banco km/h (float, opzionale)

        Restituisce lista di tuple (command_type, tempo_s, valore_rullo, banco_kmh).
        """
        log = logging.getLogger(__name__)
        brake_commands = []
        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext in ('.xlsx', '.xls'):
                wb = load_workbook(file_path, read_only=True, data_only=True)
                ws = wb.active
                for line_num, raw_row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    if all(c is None or str(c).strip() == "" for c in raw_row):
                        continue
                    result = DataProcessor._parse_command_row(list(raw_row), line_num, log)
                    if result:
                        brake_commands.append(result)
                wb.close()

            else:
                delimiter = DataProcessor._detect_csv_delimiter(file_path)
                log.info(f"Separatore CSV rilevato: {repr(delimiter)}")
                with open(file_path, mode='r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    next(reader, None)   # salta intestazione
                    for line_num, row in enumerate(reader, start=2):
                        if not any(c.strip() for c in row):
                            continue
                        result = DataProcessor._parse_command_row(row, line_num, log)
                        if result:
                            brake_commands.append(result)

        except FileNotFoundError:
            log.error(f"File non trovato: {file_path}")
        except Exception as e:
            log.error(f"Errore nella lettura di '{file_path}': {e}")

        log.info(f"Letti {len(brake_commands)} comandi da '{os.path.basename(file_path)}'")
        return brake_commands