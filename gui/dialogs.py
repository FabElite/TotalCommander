"""
Dialog dell'applicazione, estratti da MainWindow.

Ogni dialog è una funzione `open_*(app)` (più alcuni helper) che riceve
l'istanza dell'app e ne usa la facade pubblica: app.make_dialog, app.ble
(run/manager/is_ready), app.banco, app.set_banco_speed, app.latest_data,
app.recording, app.psu, app.executor, app.status_bar/live_panel,
app.connected_device_name/address, app.delta_*_thresholds_*, app.rec_hz,
app.save_settings, app.start_recording.
"""
import logging
import os
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from shared_lib.bluetooth_manager import CalibrationPhase


def open_rec_dialog(app):
    win = app.make_dialog("Nuova sessione di registrazione")

    ts_preview = datetime.now().strftime('%Y%m%d_%H%M%S')

    ttk.Label(win, text="Nome sessione (opzionale):",
              font=('Helvetica', 9, 'bold')
              ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 4), sticky='w')

    name_entry = ttk.Entry(win, width=20)
    name_entry.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 4), sticky='ew')
    name_entry.focus()

    preview_var = tk.StringVar(value=f"{ts_preview}_bike_data.xlsx")
    ttk.Label(win, text="File:").grid(row=2, column=0, padx=(16, 4), pady=(4, 2), sticky='e')
    ttk.Label(win, textvariable=preview_var, foreground='#0055aa',
              font=('Helvetica', 8)
              ).grid(row=2, column=1, padx=(0, 16), pady=(4, 2), sticky='w')
    # Nota esplicativa sotto la preview — tk.Label per supportare fg
    tk.Label(win, text="(senza nome → aggiunge _bike_data)",
             font=('Helvetica', 7), fg='#888888'
             ).grid(row=3, column=0, columnspan=2, padx=16, pady=(0, 2))

    def _update_preview(*_):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw = name_entry.get().strip().replace(' ', '_')
        # Con nome: YYYYMMDD_HHMMSS_nome.xlsx — Senza: YYYYMMDD_HHMMSS_bike_data.xlsx
        fname = f"{ts}_{raw}.xlsx" if raw else f"{ts}_bike_data.xlsx"
        preview_var.set(fname)

    name_entry.bind('<KeyRelease>', _update_preview)

    err_var = tk.StringVar()
    ttk.Label(win, textvariable=err_var, foreground='#CC0000',
              font=('Helvetica', 8)
              ).grid(row=4, column=0, columnspan=2, padx=16, pady=(2, 0))

    def _start():
        ok, err = app.start_recording(name_entry.get())
        if not ok:
            err_var.set(err)
            return
        win.destroy()

    bf = ttk.Frame(win)
    bf.grid(row=5, column=0, columnspan=2, pady=(8, 14))
    ttk.Button(bf, text="Avvia", command=_start).grid(row=0, column=0, padx=6)
    ttk.Button(bf, text="Annulla", command=win.destroy).grid(row=0, column=1, padx=6)
    win.bind('<Return>', lambda e: _start())

def open_delta_settings(app):
    win = app.make_dialog("Parametri delta e smoothing")

    pad = dict(padx=12, pady=4)

    ttk.Label(win, text="Soglie Δ Velocità (km/h)",
              font=('Helvetica', 9, 'bold')).grid(
        row=0, column=0, columnspan=3, sticky='w', padx=12, pady=(14, 2))
    ttk.Label(win, text="Verde  ≤").grid(row=1, column=0, sticky='e', **pad)
    spd_t1 = ttk.Entry(win, width=8, justify='right')
    spd_t1.insert(0, str(app.delta_speed_thresholds_kmh[0]))
    spd_t1.grid(row=1, column=1, **pad)
    ttk.Label(win, text="km/h").grid(row=1, column=2, sticky='w', padx=(0, 12))

    ttk.Label(win, text="Arancione  ≤").grid(row=2, column=0, sticky='e', **pad)
    spd_t2 = ttk.Entry(win, width=8, justify='right')
    spd_t2.insert(0, str(app.delta_speed_thresholds_kmh[1]))
    spd_t2.grid(row=2, column=1, **pad)
    ttk.Label(win, text="km/h").grid(row=2, column=2, sticky='w', padx=(0, 12))

    ttk.Separator(win, orient='horizontal').grid(
        row=3, column=0, columnspan=3, sticky='ew', padx=12, pady=6)

    ttk.Label(win, text="Soglie Δ Potenza (%)",
              font=('Helvetica', 9, 'bold')).grid(
        row=4, column=0, columnspan=3, sticky='w', padx=12, pady=(2, 2))
    ttk.Label(win, text="Verde  ≤").grid(row=5, column=0, sticky='e', **pad)
    pwr_t1 = ttk.Entry(win, width=8, justify='right')
    pwr_t1.insert(0, str(app.delta_power_thresholds_pct[0]))
    pwr_t1.grid(row=5, column=1, **pad)
    ttk.Label(win, text="%").grid(row=5, column=2, sticky='w', padx=(0, 12))

    ttk.Label(win, text="Arancione  ≤").grid(row=6, column=0, sticky='e', **pad)
    pwr_t2 = ttk.Entry(win, width=8, justify='right')
    pwr_t2.insert(0, str(app.delta_power_thresholds_pct[1]))
    pwr_t2.grid(row=6, column=1, **pad)
    ttk.Label(win, text="%").grid(row=6, column=2, sticky='w', padx=(0, 12))

    ttk.Separator(win, orient='horizontal').grid(
        row=7, column=0, columnspan=3, sticky='ew', padx=12, pady=6)
    ttk.Label(win, text="Frequenza registrazione",
              font=('Helvetica', 9, 'bold')).grid(
        row=8, column=0, columnspan=3, sticky='w', padx=12, pady=(2, 2))
    ttk.Label(win, text="Frequenza [Hz]:").grid(row=9, column=0, sticky='e', **pad)
    rec_hz_cb = ttk.Combobox(win, values=['1', '2', '4', '10'], width=6,
                             justify='right', state='readonly')
    rec_hz_cb.set(str(app.rec_hz))
    rec_hz_cb.grid(row=9, column=1, **pad)

    err_var = tk.StringVar()
    ttk.Label(win, textvariable=err_var, foreground='#CC0000',
              font=('Helvetica', 8)).grid(
        row=10, column=0, columnspan=3, padx=12, pady=(2, 0))

    def _apply():
        try:
            s1 = float(spd_t1.get())
            s2 = float(spd_t2.get())
            p1 = float(pwr_t1.get())
            p2 = float(pwr_t2.get())
            if s1 <= 0 or s2 <= s1:
                raise ValueError("Soglie velocità: richiede 0 < verde < arancione")
            if p1 <= 0 or p2 <= p1:
                raise ValueError("Soglie potenza: richiede 0 < verde < arancione")
            hz = int(rec_hz_cb.get())
        except ValueError as e:
            err_var.set(str(e))
            return

        app.delta_speed_thresholds_kmh = (s1, s2)
        app.delta_power_thresholds_pct = (p1, p2)
        app.rec_hz                    = hz
        app.live_panel.set_thresholds(
            app.delta_speed_thresholds_kmh,
            app.delta_power_thresholds_pct)
        app.save_settings()
        app.status_bar.set_rec_hz(hz, active=app.recording.is_recording)
        logging.getLogger().info(
            f"Settings updated - spd ({s1},{s2}) km/h | pwr ({p1},{p2})% | REC {hz}Hz")

    bf = ttk.Frame(win)
    bf.grid(row=11, column=0, columnspan=3, pady=(8, 14))
    ttk.Button(bf, text="Applica", command=_apply).grid(
        row=0, column=0, padx=6)
    ttk.Button(bf, text="Annulla", command=win.destroy).grid(
        row=0, column=1, padx=6)

