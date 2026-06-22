"""
Coordinatore della registrazione dati.

Incapsula DataProcessor (scrittura bike_data) e SintesiWriter (medie del
comando 'save'), più la logica del tick periodico di scrittura e della
raccolta campioni durante un 'save'. L'app si limita ad aggiornare i widget
(barre REC) e a fornire i provider di stato (rec_hz corrente, sequenza
automatica in esecuzione) e gli scheduler Tk (after / after_cancel).
"""
import logging
import os
import re
import time

from logic.data_processing import DataProcessor, SintesiWriter


class RecordingCoordinator:
    def __init__(self, latest_data, executor, schedule, cancel,
                 rec_hz_provider, auto_running_provider):
        # schedule(ms, fn) -> id ; cancel(id) : scheduler Tk del main thread
        # rec_hz_provider() -> int ; auto_running_provider() -> bool
        self.log = logging.getLogger(__name__)
        self.data_processor = DataProcessor()
        self.sintesi_writer = SintesiWriter(output_dir=self.data_processor.output_dir)
        self._latest = latest_data
        self._executor = executor
        self._schedule = schedule
        self._cancel = cancel
        self._rec_hz = rec_hz_provider
        self._auto_running = auto_running_provider
        self._tick_id = None

    # ── Stato / passthrough ──────────────────────────────────────────────────
    @property
    def is_recording(self) -> bool:
        return self.data_processor.is_recording

    @property
    def xlsx_filename(self):
        return self.data_processor.xlsx_filename

    def start_session(self, session_name: str = ""):
        """Avvia una nuova sessione. Può sollevare in caso di errore I/O."""
        self.data_processor.start_session(session_name)

    def reset_sintesi(self):
        self.sintesi_writer.reset()

    def stop_session(self):
        self.data_processor.stop_session()

    def flush(self):
        self.data_processor.flush()

    def close(self):
        self.data_processor.close()

    # ── Tick di scrittura periodica ──────────────────────────────────────────
    def start_tick(self):
        self._stop_tick_timer()
        self._tick()

    def stop_tick(self):
        self._stop_tick_timer()

    def _stop_tick_timer(self):
        if self._tick_id is not None:
            self._cancel(self._tick_id)
            self._tick_id = None

    def _tick(self):
        """I callback dei sensori tengono i dati aggiornati; qui basta uno
        snapshot atomico e la scrittura delegata all'executor."""
        if self.data_processor.is_recording:
            snapshot = self._latest.snapshot()
            self._executor.submit(self.data_processor.handle_bike_data, snapshot)
        interval_ms = max(100, int(1000 / max(1, self._rec_hz())))
        self._tick_id = self._schedule(interval_ms, self._tick)

    # ── Comando 'save' (raccolta finestra + media) ───────────────────────────
    def collect_save(self, tempo_s: int, etichetta: str, resume_fn):
        """
        Raccoglie snapshot di latest_data per tempo_s secondi, ne calcola la
        media (delegata a SintesiWriter sull'executor) e infine chiama resume_fn.
        La raccolta avviene sul main thread; il countdown della sequenza è
        wall-clock e prosegue indipendente.
        """
        samples: list = []
        interval_ms = max(200, int(1000 / max(1, self._rec_hz())))
        t_end = time.monotonic() + max(float(tempo_s), 0.5)

        # Il file sintesi è legato alla sessione REC corrente: stesso prefisso
        # timestamp del bike_data, senza suffisso _partXX né estensione.
        session_name = None
        if self.data_processor.xlsx_filename:
            base = os.path.basename(self.data_processor.xlsx_filename)
            base = re.sub(r'_part\d+\.xlsx$', '', base)
            base = re.sub(r'\.xlsx$', '', base)
            session_name = base
        rec_file = (os.path.basename(self.data_processor.xlsx_filename)
                    if self.data_processor.xlsx_filename else "")

        def _collect():
            if not self._auto_running():
                # Sequenza interrotta mentre si raccoglieva: non salvare
                resume_fn(False)
                return

            samples.append(self._latest.snapshot())

            remaining_ms = int((t_end - time.monotonic()) * 1000)
            if remaining_ms > 0:
                self._schedule(min(interval_ms, max(50, remaining_ms)), _collect)
            else:
                n = len(samples)
                self.log.debug(
                    f"save: {n} campioni raccolti in {tempo_s}s — scrittura su disco...")
                self._executor.submit(
                    self.sintesi_writer.add_row,
                    samples, tempo_s, etichetta, rec_file, session_name,
                )
                resume_fn(True)

        # Primo campione dopo interval_ms (non immediatamente)
        self._schedule(interval_ms, _collect)
