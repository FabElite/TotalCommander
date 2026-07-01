"""
Controller dei dispositivi non-BLE.

Ognuno incapsula la propria libreria hardware + l'executor e riporta gli
aggiornamenti alla UI tramite callback iniettati dall'app (così i controller
non conoscono i widget). Le due cadenze periodiche (check 1 s, poll 100 ms)
restano schedulate dall'app, che a ogni tick chiama check()/poll().

Costanti di configurazione hardware centralizzate qui (prima sparse in
MainWindow come numeri magici).
"""
import logging
import re
import time
from collections import deque
from types import SimpleNamespace

from shared_lib.funzioni_accessorie import trova_porta_usb_serial
from shared_lib.ScpiAlimentatore import Alimentatore, SCPIError

# ── Configurazione hardware ──────────────────────────────────────────────────
LORENZ_FULL_SCALE_NM   = 200.0
LORENZ_PORT_DESCRIPTION = "Lorenz USB sensor interface Port"
BANCO_MAX_SPEED_KMH    = 80.0
PSU_MEASURE_INTERVAL_MS = 1000

_SEP_LINE = "=" * 55


def _log_disconnect_lost(log, name: str) -> None:
    """Banner uniforme di perdita connessione (prima ripetuto in ogni check())."""
    log.warning(_SEP_LINE)
    log.warning(f"*** DISCONNESSIONE {name} - connessione persa ***")
    log.warning(_SEP_LINE)


class _ConnTransitionMixin:
    """Fornisce check() con logging di transizione, dato is_connected().

    Elimina la ripetizione del blocco 'stato + rilevamento perdita connessione'
    presente in quasi tutti i controller. La classe che lo usa deve:
      - definire is_connected() -> bool
      - avere gli attributi self.on_status, self.log, self._was_connected
      - impostare l'attributo di classe _status_name (etichetta nel banner)
    e può opzionalmente sovrascrivere _on_disconnect_lost() per azioni extra
    (es. spegnere un tick periodico o pulire i widget).
    """
    _status_name = "DISPOSITIVO"

    def _on_disconnect_lost(self) -> None:
        """Hook chiamato una sola volta alla perdita di connessione."""
        pass

    def check(self):
        connected = self.is_connected()
        self.on_status('ok' if connected else 'err')
        if connected:
            self._was_connected = True
        elif self._was_connected:
            _log_disconnect_lost(self.log, self._status_name)
            self._was_connected = False
            self._on_disconnect_lost()


# ═════════════════════════════════════════════════════════════════════════════
# Lorenz (sensore coppia/potenza su USB dedicata)
# ═════════════════════════════════════════════════════════════════════════════

class LorenzController(_ConnTransitionMixin):
    _status_name = "LORENZ"

    def __init__(self, reader, executor, ui_after,
                 on_status, on_data, on_hz,
                 port_description: str = LORENZ_PORT_DESCRIPTION):
        self.reader = reader
        self.executor = executor
        self.ui_after = ui_after
        self.on_status = on_status      # on_status(state: str)
        self.on_data = on_data          # on_data(dict)
        self.on_hz = on_hz              # on_hz(hz | None)
        self.port_description = port_description
        self.log = logging.getLogger(__name__)
        self._was_connected = False
        self._timestamps: deque = deque(maxlen=10)

    def connect(self):
        self.log.info("Connessione Lorenz in corso...")
        self.executor.submit(self._connect_worker)

    def _connect_worker(self):
        try:
            port = trova_porta_usb_serial(self.port_description)
            if port:
                match = re.search(r'(\d+)$', port)
                if not match:
                    raise ValueError(f"Impossibile estrarre il numero di porta da: {port!r}")
                ok = self.reader.open_connection(int(match.group(1)))
            else:
                ok = False
        except Exception as e:
            self.log.error(f"Errore connessione Lorenz: {e}")
            ok = False
        self.ui_after(self._connect_result, ok)

    def _connect_result(self, ok):
        if ok:
            self.log.info("Lorenz connesso")
        else:
            self.log.warning("Lorenz non connesso.")

    def disconnect(self):
        self.log.info("Disconnessione Lorenz in corso...")
        self._was_connected = False
        self.executor.submit(self._disconnect_worker)

    def _disconnect_worker(self):
        ok = self.reader.close_connection()
        msg = "Lorenz disconnesso." if ok else "Lorenz: nessuna connessione attiva."
        self.ui_after(self.log.info if ok else self.log.warning, msg)

    def is_connected(self) -> bool:
        return self.reader.is_connected()

    def poll(self):
        if self.reader.is_connected():
            data = self.reader.get_data()
            self.on_data(data)
            now = time.monotonic()
            self._timestamps.append(now)
            if len(self._timestamps) >= 2:
                span = self._timestamps[-1] - self._timestamps[0]
                if span > 0:
                    self.on_hz((len(self._timestamps) - 1) / span)
        else:
            if self._timestamps:
                self._timestamps.clear()
                self.on_hz(None)