def open_psu_settings(app):
    if app.psu is None or not app.psu.is_connected():
        logging.getLogger().warning("PSU non connesso: impossibile aprire impostazioni.")
        return

    win = app.make_dialog("Impostazioni Alimentatore PSU")

    pad = dict(padx=10, pady=4)
    err_var = tk.StringVar()

    def _show_err(msg):
        err_var.set(msg)
        win.after(3000, lambda: err_var.set(""))

    # ── Uscita ────────────────────────────────────────────────────────────
    ttk.Label(win, text="Uscita", font=('Helvetica', 9, 'bold')).grid(
        row=0, column=0, columnspan=3, sticky='w', padx=10, pady=(12, 2))

    ttk.Label(win, text="Tensione [V]:").grid(row=1, column=0, sticky='e', **pad)
    e_volt = ttk.Entry(win, width=10, justify='right')
    e_volt.insert(0, "0.000")
    e_volt.grid(row=1, column=1, **pad)

    ttk.Label(win, text="Corrente [A]:").grid(row=2, column=0, sticky='e', **pad)
    e_curr = ttk.Entry(win, width=10, justify='right')
    e_curr.insert(0, "0.000")
    e_curr.grid(row=2, column=1, **pad)

    def _apply_vi():
        try:
            v, i = float(e_volt.get()), float(e_curr.get())
            app.executor.submit(lambda: app.psu.apply(v, i))
            logging.getLogger().info(f"PSU: apply({v:.3f} V, {i:.3f} A)")
        except Exception as ex:
            _show_err(str(ex))

    ttk.Button(win, text="⚡ Applica V+I", command=_apply_vi).grid(
        row=1, column=2, rowspan=2, sticky='nsew', padx=(2, 10), pady=4)

    rb = ttk.Frame(win)
    rb.grid(row=3, column=0, columnspan=3, pady=(2, 4))
    ttk.Button(rb, text="▶  Output ON",
               command=lambda: app.executor.submit(app.psu.output_on)
               ).grid(row=0, column=0, padx=6)
    ttk.Button(rb, text="■  Output OFF",
               command=lambda: app.executor.submit(app.psu.output_off)
               ).grid(row=0, column=1, padx=6)

    ttk.Separator(win, orient='horizontal').grid(
        row=4, column=0, columnspan=3, sticky='ew', padx=10, pady=6)

    # ── Protezioni ────────────────────────────────────────────────────────
    ttk.Label(win, text="Protezioni", font=('Helvetica', 9, 'bold')).grid(
        row=5, column=0, columnspan=3, sticky='w', padx=10, pady=(2, 2))

    ttk.Label(win, text="OVP [V]:").grid(row=6, column=0, sticky='e', **pad)
    e_ovp = ttk.Entry(win, width=10, justify='right')
    e_ovp.insert(0, "0.000")
    e_ovp.grid(row=6, column=1, **pad)
    ob = ttk.Frame(win)
    ob.grid(row=6, column=2, padx=(2, 10))
    ttk.Button(ob, text="Abilita",
               command=lambda: app.executor.submit(
                   lambda: app.psu.set_ovp(float(e_ovp.get())))
               ).grid(row=0, column=0, padx=(0, 2))
    ttk.Button(ob, text="Disab.",
               command=lambda: app.executor.submit(app.psu.disable_ovp)
               ).grid(row=0, column=1)

    ttk.Label(win, text="OCP [A]:").grid(row=7, column=0, sticky='e', **pad)
    e_ocp = ttk.Entry(win, width=10, justify='right')
    e_ocp.insert(0, "0.000")
    e_ocp.grid(row=7, column=1, **pad)
    ob2 = ttk.Frame(win)
    ob2.grid(row=7, column=2, padx=(2, 10))
    ttk.Button(ob2, text="Abilita",
               command=lambda: app.executor.submit(
                   lambda: app.psu.set_ocp(float(e_ocp.get())))
               ).grid(row=0, column=0, padx=(0, 2))
    ttk.Button(ob2, text="Disab.",
               command=lambda: app.executor.submit(app.psu.disable_ocp)
               ).grid(row=0, column=1)

    ttk.Separator(win, orient='horizontal').grid(
        row=8, column=0, columnspan=3, sticky='ew', padx=10, pady=6)

    # ── Identificazione ───────────────────────────────────────────────────
    idn_var = tk.StringVar(value="—")
    ttk.Label(win, text="IDN:").grid(row=9, column=0, sticky='e', **pad)
    ttk.Label(win, textvariable=idn_var, foreground='#555555',
              font=('Helvetica', 8), wraplength=180, justify='left'
              ).grid(row=9, column=1, sticky='w', **pad)
    ttk.Button(win, text="Leggi",
               command=lambda: app.executor.submit(
                   lambda: idn_var.set(app.psu.identify()))
               ).grid(row=9, column=2, padx=(2, 10))

    # ── Errori e chiudi ───────────────────────────────────────────────────
    ttk.Label(win, textvariable=err_var, foreground='#CC0000',
              font=('Helvetica', 8)).grid(
        row=10, column=0, columnspan=3, padx=10, pady=(4, 0))
    ttk.Button(win, text="Chiudi", command=win.destroy).grid(
        row=11, column=0, columnspan=3, pady=(6, 14))

