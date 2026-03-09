"""
Barra di stato orizzontale in cima alla finestra.
Espone metodi pubblici per aggiornare LED e label; non contiene logica applicativa.
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
        self._build()

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _sep(self, col):
        tk.Frame(self, bg=_SEP, width=1, height=20).grid(row=0, column=col, padx=(10, 14))

    def _make_led_group(self, col, label_text, extra_fn=None):
        g = tk.Frame(self, bg=_BG)
        g.grid(row=0, column=col, padx=10)
        led = tk.Label(g, text='●', bg=_BG, fg='#555555', font=('Helvetica', 25))
        led.grid(row=0, column=0, padx=(0, 3))
        tk.Label(g, text=label_text, bg=_BG, fg='#aaaacc',
                 font=('Helvetica', 8)).grid(row=0, column=1)
        if extra_fn:
            extra_fn(g)
        return led

    def _build(self):
        # UI Watchdog pulse
        g_ui = tk.Frame(self, bg=_BG)
        g_ui.grid(row=0, column=0, padx=(12, 0))
        self._led_ui = tk.Label(g_ui, text='●', bg=_BG, fg='#555555',
                                font=('Helvetica', 25))
        self._led_ui.grid(row=0, column=0, padx=(0, 3))
        self._lbl_ui_tick = tk.Label(g_ui, text='UI  0', bg=_BG, fg='#aaaacc',
                                     font=('Helvetica', 8))
        self._lbl_ui_tick.grid(row=0, column=1)
        self._ui_tick     = 0
        self._ui_phase    = False   # alterna i due toni di verde
        self._sep(1)

        # LED connessioni — BLE ha due label extra (nome + indirizzo)
        self._led_ble    = self._make_led_group(2, 'BLE',    extra_fn=self._ble_extra)
        self._led_lorenz = self._make_led_group(3, 'Lorenz')
        self._led_banco  = self._make_led_group(4, 'Banco')
        self._led_com    = self._make_led_group(5, 'COM')
        self._sep(6)

        # Heartbeat
        g_hb = tk.Frame(self, bg=_BG)
        g_hb.grid(row=0, column=7, padx=10)
        self._led_heartbeat = tk.Label(g_hb, text='●', bg=_BG, fg='#555555',
                                       font=('Helvetica', 25))
        self._led_heartbeat.grid(row=0, column=0, padx=(0, 3))
        self._lbl_hz = tk.Label(g_hb, text='-- Hz', bg=_BG, fg='#aaaacc',
                                font=('Helvetica', 8))
        self._lbl_hz.grid(row=0, column=1)
        self._sep(8)

        # Stato comandi automatici
        g_auto = tk.Frame(self, bg=_BG)
        g_auto.grid(row=0, column=9, padx=10)
        self._led_auto = tk.Label(g_auto, text='●', bg=_BG, fg='#555555',
                                  font=('Helvetica', 25))
        self._led_auto.grid(row=0, column=0, padx=(0, 3))
        self._lbl_auto = tk.Label(g_auto, text='Auto: OFF', bg=_BG, fg='#aaaacc',
                                  font=('Helvetica', 8))
        self._lbl_auto.grid(row=0, column=1)

    def _ble_extra(self, g):
        self._lbl_device = tk.Label(g, text='—', bg=_BG, fg='#666688',
                                    font=('Helvetica', 8), anchor='w')
        self._lbl_device.grid(row=0, column=2, padx=(6, 0))
        self._lbl_address = tk.Label(g, text='', bg=_BG, fg='#555577',
                                     font=('Helvetica', 8), anchor='w')
        self._lbl_address.grid(row=1, column=1, columnspan=2, padx=(3, 0), pady=(0, 1))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def pulse_ui(self):
        """Chiamato dal main thread ogni ~500 ms. Fa battere il LED UI."""
        _PULSE = ('#00cc44', '#006622')
        self._ui_phase = not self._ui_phase
        self._ui_tick  = (self._ui_tick + 1) % 10000
        self._led_ui.config(fg=_PULSE[self._ui_phase])
        self._lbl_ui_tick.config(text=f'UI  {self._ui_tick}')

    def set_ble(self, state: str):
        self._led_ble.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_lorenz(self, state: str):
        self._led_lorenz.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_banco(self, state: str):
        self._led_banco.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_com(self, state: str):
        self._led_com.config(fg=_LED_COLORS.get(state, '#555555'))

    def set_device_info(self, name=None, address=None):
        if name or address:
            self._lbl_device.config(text=name or 'Sconosciuto', fg='#88ffaa')
            self._lbl_address.config(text=address or '', fg='#88ffaa')
        else:
            self._lbl_device.config(text='—', fg='#666688')
            self._lbl_address.config(text='')

    def set_heartbeat(self, hz=None):
        """hz=None → LED spento; hz=float → LED verde + frequenza."""
        if hz is None:
            self._led_heartbeat.config(fg='#555555')
            self._lbl_hz.config(text='-- Hz')
        else:
            self._led_heartbeat.config(fg='#00cc44')
            self._lbl_hz.config(text=f'{hz:.1f} Hz')

    def set_auto(self, state: str, label: str):
        """Aggiorna LED + testo del pannello auto (es. 'ok', 'Auto: ON')."""
        self._led_auto.config(fg=_LED_COLORS.get(state, '#555555'))
        self._lbl_auto.config(text=label)