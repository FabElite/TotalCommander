"""
Barra di stato orizzontale in cima alla finestra.
Layout:
  ● UI 234  |  ● BLE  nome  addr  ● FTMS 2.1Hz  |  ● Lorenz  ● Banco  ● COM  |  ● Auto  |  ● REC
"""
import tkinter as tk

from gui.theme import DARK_BG as _BG, SEP as _SEP, LED_COLORS as _LED_COLORS


class StatusBar(tk.Frame):
    """Row 0 della finestra principale."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=_BG, pady=5, **kwargs)
        self.grid_columnconfigure(99, weight=1)
        self._ui_phase = False
        self._rec_phase = False
        self._rec_elapsed = 0          # secondi dall'avvio della registrazione
        self._rec_tick_id = None       # id del after() del contatore
        self._build()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _sep(self, col):
        tk.Frame(self, bg=_SEP, width=1, height=20).grid(
            row=0, column=col, padx=(10, 14))

    def _led_label(self, parent, text, row=0, col=0, colspan=1, rowspan=1):
        lbl = tk.Label(parent, text=text, bg=_BG, fg='#aaaacc',
                       font=('Helvetica', 8))
        lbl.grid(
            row=row,
            column=col,
            columnspan=colspan,
            rowspan=rowspan
        )
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
        # ── Riga 1: dettagli identità (MAC + device number) in un frame dedicato,
        #    così i due valori restano allineati tra loro con spaziatura fissa,
        #    indipendentemente dalle larghezze delle colonne della riga 0 ──────
        g_ble_id = tk.Frame(g_ble, bg=_BG)
        g_ble_id.grid(row=1, column=1, columnspan=5, sticky='w',
                      padx=(3, 0), pady=(0, 1))

        # Etichetta dell'indirizzo: NON "BLE" (già presente in riga 0 accanto al
        # LED); "MAC" distingue l'indirizzo dal device number sulla stessa riga.
        self._cap_address = tk.Label(g_ble_id, text='', bg=_BG, fg='#666688',
                                     font=('Helvetica', 8))
        self._cap_address.pack(side='left')
        self._lbl_address = tk.Label(g_ble_id, text='', bg=_BG, fg='#555577',
                                     font=('Helvetica', 8))
        self._lbl_address.pack(side='left', padx=(4, 16))

        # Device number (uint16 LE letto da EEPROM @ addr 2)
        self._cap_devnum = tk.Label(g_ble_id, text='', bg=_BG, fg='#666688',
                                    font=('Helvetica', 8))
        self._cap_devnum.pack(side='left')
        self._lbl_devnum = tk.Label(g_ble_id, text='', bg=_BG, fg='#555577',
                                    font=('Helvetica', 8))
        self._lbl_devnum.pack(side='left', padx=(4, 0))

        # LED FTMS
        self._led_ftms = tk.Label(g_ble, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_ftms.grid(row=0, column=4, padx=(0, 3))
        self._lbl_ftms = tk.Label(g_ble, text='FTMS', bg=_BG, fg='#aaaacc',
                                  font=('Helvetica', 8))
        self._lbl_ftms.grid(row=0, column=5)

        self._sep(3)

        # ── col 4-5: Lorenz, Banco ────────────────────────────────────────────
        for col, label, attr in [(4, 'Lorenz', '_led_lorenz'),
                                 (5, 'Banco',  '_led_banco')]:
            g = tk.Frame(self, bg=_BG)
            g.grid(row=0, column=col, padx=8)
            led = tk.Label(g, text='●', bg=_BG, fg='#555555',
                           font=('Helvetica', 25))
            led.grid(row=0, column=0, padx=(0, 3))
            self._led_label(g, label, col=1)
            setattr(self, attr, led)

        self._sep(6)

        # ── col 7: Auto ───────────────────────────────────────────────────────
        g_auto = tk.Frame(self, bg=_BG)
        g_auto.grid(row=0, column=7, padx=10)
        self._led_auto = tk.Label(g_auto, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_auto.grid(row=0, column=0, padx=(0, 3))
        self._lbl_auto = self._led_label(g_auto, 'Auto: OFF', col=1)
        self._sep(8)

        # ── col 9: REC ───────────────────────────────────────────────────────
        g_rec = tk.Frame(self, bg=_BG)
        g_rec.grid(row=0, column=9, padx=10)
        self._led_rec = tk.Label(g_rec, text='●', bg=_BG, fg='#555555',
                                 font=('Helvetica', 35))
        # rowspan=2: il LED grande determina l'altezza del frame su entrambe le righe
        self._led_rec.grid(row=0, column=0, rowspan=2, padx=(0, 3))
        self._lbl_rec = self._led_label(g_rec, 'REC', col=1, rowspan=2)
        # Contatore tempo — sempre visibile (--:--:-- a riposo)
        self._lbl_rec_time = tk.Label(g_rec, text='--:--:--', bg=_BG, fg='#888899',
                                      font=('Courier', 8))
        self._lbl_rec_time.grid(row=0, column=2, columnspan=2, padx=(10, 0))
        # Frequenza registrazione — seconda riga, dentro l'altezza già occupata dal LED
        self._lbl_rec_hz = tk.Label(g_rec, text='-- Hz', bg=_BG, fg='#888899',
                                    font=('Helvetica', 8))
        self._lbl_rec_hz.grid(row=1, column=2, columnspan=2,
                              padx=(10, 0), pady=(0, 1))

        self._sep(10)
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

    def set_device_info(self, name=None, address=None):
        if name or address:
            self._lbl_device.config(text=name or 'Sconosciuto', fg='#88ffaa')
            self._cap_address.config(text='MAC')
            self._lbl_address.config(text=address or '', fg='#88ffaa')
            self._cap_devnum.config(text='Dev#')
            self._lbl_devnum.config(text='…', fg='#666688')
        else:
            self._lbl_device.config(text='—', fg='#666688')
            self._cap_address.config(text='')
            self._lbl_address.config(text='')
            self._cap_devnum.config(text='')
            self._lbl_devnum.config(text='')

    def set_device_number(self, num=None):
        """Device number letto dal Serial Number del servizio Device Information
        dopo il connect.
        num valorizzato → mostra il valore (verde, coerente con nome/indirizzo).
        num=None        → lettura fallita/assente ('?', ambra)."""
        if num is None:
            self._lbl_devnum.config(text='?', fg='#cc8800')
        else:
            self._lbl_devnum.config(text=str(num), fg='#88ffaa')

    def set_ftms(self, hz=None):
        """
        None  → FTMS disabilitato (LED spento).
        0     → FTMS abilitato, nessun pacchetto ancora (LED verde).
        float → pacchetti in arrivo (LED verde).
        La frequenza Hz è ora mostrata nel LiveDataPanel.
        """
        if hz is None:
            self._led_ftms.config(fg='#555555')
            self._lbl_ftms.config(fg='#aaaacc')
        else:
            self._led_ftms.config(fg='#00cc44')
            self._lbl_ftms.config(fg='#88ffaa')

    def set_rec(self, recording: bool):
        """Attiva (rosso pulsante) o disattiva (spento) il LED REC."""
        if not recording:
            self._stop_rec_tick()
            self._led_rec.config(fg='#555555')
            self._lbl_rec.config(text='REC', fg='#aaaacc')
            self._lbl_rec_time.config(text='--:--:--', fg='#888899')
        else:
            self._rec_phase = False
            self._rec_elapsed = 0
            self._led_rec.config(fg='#cc2222')
            self._lbl_rec.config(text='REC', fg='#ff6666')
            self._lbl_rec_time.config(fg='#ffaaaa')
            self._start_rec_tick()

    # ── Contatore REC ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_elapsed(seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f'{h:02d}:{m:02d}:{s:02d}'

    def _start_rec_tick(self):
        self._stop_rec_tick()
        self._rec_tick()

    def _stop_rec_tick(self):
        if self._rec_tick_id is not None:
            self.after_cancel(self._rec_tick_id)
            self._rec_tick_id = None

    def _rec_tick(self):
        self._lbl_rec_time.config(text=self._fmt_elapsed(self._rec_elapsed))
        self._rec_elapsed += 1
        self._rec_tick_id = self.after(1000, self._rec_tick)

    def set_rec_hz(self, hz=None, active: bool = False):
        """
        Aggiorna la frequenza di campionamento accanto al LED REC.
        hz=None → non configurata (-- Hz).
        hz=int  → mostra X Hz; colore chiaro se active, grigio se idle.
        """
        if hz is None:
            self._lbl_rec_hz.config(text='-- Hz', fg='#888899')
        elif active:
            self._lbl_rec_hz.config(text=f'{int(hz)} Hz', fg='#ffaaaa')
        else:
            self._lbl_rec_hz.config(text=f'{int(hz)} Hz', fg='#888899')

    def set_auto(self, state: str, label: str):
        self._led_auto.config(fg=_LED_COLORS.get(state, '#555555'))
        self._lbl_auto.config(text=label)