"""Ventana principal de FichajeLocal: KIOSCO de fichaje (reloj + botones de
empleado + teclado PIN tactil) y panel de ADMINISTRACION protegido por PIN."""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from . import APP_NAME, APP_VERSION, theme
from . import report
from .config import AppConfig, DB_PATH, load_config, save_config
from .store import Store, StoreError

logger = logging.getLogger(__name__)

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("900x680")
        self.minsize(760, 600)
        theme.apply(self)
        try:
            ico = Path(__file__).resolve().parent.parent / "build" / "icon.ico"
            if ico.is_file():
                self.iconbitmap(str(ico))
        except tk.TclError:
            pass

        self.cfg: AppConfig = load_config()
        self.store = Store(str(DB_PATH))
        self._closing = False
        self._flash_id: str | None = None
        self._clock_id: str | None = None
        self._pin_fails: dict[str, tuple[int, float]] = {}   # target -> (fallos, hasta_ts)

        self._build_kiosco()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(250, self._tick_clock)
        self.after(400, self._first_run)
        # salir de pantalla completa exige PIN de admin (kiosco): sin esto el
        # dueno quedaba 'atrapado' hasta Alt+F4
        self.bind("<Escape>", self._salir_fullscreen)
        if self.cfg.kiosco_fullscreen:
            self.attributes("-fullscreen", True)

    def _pin_bloqueado(self, target: str) -> float:
        """Segundos que quedan de bloqueo por fuerza bruta (0 si libre)."""
        fallos, hasta = self._pin_fails.get(target, (0, 0.0))
        return max(0.0, hasta - time.time())

    def _pin_fallo(self, target: str) -> None:
        fallos, _ = self._pin_fails.get(target, (0, 0.0))
        fallos += 1
        # a partir de 5 fallos, bloqueo creciente (30s, 60s, 120s…)
        espera = 0.0 if fallos < 5 else min(300.0, 30.0 * (2 ** (fallos - 5)))
        self._pin_fails[target] = (fallos, time.time() + espera)
        if espera:
            logger.warning("PIN '%s': %d fallos, bloqueado %ds", target, fallos, int(espera))

    def _pin_ok(self, target: str) -> None:
        self._pin_fails.pop(target, None)

    def _salir_fullscreen(self, _e=None) -> None:
        if not self.attributes("-fullscreen"):
            return
        if not self.store.admin_configurado():
            self.attributes("-fullscreen", False)
            return
        PinPad(self, "PIN de administracion para salir de pantalla completa",
               lambda pin: self._fullscreen_off(pin), digits_hidden=True)

    def _fullscreen_off(self, pin: str) -> bool:
        if not self.store.verify_admin_pin(pin):
            return False
        self.attributes("-fullscreen", False)
        self.cfg.kiosco_fullscreen = False
        save_config(self.cfg)
        return True

    # ------------------------------------------------------------- kiosco
    def _build_kiosco(self) -> None:
        # NO destruir Toplevels (p.ej. la ventana de Administracion abierta que
        # acaba de pulsar 'Guardar ajustes'): solo el contenido del kiosco.
        for w in self.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        theme.header(self, APP_NAME, self.cfg.negocio or "Registro horario · 100% en este equipo")
        self.status = theme.status_bar(self, "Toca tu nombre y marca tu PIN para fichar.")

        body = ttk.Frame(self, padding=(24, 10))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        self.lbl_clock = ttk.Label(body, text="", font=(theme.FONT, 44, "bold"),
                                   foreground=theme.NAVY)
        self.lbl_clock.grid(row=0, column=0, pady=(6, 0))
        self.lbl_date = ttk.Label(body, text="", style="Muted.TLabel", font=(theme.FONT, 13))
        self.lbl_date.grid(row=1, column=0, pady=(0, 10))

        # banner de feedback del ultimo fichaje
        self.lbl_flash = tk.Label(body, text="", font=(theme.FONT, 15, "bold"),
                                  bg=theme.BG, fg=theme.SUCCESS)
        self.lbl_flash.grid(row=2, column=0, pady=(0, 8))

        # botones de empleados (rejilla tactil)
        self.grid_emp = ttk.Frame(body)
        self.grid_emp.grid(row=3, column=0, sticky="nsew")
        body.rowconfigure(3, weight=1)
        self._refresh_empleados()

        foot = ttk.Frame(self, padding=(14, 8))
        foot.pack(fill="x", side="bottom")
        ttk.Button(foot, text="⚙ Administracion", command=self._open_admin).pack(side="right")

    def _refresh_empleados(self) -> None:
        for w in self.grid_emp.winfo_children():
            w.destroy()
        emps = self.store.empleados(solo_activos=True)
        if not emps:
            ttk.Label(self.grid_emp, text="Aun no hay empleados.\n"
                      "Entra en ⚙ Administracion para darlos de alta.",
                      style="Muted.TLabel", font=(theme.FONT, 13),
                      justify="center").pack(expand=True, pady=40)
            return
        cols = 3 if len(emps) > 4 else 2
        for c in range(cols):
            self.grid_emp.columnconfigure(c, weight=1)
        for i, (eid, nombre, _a) in enumerate(emps):
            dentro = self.store.ultimo_tipo(eid) == "entrada"
            txt = f"{nombre}\n{'● dentro' if dentro else '○ fuera'}"
            b = tk.Button(self.grid_emp, text=txt, font=(theme.FONT, 14, "bold"),
                          bg=(theme.NAVY if dentro else theme.SURFACE),
                          fg=(theme.WHITE if dentro else theme.TEXT),
                          activebackground=theme.PRIMARY, activeforeground=theme.WHITE,
                          relief="flat", cursor="hand2", wraplength=240,
                          command=lambda e=eid, n=nombre: self._pedir_pin(e, n))
            b.grid(row=i // cols, column=i % cols, sticky="nsew", padx=8, pady=8,
                   ipadx=10, ipady=22)
            self.grid_emp.rowconfigure(i // cols, weight=1)

    def _tick_clock(self) -> None:
        if self._closing:
            return
        now = datetime.now()
        try:
            self.lbl_clock.config(text=now.strftime("%H:%M:%S"))
            dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
            self.lbl_date.config(
                text=f"{dias[now.weekday()]}, {now.day} de {MESES[now.month].lower()} de {now.year}")
        except tk.TclError:
            return
        self._clock_id = self.after(500, self._tick_clock)   # id unico: no se duplica el timer

    def _pedir_pin(self, eid: int, nombre: str) -> None:
        PinPad(self, f"Hola, {nombre}", lambda pin: self._fichar(eid, nombre, pin))

    def _fichar(self, eid: int, nombre: str, pin: str):
        target = f"emp:{eid}"
        espera = self._pin_bloqueado(target)
        if espera:
            return f"Demasiados intentos. Espera {int(espera)+1} s."
        if not self.store.verify_pin(eid, pin):
            self._pin_fallo(target)
            return False       # PinPad muestra 'PIN incorrecto' y sigue abierto
        self._pin_ok(target)
        tipo, ts = self.store.fichar(eid)
        hora = ts[11:16]
        if tipo == "entrada":
            self._flash(f"✔ ENTRADA registrada a las {hora} — ¡buen turno, {nombre}!")
        else:
            self._flash(f"✔ SALIDA registrada a las {hora} — ¡hasta pronto, {nombre}!")
        self._refresh_empleados()
        return True

    def _flash(self, texto: str, error: bool = False) -> None:
        try:
            self.lbl_flash.config(text=texto, fg=(theme.DANGER if error else theme.SUCCESS))
        except tk.TclError:
            return
        if self._flash_id:
            try:
                self.after_cancel(self._flash_id)
            except (tk.TclError, ValueError):
                pass
        self._flash_id = self.after(4000, lambda: self._flash_clear())

    def _flash_clear(self) -> None:
        self._flash_id = None
        try:
            self.lbl_flash.config(text="")
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- admin
    def _open_admin(self) -> None:
        if not self.store.admin_configurado():
            messagebox.showinfo(APP_NAME, "Primero configura el PIN de administracion.")
            self._setup_admin()
            return
        PinPad(self, "PIN de administracion",
               lambda pin: self._admin_ok(pin), digits_hidden=True)

    def _admin_ok(self, pin: str):
        espera = self._pin_bloqueado("admin")
        if espera:
            return f"Demasiados intentos. Espera {int(espera)+1} s."
        if not self.store.verify_admin_pin(pin):
            self._pin_fallo("admin")
            return False
        self._pin_ok("admin")
        AdminWindow(self)
        return True

    def _setup_admin(self) -> None:
        # doble entrada: un PIN mal tecleado (sin confirmar) dejaria la admin
        # bloqueada para siempre, ya que solo se teclea en el pad numerico.
        pin = simpledialog.askstring(APP_NAME, "Elige un PIN de administracion "
                                     "(4 a 8 digitos):", show="•", parent=self)
        if not pin:
            return
        pin2 = simpledialog.askstring(APP_NAME, "Repite el PIN para confirmarlo:",
                                      show="•", parent=self)
        if pin2 is None:
            return
        if pin.strip() != pin2.strip():
            messagebox.showerror(APP_NAME, "Los dos PIN no coinciden. Vuelve a intentarlo.")
            return
        try:
            self.store.set_admin_pin(pin.strip())
        except StoreError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        messagebox.showinfo(APP_NAME, "PIN de administracion guardado. "
                            "Ya puedes entrar en ⚙ Administracion.")

    # -------------------------------------------------------------- varios
    def _first_run(self) -> None:
        if self._closing or self.cfg.seen_welcome:
            return
        self.cfg.seen_welcome = True
        save_config(self.cfg)
        messagebox.showinfo(
            APP_NAME, "Bienvenido a FichajeLocal.\n\n"
            "1. Entra en ⚙ Administracion (crearas tu PIN de admin).\n"
            "2. Da de alta a tus empleados, cada uno con su PIN.\n"
            "3. Deja esta pantalla abierta en el PC del mostrador: cada empleado "
            "toca su nombre, marca su PIN, y la app registra entrada o salida sola.\n\n"
            "Cada fichaje se encadena criptograficamente al anterior: editar o borrar un "
            "asiento rompe la cadena y se detecta. Para que el registro sea defendible ante "
            "una inspeccion, GUARDA cada informe/copia mensual en tu gestoria (cada uno lleva "
            "su huella): asi tambien se detecta un recorte. El informe mensual (PDF/CSV) sale "
            "listo para la gestoria. Nada se sube a internet.")
        if not self.store.admin_configurado():
            self._setup_admin()

    def _on_close(self) -> None:
        # backup automatico al cerrar si hay carpeta configurada. Con feedback y
        # aviso: una ruta de red caida podria tardar, y si falla el usuario debe
        # enterarse (antes solo iba al log).
        if self.cfg.backup_dir:
            try:
                self.status.config(text="Guardando copia de seguridad…")
                self.update_idletasks()
            except tk.TclError:
                pass
            try:
                self.store.backup(self.cfg.backup_dir)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backup al cerrar fallo: %s", exc)
                if not messagebox.askyesno(
                        APP_NAME, f"La copia de seguridad automatica ha fallado:\n{exc}\n\n"
                        "¿Cerrar igualmente? (los datos siguen en este equipo)"):
                    try:
                        self.status.config(text="Cierre cancelado.")
                    except tk.TclError:
                        pass
                    return
        self._closing = True
        for tid in (self._clock_id, self._flash_id):
            if tid:
                try:
                    self.after_cancel(tid)
                except (tk.TclError, ValueError):
                    pass
        self.store.close()
        self.destroy()


class PinPad(tk.Toplevel):
    """Teclado numerico tactil. on_ok(pin) devuelve True para cerrar (exito) o
    False para limpiar y reintentar."""

    def __init__(self, parent, titulo: str, on_ok, digits_hidden: bool = True):
        super().__init__(parent)
        self.on_ok = on_ok
        theme.center_window(self)
        self.title(titulo)
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.resizable(False, False)
        self._pin = ""
        self._hidden = digits_hidden

        frm = ttk.Frame(self, padding=18)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=titulo, style="H.TLabel",
                  font=(theme.FONT, 14, "bold")).pack(pady=(0, 6))
        self.lbl = tk.Label(frm, text="", font=("Consolas", 24, "bold"),
                            bg=theme.SURFACE, fg=theme.NAVY, width=12, pady=8)
        self.lbl.pack(pady=(0, 4))
        self.lbl_err = tk.Label(frm, text="", font=(theme.FONT, 10, "bold"),
                                bg=theme.BG, fg=theme.DANGER)
        self.lbl_err.pack(pady=(0, 6))
        grid = ttk.Frame(frm)
        grid.pack()
        botones = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
        for i, t in enumerate(botones):
            cmd = (self._back if t == "⌫" else self._ok if t == "OK"
                   else lambda d=t: self._digit(d))
            b = tk.Button(grid, text=t, font=(theme.FONT, 16, "bold"), width=4, height=1,
                          relief="flat", cursor="hand2",
                          bg=(theme.PRIMARY if t == "OK" else theme.SURFACE),
                          fg=(theme.WHITE if t == "OK" else theme.TEXT),
                          activebackground=theme.PRIMARY_DARK, command=cmd)
            b.grid(row=i // 3, column=i % 3, padx=5, pady=5, ipady=8)
        self.bind("<Key>", self._tecla)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()

    def _tecla(self, e) -> None:
        if e.char.isdigit():
            self._digit(e.char)
        elif e.keysym == "BackSpace":
            self._back()

    def _digit(self, d: str) -> None:
        try:
            self.lbl_err.config(text="")
        except tk.TclError:
            pass
        if len(self._pin) < 8:
            self._pin += d
            self._paint()

    def _back(self) -> None:
        self._pin = self._pin[:-1]
        self._paint()

    def _paint(self) -> None:
        self.lbl.config(text=("•" * len(self._pin)) if self._hidden else self._pin)

    def _ok(self) -> None:
        if not self._pin:
            return
        pin, self._pin = self._pin, ""
        self._paint()
        res = self.on_ok(pin)      # True=cerrar, False=PIN incorrecto, str=ese aviso
        if res is True:
            self.destroy()
        else:
            try:
                self.lbl_err.config(text=res if isinstance(res, str)
                                    else "PIN incorrecto, vuelve a intentarlo.")
            except tk.TclError:
                pass


class AdminWindow(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.store = app.store
        theme.center_window(self)
        self.title(f"{APP_NAME} — Administracion")
        self.configure(bg=theme.BG)
        self.geometry("860x620")
        self.transient(app)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.tab_emp = ttk.Frame(nb, padding=12)
        self.tab_mes = ttk.Frame(nb, padding=12)
        self.tab_cfg = ttk.Frame(nb, padding=12)
        nb.add(self.tab_emp, text="  Empleados  ")
        nb.add(self.tab_mes, text="  Fichajes e informes  ")
        nb.add(self.tab_cfg, text="  Ajustes  ")
        self._build_empleados()
        self._build_mes()
        self._build_ajustes()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _close(self) -> None:
        self.app._refresh_empleados()
        self.destroy()

    # ------------------------------------------------------------ empleados
    def _build_empleados(self) -> None:
        f = self.tab_emp
        self.lst_emp = tk.Listbox(f, font=(theme.FONT, 11), height=14, bg=theme.WHITE)
        self.lst_emp.pack(fill="both", expand=True)
        self._refresh_lst()
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="+ Dar de alta", style="Primary.TButton",
                   command=self._alta).pack(side="left")
        ttk.Button(row, text="Cambiar PIN", command=self._cambiar_pin).pack(side="left", padx=6)
        ttk.Button(row, text="Activar / desactivar", command=self._toggle_activo).pack(side="left")

    def _refresh_lst(self) -> None:
        self.lst_emp.delete(0, "end")
        self._emp_ids = []
        for eid, nombre, activo in self.store.empleados(solo_activos=False):
            self._emp_ids.append(eid)
            self.lst_emp.insert("end", f"{nombre}{'' if activo else '   (desactivado)'}")

    def _sel_emp(self) -> int | None:
        s = self.lst_emp.curselection()
        return self._emp_ids[s[0]] if s else None

    def _alta(self) -> None:
        nombre = simpledialog.askstring(APP_NAME, "Nombre del empleado:", parent=self)
        if not nombre:
            return
        pin = simpledialog.askstring(APP_NAME, f"PIN para {nombre} (minimo 4 digitos):",
                                     show="•", parent=self)
        if not pin:
            return
        try:
            self.store.add_empleado(nombre, pin.strip())
        except StoreError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return
        self._refresh_lst()

    def _cambiar_pin(self) -> None:
        eid = self._sel_emp()
        if eid is None:
            return
        pin = simpledialog.askstring(APP_NAME, "Nuevo PIN (minimo 4 digitos):",
                                     show="•", parent=self)
        if not pin:
            return
        try:
            self.store.set_pin(eid, pin.strip())
        except StoreError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def _toggle_activo(self) -> None:
        eid = self._sel_emp()
        if eid is None:
            return
        estado = dict((i, a) for i, _n, a in self.store.empleados(solo_activos=False))
        self.store.set_activo(eid, not estado.get(eid, True))
        self._refresh_lst()

    # ------------------------------------------------------ fichajes e informes
    def _build_mes(self) -> None:
        f = self.tab_mes
        top = ttk.Frame(f)
        top.pack(fill="x")
        hoy = date.today()
        ttk.Label(top, text="Mes:").pack(side="left")
        self.var_mes = tk.IntVar(value=hoy.month)
        spm = ttk.Spinbox(top, from_=1, to=12, textvariable=self.var_mes, width=4,
                          command=self._refresh_mes)
        spm.pack(side="left", padx=(4, 10))
        ttk.Label(top, text="Año:").pack(side="left")
        self.var_anio = tk.IntVar(value=hoy.year)
        spa = ttk.Spinbox(top, from_=2020, to=2100, textvariable=self.var_anio, width=6,
                          command=self._refresh_mes)
        spa.pack(side="left", padx=(4, 16))
        for sp in (spm, spa):        # aplicar tambien valores TECLEADOS, no solo flechas
            sp.bind("<Return>", lambda _e: self._refresh_mes())
            sp.bind("<FocusOut>", lambda _e: self._refresh_mes())
        ttk.Button(top, text="Añadir correccion…", command=self._correccion).pack(side="left")
        ttk.Button(top, text="Verificar integridad", command=self._verificar).pack(side="left", padx=6)

        cols = ("fecha", "empleado", "detalle", "horas")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=13)
        for c, t, wpx in (("fecha", "Fecha", 90), ("empleado", "Empleado", 150),
                          ("detalle", "Movimientos", 380), ("horas", "Horas", 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wpx, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(10, 0))

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="📄 Informe PDF del mes", style="Primary.TButton",
                   command=self._pdf).pack(side="right")
        ttk.Button(bar, text="CSV para la gestoria", command=self._csv).pack(side="right", padx=6)
        self._refresh_mes()

    def _mes_anio(self) -> tuple[int, int]:
        try:
            return max(2000, int(self.var_anio.get())), max(1, min(12, int(self.var_mes.get())))
        except tk.TclError:
            hoy = date.today()
            return hoy.year, hoy.month

    def _refresh_mes(self) -> None:
        from .store import resumen_por_dia
        y, m = self._mes_anio()
        self.tree.delete(*self.tree.get_children())
        for eid, nombre, _a in self.store.empleados(solo_activos=False):
            fich = self.store.fichajes_mes(y, m, eid)
            for d in resumen_por_dia(fich):
                detalle = " · ".join(d.movimientos)
                if d.incidencias:
                    detalle += "   ⚠ " + "; ".join(d.incidencias)
                self.tree.insert("", "end", values=(d.fecha, nombre, detalle, f"{d.horas:.2f}"))

    def _correccion(self) -> None:
        eid = self._pedir_empleado()
        if eid is None:
            return
        ts = simpledialog.askstring(
            APP_NAME, "Fecha y hora REAL del movimiento olvidado\n(formato: 2026-07-12 14:30):",
            parent=self)
        if not ts:
            return
        try:
            datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M")
        except ValueError:
            messagebox.showerror(APP_NAME, "Formato invalido. Usa: AAAA-MM-DD HH:MM", parent=self)
            return
        tipo = "entrada" if messagebox.askyesno(
            APP_NAME, "¿El movimiento olvidado fue una ENTRADA?\n(Si=entrada, No=salida)",
            parent=self) else "salida"
        motivo = simpledialog.askstring(APP_NAME, "Motivo de la correccion:", parent=self) or ""
        try:
            self.store.add_correccion(eid, ts.strip(), tipo, motivo)
        except StoreError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return
        self._refresh_mes()
        messagebox.showinfo(APP_NAME, "Correccion añadida como asiento encadenado "
                            "(el registro original nunca se toca).", parent=self)

    def _pedir_empleado(self) -> int | None:
        emps = self.store.empleados(solo_activos=False)
        if not emps:
            return None
        # selector con lista (evita teclear el nombre con acentos exactos)
        win = tk.Toplevel(self)
        theme.center_window(win)
        win.title("Elegir empleado")
        win.configure(bg=theme.BG)
        win.transient(self)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Elige el empleado:", style="H.TLabel").pack(anchor="w", pady=(0, 6))
        lb = tk.Listbox(frm, width=36, height=min(12, len(emps)), font=(theme.FONT, 11))
        lb.pack(fill="both", expand=True)
        for _i, n, a in emps:
            lb.insert("end", n + ("" if a else "   (desactivado)"))
        elegido = {"eid": None}

        def ok():
            s = lb.curselection()
            if s:
                elegido["eid"] = emps[s[0]][0]
            win.destroy()
        lb.bind("<Double-Button-1>", lambda _e: ok())
        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Aceptar", style="Primary.TButton", command=ok).pack(side="right")
        ttk.Button(row, text="Cancelar", command=win.destroy).pack(side="right", padx=(0, 6))
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        return elegido["eid"]

    def _verificar(self) -> None:
        ok, roto, total = self.store.verificar_cadena()
        if ok:
            messagebox.showinfo(APP_NAME, f"✔ Cadena integra: {total} asientos verificados.\n"
                                f"Huella: {self.store.huella()[:32]}…", parent=self)
        else:
            messagebox.showerror(APP_NAME, f"✘ CADENA ROTA en el asiento {roto} "
                                 f"(de {total}). El registro fue alterado fuera de la app.",
                                 parent=self)

    def _pdf(self) -> None:
        y, m = self._mes_anio()
        por_emp: dict[str, list] = {}
        for eid, nombre, _a in self.store.empleados(solo_activos=False):
            fich = self.store.fichajes_mes(y, m, eid)
            if fich:
                por_emp[nombre] = fich
        if not por_emp:
            messagebox.showinfo(APP_NAME, "No hay fichajes en ese mes.", parent=self)
            return
        out = Path(self.app.cfg.output_dir) / f"Registro_{y:04d}-{m:02d}.pdf"
        try:
            report.exportar_pdf(str(out), negocio=self.app.cfg.negocio, year=y, month=m,
                                por_empleado=por_emp,
                                integridad=self.store.verificar_cadena(),
                                huella=self.store.huella())
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf fallo")
            messagebox.showerror(APP_NAME, f"No se pudo generar el PDF:\n{exc}", parent=self)
            return
        if messagebox.askyesno(APP_NAME, f"Informe guardado en:\n{out}\n\n¿Abrirlo?", parent=self):
            try:
                os.startfile(str(out))
            except OSError:
                pass

    def _csv(self) -> None:
        y, m = self._mes_anio()
        fich = self.store.fichajes_mes(y, m)
        if not fich:
            messagebox.showinfo(APP_NAME, "No hay fichajes en ese mes.", parent=self)
            return
        out = Path(self.app.cfg.output_dir) / f"Registro_{y:04d}-{m:02d}.csv"
        try:
            report.exportar_csv(str(out), fich)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"No se pudo guardar el CSV (¿esta abierto en "
                                 f"Excel?):\n{exc}", parent=self)
            return
        messagebox.showinfo(APP_NAME, f"CSV guardado en:\n{out}", parent=self)

    # -------------------------------------------------------------- ajustes
    def _build_ajustes(self) -> None:
        f = self.tab_cfg
        ttk.Label(f, text="Nombre del negocio (encabeza los informes):").pack(anchor="w")
        self.var_neg = tk.StringVar(value=self.app.cfg.negocio)
        ttk.Entry(f, textvariable=self.var_neg, width=40).pack(anchor="w", pady=(2, 10))

        ttk.Label(f, text=f"Carpeta de informes: {self.app.cfg.output_dir}",
                  style="Muted.TLabel", wraplength=680).pack(anchor="w")
        ttk.Button(f, text="Cambiar carpeta de informes…",
                   command=self._out_dir).pack(anchor="w", pady=(2, 10))

        ttk.Label(f, text="Copia de seguridad automatica al cerrar (USB o carpeta de red):",
                  ).pack(anchor="w")
        self.lbl_bk = ttk.Label(f, text=self.app.cfg.backup_dir or "(desactivada)",
                                style="Muted.TLabel", wraplength=680)
        self.lbl_bk.pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=(2, 10))
        ttk.Button(row, text="Elegir carpeta…", command=self._bk_dir).pack(side="left")
        ttk.Button(row, text="Hacer copia AHORA", command=self._bk_now).pack(side="left", padx=6)

        self.var_full = tk.BooleanVar(value=self.app.cfg.kiosco_fullscreen)
        ttk.Checkbutton(f, text="Kiosco a pantalla completa al arrancar",
                        variable=self.var_full).pack(anchor="w", pady=(4, 10))
        ttk.Button(f, text="Cambiar PIN de administracion…",
                   command=self._admin_pin).pack(anchor="w", pady=(0, 12))
        ttk.Button(f, text="Guardar ajustes", style="Primary.TButton",
                   command=self._save).pack(anchor="w")

    def _out_dir(self) -> None:
        d = filedialog.askdirectory(title="Carpeta de informes",
                                    initialdir=self.app.cfg.output_dir, parent=self)
        if d:
            self.app.cfg.output_dir = d
            save_config(self.app.cfg)

    def _bk_dir(self) -> None:
        d = filedialog.askdirectory(title="Carpeta de copias de seguridad", parent=self)
        if d:
            self.app.cfg.backup_dir = d
            save_config(self.app.cfg)
            self.lbl_bk.config(text=d)

    def _bk_now(self) -> None:
        if not self.app.cfg.backup_dir:
            messagebox.showinfo(APP_NAME, "Elige primero la carpeta de copias.", parent=self)
            return
        try:
            dest = self.store.backup(self.app.cfg.backup_dir)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"La copia fallo:\n{exc}", parent=self)
            return
        messagebox.showinfo(APP_NAME, f"Copia creada:\n{dest}", parent=self)

    def _admin_pin(self) -> None:
        pin = simpledialog.askstring(APP_NAME, "Nuevo PIN de administracion (4 a 8 digitos):",
                                     show="•", parent=self)
        if not pin:
            return
        pin2 = simpledialog.askstring(APP_NAME, "Repite el PIN para confirmarlo:",
                                      show="•", parent=self)
        if pin2 is None:
            return
        if pin.strip() != pin2.strip():
            messagebox.showerror(APP_NAME, "Los dos PIN no coinciden.", parent=self)
            return
        try:
            self.store.set_admin_pin(pin.strip())
        except StoreError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)

    def _save(self) -> None:
        self.app.cfg.negocio = self.var_neg.get().strip()
        self.app.cfg.kiosco_fullscreen = bool(self.var_full.get())
        save_config(self.app.cfg)
        messagebox.showinfo(APP_NAME, "Ajustes guardados.", parent=self)
        self.app._build_kiosco()


def main() -> None:
    from .config import setup_logging
    setup_logging()
    App().mainloop()