def open_eeprom_dialog(app):
    """
    Apre un dialog con indirizzo EEPROM (hex, default 0x0549) e valore
    (0-255, default 70) entrambi editabili. Conferma prima di scrivere.
    """

    if not app.ble.is_ready():
        messagebox.showwarning(
            "Dispositivo non connesso",
            "Nessun trainer BLE connesso.\n"
            "Connetti il dispositivo prima di inviare questo comando.",
            parent=app,
        )
        return

    # ── Dialog ───────────────────────────────────────────────────────────
    win = app.make_dialog("Scrittura EEPROM — cadenza simulata")

    pad = dict(padx=14, pady=4)

    # Dispositivo connesso
    if app.connected_device_name or app.connected_device_address:
        dev_txt = (f"{app.connected_device_name or '?'}"
                   f"  [{app.connected_device_address or '?'}]")
        tk.Label(win, text=dev_txt, font=('Helvetica', 8), fg='#555555'
                 ).grid(row=0, column=0, columnspan=3,
                        padx=14, pady=(12, 4), sticky='w')

    # ── Riga indirizzo ────────────────────────────────────────────────────
    ttk.Label(win, text="Indirizzo EEPROM:").grid(
        row=1, column=0, sticky='e', **pad)
    addr_frame = ttk.Frame(win)
    addr_frame.grid(row=1, column=1, columnspan=2, sticky='w', **pad)
    tk.Label(addr_frame, text="0x", font=('Courier', 9),
             fg='#555555').grid(row=0, column=0)
    addr_entry = ttk.Entry(addr_frame, width=6, justify='left',
                           font=('Courier', 9))
    addr_entry.insert(0, "0549")
    addr_entry.grid(row=0, column=1)
    tk.Label(addr_frame, text="(hex, 0000 – FFFF)",
             font=('Helvetica', 8), fg='#888888'
             ).grid(row=0, column=2, padx=(8, 0))

    # ── Riga valore ───────────────────────────────────────────────────────
    ttk.Label(win, text="Valore (0 – 255):").grid(
        row=2, column=0, sticky='e', **pad)
    spin = ttk.Spinbox(win, from_=0, to=255, increment=1,
                       width=6, justify='right')
    spin.set(70)
    spin.grid(row=2, column=1, sticky='w', **pad)

    hex_var = tk.StringVar(value="0x46")
    tk.Label(win, textvariable=hex_var, font=('Courier', 9),
             fg='#888888').grid(row=2, column=2, sticky='w', padx=(0, 14))

    def _update_hex(*_):
        try:
            hex_var.set(f"0x{int(float(spin.get())):02X}")
        except Exception:
            hex_var.set("—")

    spin.bind('<KeyRelease>', _update_hex)
    spin.bind('<<Increment>>', _update_hex)
    spin.bind('<<Decrement>>', _update_hex)

    # ── Avviso ────────────────────────────────────────────────────────────
    ttk.Separator(win, orient='horizontal').grid(
        row=3, column=0, columnspan=3, sticky='ew', padx=14, pady=(6, 4))
    tk.Label(win,
             text="⚠  Supportato solo su alcuni modelli di trainer.\n"
                  "Su modelli non compatibili il comportamento\n"
                  "potrebbe essere imprevisto.",
             font=('Helvetica', 8), fg='#885500', justify='left'
             ).grid(row=4, column=0, columnspan=3,
                    padx=14, pady=(0, 4), sticky='w')
    ttk.Separator(win, orient='horizontal').grid(
        row=5, column=0, columnspan=3, sticky='ew', padx=14, pady=(4, 2))

    # Errore di validazione
    err_var = tk.StringVar()
    tk.Label(win, textvariable=err_var, font=('Helvetica', 8),
             fg='#CC0000').grid(row=6, column=0, columnspan=3,
                                padx=14, pady=(2, 2))

    # ── Pulsanti ──────────────────────────────────────────────────────────
    def _confirm():
        # Valida indirizzo
        try:
            addr = int(addr_entry.get().strip(), 16)
            if not (0x0000 <= addr <= 0xFFFF):
                raise ValueError
        except ValueError:
            err_var.set("Indirizzo non valido: inserire un valore hex tra 0000 e FFFF.")
            addr_entry.focus()
            return
        # Valida valore
        try:
            value = int(float(spin.get()))
            if not (0 <= value <= 255):
                raise ValueError
        except ValueError:
            err_var.set("Valore non valido: inserire un intero tra 0 e 255.")
            spin.focus()
            return

        win.destroy()
        app.executor.submit(_eeprom_worker, app, addr, value)

    bf = ttk.Frame(win)
    bf.grid(row=7, column=0, columnspan=3, pady=(4, 14))
    ttk.Button(bf, text="Scrivi",   command=_confirm   ).grid(row=0, column=0, padx=6)
    ttk.Button(bf, text="Annulla",  command=win.destroy).grid(row=0, column=1, padx=6)
    win.bind('<Return>', lambda e: _confirm())

def _eeprom_worker(app, address, value):
    """Eseguito nel thread pool: chiama write_eeprom e riporta il risultato al main thread."""
    try:
        ok = app.ble.run(
            app.ble.manager.write_eeprom(address=address, data=bytearray([value]))
        ).result(timeout=10)
    except Exception as e:
        logging.getLogger().error(f"Errore scrittura EEPROM 0x{address:04X}: {e}")
        ok = False

    app.after(0, _eeprom_result, app, ok, address, value)

