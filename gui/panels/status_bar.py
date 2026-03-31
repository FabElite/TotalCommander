"""
Barra di stato orizzontale in cima alla finestra.
Layout:
  ● UI 234  |  ● BLE  nome  addr  ● FTMS 2.1Hz  |  ● Lorenz  ● Banco  ● COM  |  ● Auto  |  ● REC
"""
import tkinter as tk

_BG = '#1e1e2e'
_SEP = '#444466'
_LED_COLORS = {'ok': '#00cc44', 'err': '#cc2222', 'warn': '#cc8800', 'off': '#555555'}


class StatusBar(tk.Frame):
    """Row 0 della finestra principale."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=_BG, pady=5, **kwargs)
        self.grid_columnconfigure(99, weight=1)
        self._ui_phase = False
        self._rec_phase = False
        self._build()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _sep(self, col):
        tk.Frame(self, bg=_SEP, width=1, height=20).grid(
            row=0, column=col, padx=(10, 14))

    def _led_label(self, parent, text, row=0, col=0, colspan=1):
        lbl = tk.Label(parent, text=text, bg=_BG, fg='#aaaacc', font=('Helvetica', 8))
        lbl.grid(row=row, column=col, columnspan=colspan)
        return lbl

    def _build(self):
        # ── col 0: UI watchdog ────────────────────────────────────────────────
        g_ui = tk.Frame(self, bg=_BG)
        g_ui.grid(row=0, column=0, padx=(12, 0))
        self._led_ui = tk.Label(g_ui, text='●', bg=_BG, fg='#555555',
                                font=('Helvetica', 25))
        self._led_ui.grid(row=0, column=0, padx=(0, 3))
        self._led_label(g_ui, '', col=1)
        self._sep(1)

        # ── col 2: BLE + FTMS (stesso gruppo visivo) ──────────────────────────
        g_ble = tk.Frame(self, bg=_BG)
        g_ble.grid(row=0, column=2, padx=10)

        # LED BLE
        self._led_ble = tk.Label(g_ble, text='●', bg=_BG, fg='#555555',
                                 font=('Helvetica', 25))
        self._led_ble.grid(row=0, column=0, padx=(0, 3))
        self._led_label(g_ble, 'BLE', col=1)
        # nome e indirizzo device
        self._lbl_device = tk.Label(g_ble, text='—', bg=_BG, fg='#666688',
                                    font=('Helvetica', 8), anchor='w')
        self._lbl_device.grid(row=0, column=2, padx=(6, 12))
        self._lbl_address = tk.Label(g_ble, text='', bg=_BG, fg='#555577',
                                     font=('Helvetica', 8), anchor='w')
        self._lbl_address.grid(row=1, column=1, columnspan=3,
                               padx=(3, 12), pady=(0, 1))

        # LED FTMS
        self._led_ftms = tk.Label(g_ble, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_ftms.grid(row=0, column=4, padx=(0, 3))
        self._lbl_ftms = tk.Label(g_ble, text='FTMS', bg=_BG, fg='#aaaacc',
                                  font=('Helvetica', 8))
        self._lbl_ftms.grid(row=0, column=5)
        self._lbl_ftms_hz = tk.Label(g_ble, text='', bg=_BG, fg='#aaaacc',
                                     font=('Helvetica', 8))
        self._lbl_ftms_hz.grid(row=1, column=4, columnspan=2,
                               padx=(3, 0), pady=(0, 1))

        self._sep(3)

        # ── col 4-7: Lorenz, Banco, COM, PSU ─────────────────────────────────
        for col, label, attr in [(4, 'Lorenz', '_led_lorenz'),
                                 (5, 'Banco',  '_led_banco'),
                                 (6, 'COM',    '_led_com'),
                                 (7, 'PSU',    '_led_psu')]:
            g = tk.Frame(self, bg=_BG)
            g.grid(row=0, column=col, padx=8)
            led = tk.Label(g, text='●', bg=_BG, fg='#555555',
                           font=('Helvetica', 25))
            led.grid(row=0, column=0, padx=(0, 3))
            self._led_label(g, label, col=1)
            setattr(self, attr, led)

        self._sep(8)

        # ── col 9: Auto ───────────────────────────────────────────────────────
        g_auto = tk.Frame(self, bg=_BG)
        g_auto.grid(row=0, column=9, padx=10)
        self._led_auto = tk.Label(g_auto, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_auto.grid(row=0, column=0, padx=(0, 3))
        self._lbl_auto = self._led_label(g_auto, 'Auto: OFF', col=1)
        self._sep(10)

        # ── col 11: REC ───────────────────────────────────────────────────────
        g_rec = tk.Frame(self, bg=_BG)
        g_rec.grid(row=0, column=11, padx=10)
        self._led_rec = tk.Label(g_rec, text='●', bg=_BG, fg='#555555',
                                 font=('Helvetica', 25))
        self._led_rec.grid(row=0, column=0, padx=(0, 3))
        self._lbl_rec = self._led_label(g_rec, 'REC', col=1)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def pulse_ui(self):
        """Chiamato dal main thread ogni ~500 ms. Fa battere LED UI e LED REC."""
        _PULSE_UI  = ('#00cc44', '#006622')
        _PULSE_REC = ('#cc2222', '#880000')
        self._ui_phase  = not self._ui_phase
        self._rec_phase = not self._rec_phase
        self._led_ui.config(fg=_PULSE_UI[self._ui_phase])
        if self._led_rec.cget('fg') != '#555555':
            self._led_rec.config(fg=_PULSE_REC[self._rec_phase])

    def set_ble(self, state: str):
        self._led_ble.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_lorenz(self, state: str):
        self._led_lorenz.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_banco(self, state: str):
        self._led_banco.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_com(self, state: str):
        self._led_com.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_psu(self, state: str):
        self._led_psu.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_device_info(self, name=None, address=None):
        if name or address:
            self._lbl_device.config(text=name or 'Sconosciuto', fg='#88ffaa')
            self._lbl_address.config(text=address or '', fg='#88ffaa')
        else:
            self._lbl_device.config(text='—', fg='#666688')
            self._lbl_address.config(text='')

    def set_ftms(self, hz=None):
        """
        None     → FTMS disabilitato (LED spento)
        0        → FTMS abilitato, nessun pacchetto ancora (LED verde fisso)
        float>0  → pacchetti in arrivo (LED verde + Hz)
        """
        if hz is None:
            self._led_ftms.config(fg='#555555')
            self._lbl_ftms.config(fg='#aaaacc')
            self._lbl_ftms_hz.config(text='')
        elif hz == 0:
            self._led_ftms.config(fg='#00cc44')
            self._lbl_ftms.config(fg='#88ffaa')
            self._lbl_ftms_hz.config(text='-- Hz')
        else:
            self._led_ftms.config(fg='#00cc44')
            self._lbl_ftms.config(fg='#88ffaa')
            self._lbl_ftms_hz.config(text=f'{hz:.1f} Hz')

    # set_heartbeat mantenuto come alias per retrocompatibilità
    def set_heartbeat(self, hz=None):
        self.set_ftms(hz)

    def set_rec(self, recording: bool):
        """Attiva (rosso pulsante) o disattiva (spento) il LED REC."""
        if not recording:
            self._led_rec.config(fg='#555555')
            self._lbl_rec.config(text='REC', fg='#aaaacc')
        else:
            self._rec_phase = False
            self._led_rec.config(fg='#cc2222')
            self._lbl_rec.config(text='REC', fg='#ff6666')

    def set_auto(self, state: str, label: str):
        self._led_auto.config(fg=_LED_COLORS.get(state, '#555555'))
        self._lbl_auto.config(text=label)