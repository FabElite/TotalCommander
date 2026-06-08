"""
Gestione del file settings.json.
Nessuna dipendenza da tkinter; restituisce e accetta solo dizionari Python.
"""
import json
import os
import logging

DEFAULTS = {
    'avg_dim': 20,
    'invert_speed': False,
    'offset': 0.0,
    'delta_speed_thresholds_kmh': [1.0, 3.0],
    'delta_power_thresholds_pct': [2.0, 5.0],
    'delta_smoothing_window': 5,
    'rec_hz': 2,
    'stop_rec_on_auto_end': True,
    'banco_ip': '192.168.0.10',
}

_log = logging.getLogger(__name__)


def load(filepath: str) -> dict:
    """
    Carica il file JSON e restituisce il dizionario.
    In caso di errore o file mancante restituisce un dizionario vuoto
    (il chiamante applicherà i DEFAULTS).
    """
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            _log.info(f"Impostazioni caricate da {filepath}")
            return data
        _log.debug("File impostazioni non trovato: uso valori di default.")
    except (json.JSONDecodeError, TypeError, ValueError, OSError) as e:
        _log.error(f"Errore nel caricare le impostazioni: {e}. Uso valori di default.")
    return {}


def save(filepath: str, data: dict) -> None:
    """Salva il dizionario su file JSON."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
        _log.debug(f"Impostazioni salvate in {filepath}")
    except IOError as e:
        _log.error(f"Errore nel salvare le impostazioni: {e}")