def _eeprom_result(app, ok, address, value):
    """Chiamato sul main thread per mostrare l'esito all'utente."""
    if ok:
        logging.getLogger().info(
            f"EEPROM 0x{address:04X} = {value} (0x{value:02X}) — scrittura OK.")
    else:
        logging.getLogger().error(
            f"Scrittura EEPROM 0x{address:04X} = {value} fallita.")
        messagebox.showerror(
            "Scrittura fallita",
            "Impossibile scrivere nell'EEPROM del trainer.\n"
            "Verifica la connessione BLE e riprova.",
            parent=app,
        )

def open_device_info(app):
    """Mostra le informazioni DIS (Device Information Service) del dispositivo BLE connesso."""
    if not app.ble.is_ready():
        messagebox.showwarning(
            "Dispositivo non connesso",
            "Nessun trainer BLE connesso.\n"
            "Connetti il dispositivo prima di leggere le informazioni.",
            parent=app,
        )
        return

    win = app.make_dialog("Informazioni Dispositivo", size=(420, 360))

    # ── Header device ─────────────────────────────────────────────────────────
    hf = tk.Frame(win, bg='#1e1e2e')
    hf.pack(fill='x')
    tk.Label(hf, text=app.connected_device_name or "Dispositivo",
             font=('Helvetica', 10, 'bold'), bg='#1e1e2e', fg='#88ffaa',
             ).pack(side='left', padx=12, pady=(7, 2))
    tk.Label(hf, text=app.connected_device_address or "",
             font=('Helvetica', 8), bg='#1e1e2e', fg='#888899',
             ).pack(side='left', pady=(7, 2))

    # ── Griglia campi DIS ────────────────────────────────────────────────────
    _FIELD_LABELS = [
        ('manufacturer_name', 'Produttore'),
        ('model_number', 'Modello'),
        ('serial_number', 'N. Seriale'),
        ('firmware_revision', 'Firmware'),
        ('hardware_revision', 'Hardware Rev.'),
        ('software_revision', 'Software Rev.'),
        ('system_id', 'System ID'),
        ('pnp_id', 'PnP ID'),
    ]

    grid = ttk.Frame(win)
    grid.pack(fill='both', expand=True, padx=14, pady=10)
    grid.grid_columnconfigure(1, weight=1)

    status_var = tk.StringVar(value="Lettura in corso…")
    ttk.Label(grid, textvariable=status_var,
              font=('Helvetica', 8, 'italic'), foreground='#888888',
              ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))

    val_vars = {}
    for i, (key, label) in enumerate(_FIELD_LABELS, start=1):
        ttk.Label(grid, text=label + ":", font=('Helvetica', 9),
                  anchor='e', width=13,
                  ).grid(row=i, column=0, sticky='e', padx=(0, 8), pady=2)
        var = tk.StringVar(value="…")
        ttk.Label(grid, textvariable=var, font=('Helvetica', 9),
                  foreground='#222222', anchor='w',
                  ).grid(row=i, column=1, sticky='w', pady=2)
        val_vars[key] = var

    # ── Pulsanti ─────────────────────────────────────────────────────────────
    bf = ttk.Frame(win)
    bf.pack(fill='x', padx=14, pady=(4, 10))
    btn_refresh = ttk.Button(bf, text="🔄 Aggiorna", command=lambda: _fetch())
    btn_refresh.pack(side='left')
    ttk.Button(bf, text="Chiudi", command=win.destroy).pack(side='right')

    # ── Populate ─────────────────────────────────────────────────────────────
    def _populate(info: dict):
        data = info.get('data', {})
        missing = set(info.get('missing', []))
        for key, var in val_vars.items():
            if key in missing:
                var.set("N/A")
            elif key in data:
                v = data[key]
                if isinstance(v, dict):
                    if key == 'system_id':
                        var.set(
                            f"Manuf: 0x{v.get('manufacturer_id', 0):010X}"
                            f"  OUI: 0x{v.get('oui', 0):06X}"
                        )
                    elif key == 'pnp_id':
                        var.set(
                            f"VID: 0x{v.get('vendor_id', 0):04X}"
                            f"  PID: 0x{v.get('product_id', 0):04X}"
                            f"  Rev: 0x{v.get('product_version', 0):04X}"
                        )
                    else:
                        var.set(str(v))
                else:
                    var.set(str(v) if v else "—")
            else:
                var.set("—")
        status_var.set("Aggiornato")
        btn_refresh.config(state='normal')

    def _fetch():
        btn_refresh.config(state='disabled')
        status_var.set("Lettura in corso…")
        for var in val_vars.values():
            var.set("…")

        def _worker():
            fut = app.ble.run(app.ble.manager.read_device_information(timeout=6.0))
            try:
                info = fut.result(timeout=10)
            except Exception as e:
                logging.getLogger().error(f"Errore lettura device info: {e}")
                info = {'data': {}, 'missing': [k for k in val_vars], 'errors': {}}
            app.after(0, _populate, info)

        app.executor.submit(_worker)

    _fetch()

