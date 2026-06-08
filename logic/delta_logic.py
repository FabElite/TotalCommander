"""
Funzioni pure per il calcolo, la formattazione e la colorazione dei delta BLE ↔ Lorenz.
Nessuna dipendenza da tkinter o da altri moduli del progetto.
"""


# ── Calcolo ──────────────────────────────────────────────────────────────────

def compute_speed_delta(ble_val, lrz_val):
    """Restituisce (BLE - Lorenz) in km/h, o None se non calcolabile."""
    try:
        if ble_val is None or lrz_val is None:
            return None
        return float(ble_val) - float(lrz_val)
    except Exception:
        return None


def compute_power_delta_pct(ble_val, lrz_val):
    """Restituisce (BLE - Lorenz) / Lorenz * 100, o None se non calcolabile / Lorenz==0."""
    try:
        if ble_val is None or lrz_val is None:
            return None
        lrz = float(lrz_val)
        if lrz == 0:
            return None
        return (float(ble_val) - lrz) / lrz * 100.0
    except Exception:
        return None


def mean_or_none(values):
    """Media di un iterable escludendo i None; None se vuoto."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


# ── Colori ───────────────────────────────────────────────────────────────────

def color_for_speed_delta(abs_kmh, thresholds=(1.0, 3.0)):
    """Verde / arancione / rosso in base al delta di velocità assoluto."""
    if abs_kmh is None:
        return "#666666"
    t1, t2 = thresholds
    a = float(abs_kmh)
    return "#0A7A0A" if a <= t1 else ("#C98000" if a <= t2 else "#B00000")


def color_for_power_delta(pct, thresholds=(2.0, 5.0)):
    """Verde / arancione / rosso in base al delta di potenza percentuale."""
    if pct is None:
        return "#666666"
    t1, t2 = thresholds
    a = abs(float(pct))
    return "#0A7A0A" if a <= t1 else ("#C98000" if a <= t2 else "#B00000")


# ── Formattazione ─────────────────────────────────────────────────────────────

def fmt_speed_delta(diff_kmh):
    if diff_kmh is None:
        return "—"
    sign = "+" if diff_kmh >= 0 else "−"
    return f"{sign}{abs(diff_kmh):.2f} km/h"


def fmt_power_delta(pct):
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else "−"
    return f"{sign}{abs(pct):.1f}%"