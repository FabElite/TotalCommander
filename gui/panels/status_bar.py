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

        # LED BLE (riga 0) + LED FTMS (riga 1), impilati nella stessa colonna
        self._led_ble = tk.Label(g_ble, text='●', bg=_BG, fg='#555555',
                                 font=('Helvetica', 19))
        self._led_ble.grid(row=0, column=0, padx=(0, 3))
        self._led_label(g_ble, 'BLE', row=0, col=1)

        self._led_ftms = tk.Label(g_ble, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 19))
        self._led_ftms.grid(row=1, column=0, padx=(0, 3))
        self._lbl_ftms = tk.Label(g_ble, text='FTMS', bg=_BG, fg='#aaaacc',
                                  font=('Helvetica', 8))
        self._lbl_ftms.grid(row=1, column=1)

        # Riga 0, a dx dei LED: nome device + MAC
        row0 = tk.Frame(g_ble, bg=_BG)
        row0.grid(row=0, column=2, sticky='w', padx=(6, 0))

        self._cap_device = tk.Label(row0, text='', bg=_BG, fg='#666688',
                                    font=('Helvetica', 8), anchor='w')
        self._cap_device.pack(side='left')
        self._lbl_device = tk.Label(row0, text='—', bg=_BG, fg='#666688',
                                    font=('Helvetica', 8), anchor='w')
        self._lbl_device.pack(side='left')
        self._cap_address = tk.Label(row0, text='', bg=_BG, fg='#666688',
                                     font=('Helvetica', 8))
        self._cap_address.pack(side='left', padx=(12, 0))
        self._lbl_address = tk.Label(row0, text='', bg=_BG, fg='#555577',
                                     font=('Helvetica', 8))
        self._lbl_address.pack(side='left', padx=(4, 0))

        # Riga 1, a dx dei LED: FW/SW/HW/Dev# con titoli e valori colorati separatamente
        self._versions_row = tk.Frame(g_ble, bg=_BG)
        self._versions_row.grid(row=1, column=2, sticky='w',
                                padx=(6, 0), pady=(1, 0))

        self._version_value_labels = {}

        version_items = [
            ('FW', 'fw'),
            ('SW', 'sw'),
            ('HW', 'hw'),
            ('Dev#', 'devnum'),
        ]

        for i, (title, key) in enumerate(version_items):
            tk.Label(
                self._versions_row,
                text=f'{title} ',
                bg=_BG,
                fg='#666688',
                font=('Helvetica', 8),
                anchor='w'
            ).pack(side='left')

            value_lbl = tk.Label(
                self._versions_row,
                text='',
                bg=_BG,
                fg='#55ffaa',
                font=('Helvetica', 8),
                anchor='w'
            )
            value_lbl.pack(side='left')

            self._version_value_labels[key] = value_lbl

            if i < len(version_items) - 1:
                tk.Label(
                    self._versions_row,
                    text='   ',
                    bg=_BG,
                    fg='#666688',
                    font=('Helvetica', 8)
                ).pack(side='left')

        self._sep(3)

        # ── Lorenz | Banco (ora separati come tutti gli altri gruppi) ─────────
        g_lor = tk.Frame(self, bg=_BG)
        g_lor.grid(row=0, column=4, padx=8)
        self._led_lorenz = tk.Label(g_lor, text='●', bg=_BG, fg='#555555',
                                    font=('Helvetica', 25))
        self._led_lorenz.grid(row=0, column=0, padx=(0, 3))
        self._led_label(g_lor, 'Lorenz', col=1)

        self._sep(5)

        g_ban = tk.Frame(self, bg=_BG)
        g_ban.grid(row=0, column=6, padx=8)
        self._led_banco = tk.Label(g_ban, text='●', bg=_BG, fg='#555555',
                                   font=('Helvetica', 25))
        self._led_banco.grid(row=0, column=0, padx=(0, 3))
        self._led_label(g_ban, 'Banco', col=1)

        self._sep(7)

        # ── Auto ──────────────────────────────────────────────────────────────
        g_auto = tk.Frame(self, bg=_BG)
        g_auto.grid(row=0, column=8, padx=10)
        self._led_auto = tk.Label(g_auto, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_auto.grid(row=0, column=0, padx=(0, 3))
        self._lbl_auto = self._led_label(g_auto, 'Auto: OFF', col=1)
        self._sep(9)

        # ── REC ───────────────────────────────────────────────────────────────
        g_rec = tk.Frame(self, bg=_BG)
        g_rec.grid(row=0, column=10, padx=10)
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

        self._sep(11)
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
            self._cap_device.config(text='NAME')
            self._lbl_device.config(text=name or 'Sconosciuto', fg='#88ffaa')
            self._cap_address.config(text='MAC')
            self._lbl_address.config(text=address or '', fg='#88ffaa')
        else:
            self._cap_device.config(text='')
            self._lbl_device.config(text='—', fg='#666688')
            self._cap_address.config(text='')
            self._lbl_address.config(text='')

    def set_device_versions(self, fw=None, sw=None, hw=None, devnum=None):
        """
        Riga compatta FW/SW/HW/Dev#, letti dal servizio Device Information
        alla connessione BLE. Senza argomenti pulisce (usare alla disconnessione).
        """
        values = {
            'fw': fw,
            'sw': sw,
            'hw': hw,
            'devnum': devnum,
        }

        if not any(values.values()):
            for lbl in self._version_value_labels.values():
                lbl.config(text='')
            return

        self._version_value_labels['fw'].config(text=str(fw or '—'))
        self._version_value_labels['sw'].config(text=str(sw or '—'))
        self._version_value_labels['hw'].config(text=str(hw or '—'))
        self._version_value_labels['devnum'].config(text=str(devnum or '—'))

    def set_ftms(self, hz=None):
        """
        None  → FTMS disabilitato (LED spento).
        0     → FTMS abilitato, nessun pacchetto ancora (LED verde).
        float → pacchetti in arrivo (LED verde).
        La frequenza Hz è ora mostrata nel LiveDataPanel.
        """
        if hz is None:
            self._led_ftms.config(fg='#555555')
        else:
            self._led_ftms.config(fg='#00cc44')

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