def open_spindown_dialog(app):
    """Dialog guidato per la calibrazione spin-down FTMS con controllo banco integrato."""

    if not app.ble.is_ready():
        messagebox.showwarning(
            "Dispositivo non connesso",
            "Nessun trainer BLE connesso.\n"
            "Connetti il dispositivo prima di avviare la calibrazione.",
            parent=app,
        )
        return

    banco_ok = app.banco.is_connected()

    win = app.make_dialog("Calibrazione Spin-Down", size=(460, 540))

    # ── Header ───────────────────────────────────────────────────────────────
    hf = tk.Frame(win, bg='#1e1e2e')
    hf.pack(fill='x')
    tk.Label(hf, text="Calibrazione Spin-Down",
             font=('Helvetica', 11, 'bold'), bg='#1e1e2e', fg='#aaaaff',
             ).pack(side='left', padx=12, pady=8)
    dev = (app.connected_device_name or "")
    if app.connected_device_address:
        dev += f"  [{app.connected_device_address}]"
    tk.Label(hf, text=dev, font=('Helvetica', 8),
             bg='#1e1e2e', fg='#666688').pack(side='left', pady=8)

    # ── Avviso banco non connesso ─────────────────────────────────────────────
    if not banco_ok:
        warn_f = tk.Frame(win, bg='#FFF3CD')
        warn_f.pack(fill='x')
        tk.Label(warn_f,
                 text="⚠  Banco non connesso — velocità controllata manualmente.",
                 font=('Helvetica', 8), bg='#FFF3CD', fg='#7B4D00',
                 pady=4, padx=12).pack(anchor='w')

    # ── Indicatore fasi ───────────────────────────────────────────────────────
    _PHASES_DEF = [
        ("Avvio", "ctrl"),
        ("Spin-Up", "spinup"),
        ("Coast-Down", "coast"),
        ("Risultato", "result"),
    ]
    _C_IDLE = '#AAAAAA'
    _C_ACTIVE = '#E8A000'
    _C_OK = '#00BB44'
    _C_FAIL = '#CC2222'

    step_frame = tk.Frame(win, bg='white')
    step_frame.pack(fill='x', padx=16, pady=(10, 4))
    phase_leds = {}
    for i, (label, key) in enumerate(_PHASES_DEF):
        col = i * 2
        step_frame.grid_columnconfigure(col, weight=1)
        step_frame.grid_columnconfigure(col + 1, weight=0)
        led = tk.Label(step_frame, text='●', font=('Helvetica', 18),
                       bg='white', fg=_C_IDLE)
        led.grid(row=0, column=col, sticky='ew')
        tk.Label(step_frame, text=label, font=('Helvetica', 7),
                 bg='white', fg='#555555').grid(row=1, column=col, sticky='ew')
        if i < len(_PHASES_DEF) - 1:
            tk.Label(step_frame, text='──', font=('Helvetica', 9),
                     bg='white', fg='#cccccc').grid(row=0, column=col + 1)
        phase_leds[key] = led

    # ── Area istruzione ───────────────────────────────────────────────────────
    instr_var = tk.StringVar(value="Premi Avvia per iniziare.")
    instr_lbl = tk.Label(win, textvariable=instr_var,
                         font=('Helvetica', 11, 'bold'),
                         fg='#1a1a2e', bg='#F0F4FF',
                         justify='center', wraplength=420,
                         relief='groove', bd=1, pady=10, padx=10)
    instr_lbl.pack(fill='x', padx=16, pady=(4, 4))

    # ── Velocità: attuale (grande) + range target (low–high) ────────────────
    spd_outer = tk.Frame(win, bg='white', relief='sunken', bd=1)
    spd_outer.pack(fill='x', padx=16, pady=(2, 2))

    # Riga superiore: velocità attuale letta dal rullo BLE
    spd_top = tk.Frame(spd_outer, bg='white')
    spd_top.pack(fill='x', padx=8, pady=(6, 0))

    tk.Label(spd_top, text="Velocità attuale",
             font=('Helvetica', 8), fg='#555555', bg='white',
             anchor='w').pack(side='left')

    speed_var = tk.StringVar(value="—")
    tk.Label(spd_top, textvariable=speed_var,
             font=('Courier', 28, 'bold'), fg='#003300', bg='white',
             anchor='e').pack(side='right', padx=(0, 4))

    tk.Label(spd_top, text="km/h",
             font=('Helvetica', 10), fg='#555555', bg='white',
             ).pack(side='right')

    # Separatore
    tk.Frame(spd_outer, bg='#e0e0e0', height=1).pack(fill='x', padx=8, pady=2)

    # Riga inferiore: range target (min – max)
    spd_bot = tk.Frame(spd_outer, bg='white')
    spd_bot.pack(fill='x', padx=8, pady=(0, 6))

    tk.Label(spd_bot, text="Target",
             font=('Helvetica', 8), fg='#555555', bg='white',
             anchor='w').pack(side='left')

    # "min:" label
    tk.Label(spd_bot, text="min:",
             font=('Helvetica', 8), fg='#885500', bg='white',
             ).pack(side='left', padx=(8, 2))
    target_low_var = tk.StringVar(value="—")
    target_low_lbl = tk.Label(spd_bot, textvariable=target_low_var,
                              font=('Courier', 13, 'bold'), fg='#885500', bg='white')
    target_low_lbl.pack(side='left')
    tk.Label(spd_bot, text="km/h",
             font=('Helvetica', 8), fg='#885500', bg='white').pack(side='left', padx=(2, 10))

    # "max:" label
    tk.Label(spd_bot, text="max:",
             font=('Helvetica', 8), fg='#006600', bg='white',
             ).pack(side='left', padx=(0, 2))
    target_high_var = tk.StringVar(value="—")
    target_high_lbl = tk.Label(spd_bot, textvariable=target_high_var,
                               font=('Courier', 13, 'bold'), fg='#006600', bg='white')
    target_high_lbl.pack(side='left')
    tk.Label(spd_bot, text="km/h",
             font=('Helvetica', 8), fg='#006600', bg='white').pack(side='left', padx=(2, 0))

    # ── Progressbar coast-down + elapsed timer ────────────────────────────────
    pb_frame = tk.Frame(win, bg=win.cget('bg'))     # contenitore non visibile finché non serve
    pb = ttk.Progressbar(pb_frame, mode='indeterminate', length=400)
    pb.pack(fill='x', padx=0)
    _coast_elapsed_var = tk.StringVar(value="")
    _coast_elapsed_lbl = tk.Label(pb_frame, textvariable=_coast_elapsed_var,
                                  font=('Helvetica', 7), fg='#555577',
                                  bg=win.cget('bg'))
    _coast_elapsed_lbl.pack(anchor='e', padx=4)
    _coast_timer_id = [None]
    _coast_t0 = [0.0]

    def _start_coast_timer():
        _coast_t0[0] = time.monotonic()
        _coast_elapsed_var.set("coast-down: 0 s")

        def _tick():
            elapsed = int(time.monotonic() - _coast_t0[0])
            _coast_elapsed_var.set(f"coast-down: {elapsed} s")
            _coast_timer_id[0] = win.after(1000, _tick)

        _tick()

    def _stop_coast_timer():
        if _coast_timer_id[0]:
            win.after_cancel(_coast_timer_id[0])
            _coast_timer_id[0] = None
        _coast_elapsed_var.set("")

    # ── Controllo Banco ───────────────────────────────────────────────────────
    banco_frame = ttk.LabelFrame(win, text="Controllo Banco")
    banco_frame.pack(fill='x', padx=16, pady=(6, 4))

    bf_inner = ttk.Frame(banco_frame)
    bf_inner.pack(fill='x', padx=8, pady=6)
    bf_inner.grid_columnconfigure(1, weight=1)

    ttk.Label(bf_inner, text="Velocità banco [km/h]:").grid(
        row=0, column=0, sticky='e', padx=(0, 6))

    banco_speed_var = tk.DoubleVar(value=0.0)
    banco_spin = ttk.Spinbox(bf_inner, from_=0.0, to=80.0, increment=0.5,
                             format="%.1f", width=8,
                             textvariable=banco_speed_var)
    banco_spin.grid(row=0, column=1, sticky='w')

    def _set_banco_manual():
        try:
            v = float(banco_speed_var.get())
        except (ValueError, tk.TclError):
            return
        app.set_banco_speed(v)
        logging.getLogger().info(
            f"[Calibrazione] Banco impostato manualmente a {v:.1f} km/h")

    def _stop_banco_now():
        banco_speed_var.set(0.0)
        app.set_banco_speed(0)
        logging.getLogger().info("[Calibrazione] Banco fermato manualmente.")

    ttk.Button(bf_inner, text="Set", width=5,
               command=_set_banco_manual).grid(row=0, column=2, padx=(8, 4))
    tk.Button(bf_inner, text="■  Stop Banco",
              font=('Helvetica', 9, 'bold'),
              bg='#CC2222', fg='white',
              activebackground='#AA0000', activeforeground='white',
              relief='raised', bd=2, cursor='hand2', width=11,
              command=_stop_banco_now,
              ).grid(row=0, column=3, padx=(4, 0))

    banco_status_var = tk.StringVar(
        value="Banco connesso — pronto" if banco_ok else "Banco non connesso")
    tk.Label(banco_frame, textvariable=banco_status_var,
             font=('Helvetica', 7, 'italic'), fg='#555555',
             ).pack(anchor='w', padx=10, pady=(0, 4))

    # ── Pulsanti principali ───────────────────────────────────────────────────
    main_bf = ttk.Frame(win)
    main_bf.pack(fill='x', padx=16, pady=(4, 10))
    btn_start = tk.Button(
        main_bf, text="▶  Avvia",
        font=('Helvetica', 10, 'bold'),
        bg='#0D3B6E', fg='white',
        activebackground='#082B52', activeforeground='white',
        relief='raised', bd=2, cursor='hand2', width=10,
    )
    btn_start.pack(side='left')
    btn_close = ttk.Button(main_bf, text="Chiudi",
                           command=lambda: _on_close(), width=8)
    btn_close.pack(side='right')

    # ── Stato interno ─────────────────────────────────────────────────────────
    _calib_running = [False]
    _speed_poll_id = [None]

    def _set_phase_led(key, state):
        colors = {'active': _C_ACTIVE, 'ok': _C_OK, 'fail': _C_FAIL, 'idle': _C_IDLE}
        if key in phase_leds:
            phase_leds[key].config(fg=colors.get(state, _C_IDLE))

    # Polling velocità: parte subito all'apertura, non solo durante spin-up
    def _start_speed_poll():
        def _tick():
            spd = app.latest_data.get('Spd')
            speed_var.set(f"{spd:.1f}" if spd is not None else "—")
            _speed_poll_id[0] = win.after(200, _tick)

        _tick()

    def _stop_speed_poll():
        if _speed_poll_id[0]:
            win.after_cancel(_speed_poll_id[0])
            _speed_poll_id[0] = None

    # ── Callback calibrazione ─────────────────────────────────────────────────

    # Velocità di avvio automatico banco nella fase CTRL_REQ.
    # Usata solo se banco connesso; l'utente può sovrascriverla col Set.
    _RAMP_START_SPEED_KMH = 10.0

    def _apply_phase(phase: CalibrationPhase, info: dict):
        pb.stop()
        pb_frame.pack_forget()
        _stop_coast_timer()

        if phase == CalibrationPhase.CTRL_REQ:
            _set_phase_led('ctrl', 'active')
            if banco_ok:
                banco_speed_var.set(_RAMP_START_SPEED_KMH)
                app.set_banco_speed(_RAMP_START_SPEED_KMH)
                banco_status_var.set(
                    f"✔  Banco avviato a {_RAMP_START_SPEED_KMH:.0f} km/h — aumenta gradualmente")
                instr_var.set(
                    "Banco avviato — aumenta la velocità finché il rullo non risponde.\n"
                    "Il rullo segnalerà quando smettere.")
            else:
                instr_var.set(
                    "Pedala fino alla velocità target.\n"
                    "Il rullo segnalerà quando smettere.")
            instr_lbl.config(fg='#885500', bg='#FFFBE6')

        elif phase == CalibrationPhase.SPIN_UP:
            _set_phase_led('ctrl', 'ok')
            _set_phase_led('spinup', 'active')
            low  = info.get('target_speed_low_kmh')
            high = info.get('target_speed_high_kmh')

            target_low_var.set(f"{low:.1f}"   if low  is not None else "—")
            target_high_var.set(f"{high:.1f}" if high is not None else "—")

            if high is not None:
                if banco_ok:
                    target = round(high, 1)
                    banco_speed_var.set(target)
                    app.set_banco_speed(target)
                    banco_status_var.set(f"✔  Banco impostato a {target:.1f} km/h (automatico)")
                    instr_var.set(
                        f"Raggiungi {high:.1f} km/h\n"
                        f"(banco impostato automaticamente)")
                else:
                    instr_var.set(
                        f"Raggiungi {high:.1f} km/h\n"
                        "Imposta il banco manualmente." if low is not None
                        else f"Raggiungi {high:.1f} km/h")
            else:
                instr_var.set("Pedala fino alla velocità target.\n(target non ricevuto dal rullo)")
            instr_lbl.config(fg='#1a1a2e', bg='#E8F5E9')

        elif phase == CalibrationPhase.COAST_DOWN:
            # Il trainer può arrivare qui saltando la notifica SPIN_UP
            if phase_leds['ctrl'].cget('fg') == _C_ACTIVE:
                _set_phase_led('ctrl', 'ok')
            if phase_leds['spinup'].cget('fg') in (_C_ACTIVE, _C_IDLE):
                _set_phase_led('spinup', 'ok')
            _set_phase_led('coast', 'active')
            target_low_var.set("—")
            target_high_var.set("—")
            if banco_ok:
                app.set_banco_speed(0)
                banco_speed_var.set(0.0)
                banco_status_var.set("✔  Banco fermato (coast-down automatico)")
            instr_var.set("⏸  Smetti di pedalare.\nCoast-down in corso, non toccare il banco…")
            instr_lbl.config(fg='#005580', bg='#E3F2FD')
            pb_frame.pack(fill='x', padx=16, pady=(0, 4))
            pb.start(10)
            _start_coast_timer()

        elif phase == CalibrationPhase.SUCCESS:
            _set_phase_led('coast', 'ok')
            _set_phase_led('result', 'ok')
            instr_var.set("✅  Calibrazione completata con successo!")
            instr_lbl.config(fg='#005500', bg='#E8F5E9')
            btn_start.config(state='normal', text='▶  Ripeti')
            btn_close.config(state='normal')
            _calib_running[0] = False
            logging.getLogger().info("[Calibrazione] Spin-down completato con successo.")

        elif phase == CalibrationPhase.FAILED:
            for key in ('ctrl', 'spinup', 'coast', 'result'):
                if phase_leds[key].cget('fg') == _C_ACTIVE:
                    _set_phase_led(key, 'fail')
            _set_phase_led('result', 'fail')
            if banco_ok:
                app.set_banco_speed(0)
                banco_speed_var.set(0.0)
                banco_status_var.set("■  Banco fermato (sicurezza)")
                logging.getLogger().warning(
                    "[Calibrazione] Banco fermato per sicurezza dopo fallimento.")
            reason_map = {
                'request_control_failed':    'Richiesta controllo fallita',
                'spindown_cmd_failed':        'Comando spin-down rifiutato dal rullo',
                'spinup_timeout':             'Timeout: velocità target non raggiunta in tempo',
                'coastdown_timeout':          'Timeout: coast-down troppo lungo',
            }
            reason_raw = info.get('reason', 'errore sconosciuto')
            reason_txt = reason_map.get(reason_raw, reason_raw)
            instr_var.set(f"❌  Calibrazione fallita\n{reason_txt}")
            instr_lbl.config(fg='#880000', bg='#FFEBEE')
            btn_start.config(state='normal', text='▶  Riprova')
            btn_close.config(state='normal')
            _calib_running[0] = False

    def _on_phase(phase: CalibrationPhase, info: dict):
        """Callback dal loop BLE → rimanda sul main thread."""
        app.after(0, _apply_phase, phase, info)

    def _start_calib():
        if _calib_running[0]:
            return
        _calib_running[0] = True
        btn_start.config(state='disabled')
        btn_close.config(state='disabled')
        for key in phase_leds:
            _set_phase_led(key, 'idle')
        target_low_var.set("—")
        target_high_var.set("—")
        instr_var.set("Avvio in corso…")
        instr_lbl.config(fg='#1a1a2e', bg='#F0F4FF')
        app.executor.submit(_calib_worker)

    def _calib_worker():
        fut = app.ble.run(
            app.ble.manager.start_spindown_calibration(
                status_callback=_on_phase,
                timeout_ctrl=5.0,
                timeout_spinup_request=60.0,
                timeout_spinup=180.0,
                timeout_coastdown=90.0,
            )
        )
        try:
            fut.result(timeout=400)
        except Exception as e:
            logging.getLogger().error(f"Errore calibrazione: {e}")
            app.after(0, _apply_phase,
                       CalibrationPhase.FAILED, {'reason': str(e)})

    def _on_close():
        _stop_speed_poll()
        _stop_coast_timer()
        pb.stop()
        if _calib_running[0] and banco_ok:
            app.set_banco_speed(0)
            logging.getLogger().warning(
                "[Calibrazione] Finestra chiusa durante procedura — banco fermato.")
        win.destroy()

    btn_start.config(command=_start_calib)
    win.protocol("WM_DELETE_WINDOW", _on_close)

    # Polling velocità parte subito, indipendente dalla calibrazione
    _start_speed_poll()

