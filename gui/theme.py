"""
Costanti grafiche centralizzate.

Prima questi valori erano duplicati (spesso identici) in più pannelli:
la palette LED compariva in status_bar e sidebar, gli accenti BLE/Lorenz
in live_data_panel, connections_bar e csv_panel. Centralizzarli qui evita
che si disallineino e rende un eventuale restyle un'unica modifica.
"""

# ── Sfondi scuri (barre di stato, header dialog) ─────────────────────────────
DARK_BG = '#1e1e2e'
SEP     = '#444466'

# ── Palette LED di stato ─────────────────────────────────────────────────────
LED_OFF = '#555555'
LED_COLORS = {
    'ok':   '#00cc44',
    'err':  '#cc2222',
    'warn': '#cc8800',
    'off':  LED_OFF,
}

# ── Accenti pannello dati live (BLE vs Lorenz) ───────────────────────────────
BLE_ACCENT = '#1565C0'
LRZ_ACCENT = '#B85C00'
BLE_BG     = '#DCE8FA'
LRZ_BG     = '#FAE8D8'
NA_FG      = '#AAAAAA'

# ── Font ricorrenti ──────────────────────────────────────────────────────────
F_SMALL  = ('Helvetica', 7)
F_NORMAL = ('Helvetica', 9)