# ═════════════════════════════════════════════════════════════════════════════
# Sensore seriale COM (fino a 4 valori)
# ═════════════════════════════════════════════════════════════════════════════

class SerialSensorController(_ConnTransitionMixin):
    _status_name = "SENSORE SERIALE"

    def __init__(self, reader, executor, ui_after, on_status, on_data):
        self.reader = reader
        self.executor = executor
        self.ui_after = ui_after
        self.on_status = on_status
        self.on_data = on_data
        self.log = logging.getLogger(__name__)
        self._was_connected = False

    def connect(self, port: str):
        if not port:
            self.log.warning("Seleziona una COM port prima di connettere.")
            return
        self.log.info(f"Connessione sensore seriale su {port}...")
        self.executor.submit(self._connect_worker, port)

    def _connect_worker(self, port):
        ok = self.reader.open_connection(port)
        if ok:
            self.ui_after(self.log.info, "Sensore seriale connesso")
        else:
            self.ui_after(self.log.warning, "Sensore seriale non connesso.")

    def disconnect(self):
        self.log.info("Disconnessione sensore seriale in corso...")
        self._was_connected = False
        self.executor.submit(self._disconnect_worker)

    def _disconnect_worker(self):
        ok = self.reader.close_connection()
        msg = "Sensore seriale disconnesso." if ok else "Sensore: nessuna connessione attiva."
        self.ui_after(self.log.info if ok else self.log.warning, msg)

    def is_connected(self) -> bool:
        return self.reader.connected

    def poll(self):
        if self.reader.connected:
            self.on_data(self.reader.get_data())


# ═════════════════════════════════════════════════════════════════════════════
# Banco (motore via Modbus TCP)
# ═════════════════════════════════════════════════════════════════════════════

class BancoController:
    def __init__(self, modbus, executor, ui_after, on_status,
                 max_speed_kmh: float = BANCO_MAX_SPEED_KMH):
        self.modbus = modbus
        self.executor = executor
        self.ui_after = ui_after
        self.on_status = on_status
        self.max_speed_kmh = max_speed_kmh
        self.log = logging.getLogger(__name__)
        self._was_connected = False

    def connect(self, ip: str):
        self.log.info(f"Connessione Banco a {ip}...")
        self.executor.submit(self._connect_worker, ip)

    def _connect_worker(self, ip):
        try:
            self.modbus.connetti(ip, 502)
            if self.modbus.is_connesso():
                self.log.info(f"Banco connesso: {ip}")
            else:
                self.log.warning(f"Connessione Banco fallita: {ip} non raggiungibile.")
        except Exception as e:
            self.log.error(f"Errore connessione Banco: {e}")
        finally:
            self.ui_after(self.check, True)

    def disconnect(self):
        self.log.info("Disconnessione Banco in corso...")
        self.executor.submit(self._disconnect_worker)

    def _disconnect_worker(self):
        try:
            self._was_connected = False
            self.modbus.disconnetti()
            self.log.info("Banco disconnesso.")
        except Exception as e:
            self.log.error(f"Errore disconnessione Banco: {e}")
        finally:
            self.ui_after(self.check, True)

    def set_speed(self, speed_kmh):
        self.log.debug(f"Velocità banco: {speed_kmh} km/h (invio in corso...)")
        self.executor.submit(self._set_speed_worker, speed_kmh)

    def _set_speed_worker(self, speed_kmh):
        try:
            if speed_kmh is None:
                raise ValueError("La velocità non può essere None")
            if speed_kmh > self.max_speed_kmh:
                raise ValueError(f"Velocità > {self.max_speed_kmh:.0f} km/h. Comando rifiutato.")
            if self.modbus.set_motor_speed(speed_kmh * 10):
                self.log.info(f"Velocità banco {speed_kmh} km/h impostata.")
            else:
                self.log.info("Comando velocità non riuscito.")
        except Exception as e:
            self.log.error(f"Errore velocità banco: {e}")

    def is_connected(self) -> bool:
        return self.modbus.is_connesso()

    def check(self, from_user_action=False):
        connected = self.modbus.is_connesso()
        self.on_status('ok' if connected else 'err')
        if connected:
            if not self._was_connected:
                self.log.debug("Modbus: connessione attiva (check periodico).")
            self._was_connected = True
        else:
            if self._was_connected:
                _log_disconnect_lost(self.log, "MODBUS")
            elif from_user_action:
                self.log.debug("Modbus: nessuna connessione attiva da chiudere.")
            self._was_connected = False


# ═════════════════════════════════════════════════════════════════════════════
# PSU (alimentatore SCPI)
# ═════════════════════════════════════════════════════════════════════════════