def open_help(app):
    win = app.make_dialog("Guida all'uso", resizable=True, modal=False, size=(580, 540))

    outer = ttk.Frame(win)
    outer.pack(fill='both', expand=True, padx=2, pady=2)

    sb = ttk.Scrollbar(outer, orient='vertical')
    sb.pack(side='right', fill='y')
    canvas = tk.Canvas(outer, yscrollcommand=sb.set,
                       highlightthickness=0, bg='white')
    canvas.pack(side='left', fill='both', expand=True)
    sb.config(command=canvas.yview)

    inner = tk.Frame(canvas, bg='white')
    canvas_win = canvas.create_window((0, 0), window=inner, anchor='nw')

    def _on_resize(e):
        canvas.itemconfig(canvas_win, width=e.width)
    canvas.bind('<Configure>', _on_resize)
    inner.bind('<Configure>',
               lambda e: canvas.configure(
                   scrollregion=canvas.bbox('all')))
    canvas.bind_all('<MouseWheel>',
                    lambda e: canvas.yview_scroll(
                        int(-1 * (e.delta / 120)), 'units'))

    def _on_info_close():
        canvas.unbind_all('<MouseWheel>')
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _on_info_close)

    _BG  = 'white'
    _H1  = ('Helvetica', 11, 'bold')
    _H2  = ('Helvetica', 10, 'bold')
    _TXT = ('Helvetica', 9)

    def h1(text):
        tk.Label(inner, text=text, font=_H1, bg=_BG,
                 fg='#1a1a2e', anchor='w'
                 ).pack(fill='x', padx=16, pady=(14, 2))
        tk.Frame(inner, bg='#aaaacc', height=1).pack(
            fill='x', padx=16, pady=(0, 6))

    def h2(text):
        tk.Label(inner, text=text, font=_H2, bg=_BG,
                 fg='#333366', anchor='w'
                 ).pack(fill='x', padx=20, pady=(8, 1))

    def body(text):
        tk.Label(inner, text=text, font=_TXT, bg=_BG,
                 fg='#333333', anchor='nw', justify='left',
                 wraplength=510
                 ).pack(fill='x', padx=24, pady=(0, 4))

    # ── Contenuto ─────────────────────────────────────────────────────
    h1("● Barra di Stato — LED")

    h2("APP  (primo LED a sinistra)")
    body("Indicatore per capire se il programma si è congelato. Fino a quanto lampeggia e il contatore incrementa tutto ok")

    h2("BLE / Lorenz / Banco / COM")
    body("Verde = dispositivo connesso e raggiungibile.\n"
         "Rosso = non connesso o connessione persa. ")

    h2("FTMS — frequenza dati")
    body("Mostra la frequenza (Hz) con cui arrivano i pacchetti dati dal "
         "trainer BLE. Attivo solo quando le notifiche FTMS sono abilitate. "
         "Si spegne automaticamente se i dati si interrompono per più di 2 secondi.")

    h2("Auto")
    body("Verde = sequenza automatica da CSV in esecuzione.\n"
         "Spento = nessuna sequenza attiva.")

    h2("REC")
    body("Rosso lampeggiante = la sessione è in registrazione.\n"
         "Spento = nessuna registazione in corso")

    h1("● Barra Connessioni")

    h2("REC")
    body("Avvia o ferma la registrazione dei dati. Vengono registrati tutti i dati disponibili in quel momento. "
         "La cartella di Output serve ad aprire dove sono i risultati. "
         "In caso di superamento dei 50 Mega di dimensioni del file verrà creato un nuovo file")

    h2("BLE")
    body("Cerca i dispositivi Bluetooth nelle vicinanze, seleziona il trainer "
         "dalla lista e premi Connetti. La barra di avanzamento indica che "
         "un'operazione è in corso. Una volta connesso, le notifiche FTMS "
         "vengono abilitate automaticamente alla connessione.")

    h2("Lorenz")
    body("Connette il sensore di coppia/potenza esterno sulla porta USB dedicata. "
         "'Leggi Offset' acquisisce il valore di offset attuale (eseguire a riposo). "
         "'Media' imposta quanti campioni usare per la media mobile. "
         "'Inverti Velocità' inverte il segno del canale B.")

    h2("Banco")
    body("Connette il motore tramite Modbus TCP. Inserire l'IP del banco e premere "
         "Connetti. La velocità viene impostata automaticamente durante le sequenze "
         "automatiche se specificata nel CSV.")

    h2("Sensore COM")
    body("Connette un sensore seriale aggiuntivo (fino a 4 valori numerici separati "
         "da ';'). Il pannello è collassabile con il pulsante '+COM'.")

    h2("Gamma Sensor")
    body("Connette il sensore Gamma via porta seriale. Legge continuamente DGS, TPR e Trigger "
         "dal sensore con parsing hardware del protocollo frame (header FF FF, CRC, footer 55 AA). "
         "I valori sono visualizzati nel pannello laterale e vengono registrati automaticamente "
         "nelle colonne dgs_gamma, tpr_gamma, trigger_gamma del file Excel se la registrazione è attiva.")

    h1("● Comandi e Sequenza Automatica")

    h2("Comandi manuali")
    body("Inviano direttamente al trainer un livello di resistenza (0–200), "
         "una potenza target (W) o un profilo di simulazione (pendenza %). "
         "Usare per test rapidi o verifica risposta.")

    h2("Sequenza da CSV / Excel")
    body("Carica un file CSV o Excel. Colonne (riga 1 = intestazione, ignorata): "
         "comando | tempo_s | valore_rullo | banco_kmh | etichetta. "
         "Comandi disponibili: livelli, potenza, simulazione, spindown, save. "
         "'tempo_s' è l'attesa dopo il comando; 'valore_rullo' è livello/potenza/pendenza. "
         "vengono inviati automaticamente freno=0 e velocità banco=0 per sicurezza. "
         "Le notifiche FTMS restano attive e vanno disabilitate manualmente se necessario.")

    h2("Emergency Stop")
    body("Ferma immediatamente la sequenza automatica e imposta la velocità "
         "del banco a 0. Usare in caso di necessità.")

    h1("● Dati Live e Pannello Δ")

    body("Il pannello mostra in tempo reale i valori ricevuti dal trainer BLE "
         "e dal sensore Lorenz affiancati. Il Δ centrale indica la differenza "
         "tra le due sorgenti: verde se rientra nella soglia, arancione se "
         "moderato, rosso se elevato. Le soglie e la finestra di smoothing "
         "sono configurabili da Impostazioni → Parametri delta.")

    h1("● Salvataggio Dati")

    body("Per avviare la registrazione premere ⏺ REC: verrà chiesto un nome "
         "opzionale per la sessione. Senza nome il file sarà YYYYMMDD_HHMMSS_bike_data.xlsx; "
         "con nome personalizzato sarà YYYYMMDD_HHMMSS_nome.xlsx (senza suffisso _bike_data). "
         "Premere ⏹ STOP per terminare la sessione con flush finale garantito. "
         "È possibile avviare più sessioni consecutive senza riavviare il programma.")
    body("Il salvataggio avviene automaticamente ogni 60 secondi. Se il file supera "
         "50 MB viene creato un nuovo file (_part02, _part03…) con la stessa intestazione. "
         "Per forzare il salvataggio immediato usare File → Forza salvataggio dati. "
         "La frequenza di registrazione (default 2 Hz) è configurabile da "
         "Impostazioni → Parametri delta.")

    # ── Pulsante chiudi ────────────────────────────────────────────────
    ttk.Button(win, text="Chiudi", command=_on_info_close
               ).pack(pady=10)