class PsuController(_ConnTransitionMixin):
    _status_name = "PSU"

    def __init__(self, executor, ui_after, schedule, cancel,
                 on_status, on_measure, on_clear):
        # schedule(ms, fn) -> id ; cancel(id) : per il tick di misura periodico
        self.executor = executor
        self.ui_after = ui_after
        self.schedule = schedule
        self.cancel = cancel
        self.on_status = on_status      # on_status(state)
        self.on_measure = on_measure    # on_measure(v, i, p)
        self.on_clear = on_clear        # on_clear()
        self.log = logging.getLogger(__name__)
        self.psu = None                 # Alimentatore | None (None = mai connesso)
        self._was_connected = False
        self._update_id = None

    def connect(self, port: str):
        if not port:
            self.log.warning("Selezionare una porta COM per il PSU.")
            return
        self.log.info(f"Connessione PSU su {port}...")
        self.executor.submit(self._connect_worker, port)

    def _connect_worker(self, port):
        try:
            psu = Alimentatore(port)
            psu.connect()
            idn = psu.identify()
            self.psu = psu
            self.ui_after(self.log.info, f"PSU connesso: {idn}")
            self.ui_after(self._start_update)
        except SCPIError as e:
            self.log.error(f"Errore connessione PSU: {e}")

    def disconnect(self):
        self.log.info("Disconnessione PSU in corso...")
        self._was_connected = False
        self._stop_update()
        self.executor.submit(self._disconnect_worker)

    def _disconnect_worker(self):
        try:
            if self.psu is not None:
                self.psu.disconnect()
                self.psu = None
                self.ui_after(self.log.info, "PSU disconnesso.")
                self.ui_after(self.on_clear)
        except Exception as e:
            self.log.error(f"Errore disconnessione PSU: {e}")

    def is_connected(self) -> bool:
        return self.psu is not None and self.psu.is_connected()

    def _on_disconnect_lost(self):
        # Alla perdita di connessione: ferma il tick di misura e pulisci i widget.
        self._stop_update()
        self.ui_after(self.on_clear)

    def _start_update(self):
        self._stop_update()
        self._tick()

    def stop_updates(self):
        """Ferma il tick di misura periodico (usato alla chiusura dell'app)."""
        self._stop_update()

    def _stop_update(self):
        if self._update_id is not None:
            self.cancel(self._update_id)
            self._update_id = None

    def _tick(self):
        if self.is_connected():
            self.executor.submit(self._measure_worker)
        self._update_id = self.schedule(PSU_MEASURE_INTERVAL_MS, self._tick)

    def _measure_worker(self):
        try:
            m = self.psu.measure_all()
            self.ui_after(self.on_measure, m.tensione, m.corrente, m.potenza)
        except Exception as e:
            self.log.debug(f"PSU misura fallita: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Gamma Sensor (seriale, parsing frame hardware)
# ═════════════════════════════════════════════════════════════════════════════

class GammaController(_ConnTransitionMixin):
    _status_name = "GAMMA"

    def __init__(self, reader, executor, ui_after, on_status, on_data, on_clear):
        self.reader = reader
        self.executor = executor
        self.ui_after = ui_after
        self.on_status = on_status
        self.on_data = on_data          # on_data(SimpleNamespace dgs/tpr/trigger)
        self.on_clear = on_clear
        self.log = logging.getLogger(__name__)
        self._was_connected = False

    def connect(self, port: str):
        if not port:
            self.log.warning("Seleziona una porta COM prima di connettere il Gamma Sensor.")
            return
        self.log.info(f"Connessione Gamma Sensor su {port}...")
        self.executor.submit(self._connect_worker, port)

    def _connect_worker(self, port):
        # GammaLib.open_connection() vuole solo il numero di porta (aggiunge "COM").
        match = re.search(r'\d+$', port)
        port_id = match.group() if match else port
        self.reader.open_connection(port_id)
        if self.is_connected():
            self.ui_after(self.log.info, f"Gamma Sensor connesso su {port}")
        else:
            self.ui_after(self.log.warning, f"Gamma Sensor: connessione a {port} fallita.")

    def disconnect(self):
        self.log.info("Disconnessione Gamma Sensor in corso...")
        self._was_connected = False
        self.executor.submit(self._disconnect_worker)

    def _disconnect_worker(self):
        self.reader.close()
        self.ui_after(self.log.info, "Gamma Sensor disconnesso.")
        self.ui_after(self.on_clear)

    def is_connected(self) -> bool:
        return (
            self.reader.ser is not None
            and self.reader.read_thread is not None
            and self.reader.read_thread.is_alive()
        )

    def _on_disconnect_lost(self):
        # Alla perdita di connessione: pulisci i widget del Gamma Sensor.
        self.ui_after(self.on_clear)

    def poll(self):
        if not self.is_connected():
            return
        new_data = False
        dgs = tpr = trigger = None
        with self.reader.lock:
            if self.reader.new_data_flag:
                new_data = True
                dgs = self.reader.DGS_value
                tpr = self.reader.TPR_value
                trigger = self.reader.trigger_value
                self.reader.new_data_flag = False
        if new_data:
            self.on_data(SimpleNamespace(dgs=dgs, tpr=tpr, trigger=trigger))