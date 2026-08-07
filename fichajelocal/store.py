"""Almacen de FichajeLocal: SQLite con CADENA DE HASHES.

Integridad demostrable: cada asiento guarda el hash SHA-256 de una codificacion
CANONICA (JSON, sin ambiguedades de separador) de sus campos FIRMADOS —incluido
el empleado— encadenada con el hash del asiento anterior. Editar, borrar o
reordenar un asiento intermedio rompe la cadena y verificar_cadena() lo delata.

Alcance honesto de la cadena (ver README): garantiza que nadie ha alterado un
asiento aislado ni el orden relativo, y —comparando el numero de asientos y la
huella de copias anteriores— permite detectar recortes al final. NO puede, por
si sola, impedir que quien tiene acceso al fichero reescriba TODO el historial
recalculando la cadena: para eso hace falta anclar la huella fuera del equipo
(entregar el PDF/huella mensual a la gestoria, que actua de tercero de confianza).

Las CORRECCIONES nunca editan: se anaden como asientos nuevos de tipo
'correccion' con la fecha/tipo REAL del movimiento olvidado en columnas propias
(tambien firmadas), para que el informe impute las horas al dia correcto.

Los PIN jamas se guardan en claro: PBKDF2-HMAC-SHA256 con salt por empleado. El
PIN es control de ACCESO de la UI, no de integridad.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

GENESIS = "0" * 64
CHAIN_VERSION = 2          # v2: payload canonico JSON con empleado_id + campos de correccion
PBKDF2_ITERS = 100_000
TIPOS = ("entrada", "salida", "correccion")


class StoreError(Exception):
    pass


@dataclass
class Fichaje:
    id: int
    empleado_id: int
    nombre: str
    tipo: str            # entrada | salida | correccion
    ts: str              # ISO "YYYY-MM-DD HH:MM:SS" (momento del asiento)
    nota: str
    hash: str
    ts_real: str = ""    # para correcciones: fecha/hora REAL del movimiento
    tipo_real: str = ""  # para correcciones: entrada | salida real


def hash_asiento(prev_hash: str, empleado_id: int, nombre: str, tipo: str, ts: str,
                 nota: str, ts_real: str = "", tipo_real: str = "") -> str:
    """Hash canonico del asiento (SHA-256 sobre JSON de una lista: sin
    ambiguedad de separadores, e incluye el empleado). PURO y testeable."""
    payload = json.dumps(
        [prev_hash, int(empleado_id), nombre, tipo, ts, nota, ts_real, tipo_real],
        ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pin_hash(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PBKDF2_ITERS)


def _validar_pin(pin: str) -> str:
    pin = (pin or "").strip()
    if not pin.isdigit() or not (4 <= len(pin) <= 8):
        raise StoreError("El PIN debe ser NUMERICO, de 4 a 8 digitos "
                         "(para poder teclearlo en el teclado tactil).")
    return pin


class Store:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.db_path, check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        try:
            self._con.close()
        except sqlite3.Error:
            pass

    def _init_schema(self) -> None:
        c = self._con
        c.executescript("""
        CREATE TABLE IF NOT EXISTS empleados(
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL UNIQUE,
            pin_salt BLOB NOT NULL,
            pin_hash BLOB NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            creado TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fichajes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empleado_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL,
            ts TEXT NOT NULL,
            nota TEXT NOT NULL DEFAULT '',
            ts_real TEXT NOT NULL DEFAULT '',
            tipo_real TEXT NOT NULL DEFAULT '',
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta(
            clave TEXT PRIMARY KEY,
            valor BLOB);
        """)
        c.commit()

    # ------------------------------------------------------------ PIN admin
    def admin_configurado(self) -> bool:
        r = self._con.execute("SELECT valor FROM meta WHERE clave='admin_hash'").fetchone()
        return r is not None

    def set_admin_pin(self, pin: str) -> None:
        pin = _validar_pin(pin)
        salt = os.urandom(16)
        self._con.execute("INSERT OR REPLACE INTO meta(clave, valor) VALUES('admin_salt', ?)", (salt,))
        self._con.execute("INSERT OR REPLACE INTO meta(clave, valor) VALUES('admin_hash', ?)",
                          (_pin_hash(pin, salt),))
        self._con.commit()

    def verify_admin_pin(self, pin: str) -> bool:
        rs = self._con.execute("SELECT valor FROM meta WHERE clave='admin_salt'").fetchone()
        rh = self._con.execute("SELECT valor FROM meta WHERE clave='admin_hash'").fetchone()
        if not rs or not rh:
            return False
        return hmac.compare_digest(_pin_hash((pin or "").strip(), rs[0]), rh[0])

    # ------------------------------------------------------------ empleados
    def add_empleado(self, nombre: str, pin: str) -> int:
        nombre = nombre.strip()
        if not nombre:
            raise StoreError("El nombre no puede estar vacio.")
        pin = _validar_pin(pin)
        salt = os.urandom(16)
        try:
            cur = self._con.execute(
                "INSERT INTO empleados(nombre, pin_salt, pin_hash, creado) VALUES(?,?,?,?)",
                (nombre, salt, _pin_hash(pin, salt), _now()))
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"Ya existe un empleado llamado «{nombre}».") from exc
        self._con.commit()
        return int(cur.lastrowid)

    def set_pin(self, empleado_id: int, pin: str) -> None:
        pin = _validar_pin(pin)
        salt = os.urandom(16)
        self._con.execute("UPDATE empleados SET pin_salt=?, pin_hash=? WHERE id=?",
                          (salt, _pin_hash(pin, salt), int(empleado_id)))
        self._con.commit()

    def set_activo(self, empleado_id: int, activo: bool) -> None:
        self._con.execute("UPDATE empleados SET activo=? WHERE id=?",
                          (1 if activo else 0, int(empleado_id)))
        self._con.commit()

    def empleados(self, solo_activos: bool = True) -> list[tuple[int, str, bool]]:
        q = "SELECT id, nombre, activo FROM empleados"
        if solo_activos:
            q += " WHERE activo=1"
        q += " ORDER BY nombre COLLATE NOCASE"
        return [(int(i), n, bool(a)) for i, n, a in self._con.execute(q)]

    def verify_pin(self, empleado_id: int, pin: str) -> bool:
        r = self._con.execute("SELECT pin_salt, pin_hash FROM empleados WHERE id=? AND activo=1",
                              (int(empleado_id),)).fetchone()
        if not r:
            return False
        return hmac.compare_digest(_pin_hash((pin or "").strip(), r[0]), r[1])

    # -------------------------------------------------------------- fichajes
    def _ultimo_hash(self) -> str:
        r = self._con.execute("SELECT hash FROM fichajes ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else GENESIS

    def ultimo_tipo(self, empleado_id: int) -> str | None:
        """Ultimo movimiento EFECTIVO (entrada/salida) del empleado, para
        alternar. Las correcciones cuentan por su fecha/tipo REAL: corregir una
        salida olvidada resincroniza el kiosco (si no, quedaba '● dentro' para
        siempre y el primer toque del dia siguiente grababa una salida). Una
        correccion ANTIGUA intercalada no cambia nada: su ts_real es anterior
        al ultimo movimiento real."""
        r = self._con.execute(
            "SELECT CASE WHEN tipo='correccion' THEN tipo_real ELSE tipo END "
            "FROM fichajes WHERE empleado_id=? AND (tipo IN ('entrada','salida') "
            "OR (tipo='correccion' AND tipo_real!='')) "
            "ORDER BY (CASE WHEN tipo='correccion' THEN ts_real ELSE ts END) DESC, id DESC "
            "LIMIT 1", (int(empleado_id),)).fetchone()
        return r[0] if r else None

    def fichar(self, empleado_id: int, tipo: str | None = None, nota: str = "",
               ts: str | None = None, ts_real: str = "", tipo_real: str = "") -> tuple[str, str]:
        """Registra un fichaje. Sin `tipo`, alterna automaticamente
        (fuera->entrada, dentro->salida). Devuelve (tipo, ts). La escritura del
        prev_hash + INSERT va en UNA transaccion explicita (BEGIN IMMEDIATE) para
        que dos fichajes concurrentes no compartan prev_hash."""
        r = self._con.execute("SELECT nombre FROM empleados WHERE id=?",
                              (int(empleado_id),)).fetchone()
        if not r:
            raise StoreError("Empleado desconocido.")
        nombre = r[0]
        if tipo is None:
            tipo = "salida" if self.ultimo_tipo(empleado_id) == "entrada" else "entrada"
        if tipo not in TIPOS:
            raise StoreError(f"Tipo de fichaje invalido: {tipo}")
        ts = ts or _now()
        try:
            self._con.execute("BEGIN IMMEDIATE")   # bloqueo de escritura: prev_hash consistente
            prev = self._ultimo_hash()
            h = hash_asiento(prev, empleado_id, nombre, tipo, ts, nota, ts_real, tipo_real)
            self._con.execute(
                "INSERT INTO fichajes(empleado_id, nombre, tipo, ts, nota, ts_real, tipo_real, "
                "prev_hash, hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (int(empleado_id), nombre, tipo, ts, nota, ts_real, tipo_real, prev, h))
            self._con.execute("COMMIT")
        except sqlite3.Error:
            try:
                self._con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return tipo, ts

    def add_correccion(self, empleado_id: int, ts_real: str, tipo_real: str, motivo: str) -> None:
        """Correccion de un olvido: asiento NUEVO encadenado que documenta el
        movimiento real (fecha/tipo en columnas propias, firmadas). Jamas se
        edita ni borra nada; el informe imputa las horas al dia REAL."""
        if tipo_real not in ("entrada", "salida"):
            raise StoreError("La correccion debe ser una entrada o una salida.")
        try:
            datetime.strptime(ts_real, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                # admite sin segundos y los normaliza
                ts_real = datetime.strptime(ts_real, "%Y-%m-%d %H:%M").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise StoreError("Fecha/hora real invalida (usa AAAA-MM-DD HH:MM).") from exc
        nota = f"Correccion: {motivo.strip()}" if motivo.strip() else "Correccion"
        self.fichar(empleado_id, tipo="correccion", nota=nota,
                    ts_real=ts_real, tipo_real=tipo_real)

    def fichajes_mes(self, year: int, month: int,
                     empleado_id: int | None = None) -> list[Fichaje]:
        """Fichajes cuyo dia EFECTIVO (ts_real si es correccion, ts si no) cae en
        el mes pedido. Asi una correccion tecleada en agosto de un olvido de
        julio aparece en el informe de JULIO."""
        pref = f"{year:04d}-{month:02d}-"
        q = ("SELECT id, empleado_id, nombre, tipo, ts, nota, hash, ts_real, tipo_real "
             "FROM fichajes WHERE ((tipo='correccion' AND ts_real LIKE ?) "
             "OR (tipo!='correccion' AND ts LIKE ?))")
        args: list = [pref + "%", pref + "%"]
        if empleado_id is not None:
            q += " AND empleado_id=?"
            args.append(int(empleado_id))
        q += " ORDER BY id"
        return [Fichaje(*row) for row in self._con.execute(q, args)]

    def fichajes_mes_ampliado(self, year: int, month: int,
                              empleado_id: int | None = None) -> list[Fichaje]:
        """Como fichajes_mes pero con UN DIA de margen a cada lado. Un turno
        nocturno que cruza el cambio de mes (31-jul 22:00 -> 1-ago 06:00)
        necesita ambos movimientos en la consulta para emparejarse; troceado
        por mes, cada informe veia medio turno (0 h + incidencia falsa en los
        DOS meses). Los informes usan esta consulta + resumen_mes(), que
        despues descarta los dias del margen."""
        ini = (date(year, month, 1) - timedelta(days=1)).isoformat()
        fin = (date(year + month // 12, month % 12 + 1, 1) + timedelta(days=1)).isoformat()
        q = ("SELECT id, empleado_id, nombre, tipo, ts, nota, hash, ts_real, tipo_real "
             "FROM fichajes WHERE ((tipo='correccion' AND ts_real>=? AND ts_real<?) "
             "OR (tipo!='correccion' AND ts>=? AND ts<?))")
        args: list = [ini, fin, ini, fin]
        if empleado_id is not None:
            q += " AND empleado_id=?"
            args.append(int(empleado_id))
        q += " ORDER BY id"
        return [Fichaje(*row) for row in self._con.execute(q, args)]

    def n_asientos(self) -> int:
        return int(self._con.execute("SELECT COUNT(*) FROM fichajes").fetchone()[0])

    # ------------------------------------------------------------ integridad
    def verificar_cadena(self) -> tuple[bool, int | None, int]:
        """(ok, primer_id_roto, total). Recalcula toda la cadena firmando los
        mismos campos que fichar() (incluido empleado_id y los de correccion)."""
        prev = GENESIS
        total = 0
        for (fid, eid, nombre, tipo, ts, nota, prev_g, h, ts_real, tipo_real) in self._con.execute(
                "SELECT id, empleado_id, nombre, tipo, ts, nota, prev_hash, hash, ts_real, tipo_real "
                "FROM fichajes ORDER BY id"):
            total += 1
            calc = hash_asiento(prev, eid, nombre, tipo, ts, nota, ts_real or "", tipo_real or "")
            if prev_g != prev or calc != h:
                return False, int(fid), total
            prev = h
        return True, None, total

    def huella(self) -> str:
        """Hash del ultimo asiento (la 'punta' de la cadena), para el informe."""
        return self._ultimo_hash()

    # ---------------------------------------------------------------- backup
    def backup(self, dest_dir: str) -> str:
        """Copia integra de la BD + un sello .txt con la huella y el numero de
        asientos. IMPORTANTE (ver README): el sello etiqueta el momento de la
        copia; NO es una prueba de no-manipulacion por si mismo. La defensa real
        es conservar estas copias/PDF en un tercero (la gestoria): comparar la
        huella y el numero de asientos entre copias sucesivas delata un recorte."""
        d = Path(dest_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest = d / f"fichajes_backup_{stamp}.db"
        dst = sqlite3.connect(str(dest))
        try:
            with dst:
                self._con.backup(dst)
        finally:
            dst.close()
        sello = d / f"fichajes_backup_{stamp}.sello.txt"
        ok, _, total = self.verificar_cadena()
        sello.write_text(
            f"FichajeLocal - sello de la copia de seguridad\nFecha de la copia: {_now()}\n"
            f"Asientos en esta copia: {total}\nCadena interna coherente: {'SI' if ok else 'NO'}\n"
            f"Huella (hash del ultimo asiento): {self.huella()}\n\n"
            "Guarda estas copias en un lugar de confianza (p.ej. envialas a tu gestoria). "
            "Si el numero de asientos o la huella de una copia posterior no encaja con esta, "
            "el registro se recorto o reescribio despues.\n", encoding="utf-8")
        return str(dest)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------- horas trabajadas
@dataclass
class DiaResumen:
    fecha: str                   # YYYY-MM-DD (dia efectivo)
    movimientos: list[str]       # ["08:01 entrada", "14:03 salida", ...]
    horas: float                 # horas trabajadas imputadas a ese dia
    incidencias: list[str]


def _mov_efectivos(fichajes: list[Fichaje]) -> list[tuple[str, str, bool]]:
    """Normaliza a (ts_efectivo, tipo_efectivo, es_correccion) ordenado por ts
    efectivo: una correccion aporta su ts_real/tipo_real como movimiento real."""
    movs = []
    for f in fichajes:
        if f.tipo == "correccion":
            if f.tipo_real and f.ts_real:
                movs.append((f.ts_real, f.tipo_real, True))
        else:
            movs.append((f.ts, f.tipo, False))
    movs.sort(key=lambda m: m[0])
    return movs


def resumen_por_dia(fichajes: list[Fichaje]) -> list[DiaResumen]:
    """Agrupa los fichajes de UN empleado por dia y calcula horas. PURO.

    Empareja sobre la SECUENCIA completa ordenada (no por cubos de dia), asi un
    turno que cruza medianoche (22:00->06:00) suma bien y se imputa al dia de la
    ENTRADA. Las correcciones se integran como movimientos reales."""
    movs = _mov_efectivos(fichajes)
    dias: dict[str, DiaResumen] = {}

    def dia(fecha: str) -> DiaResumen:
        if fecha not in dias:
            dias[fecha] = DiaResumen(fecha=fecha, movimientos=[], horas=0.0, incidencias=[])
        return dias[fecha]

    entrada_ts: str | None = None
    for ts, tipo, _corr in movs:
        fecha, hhmm = ts[:10], ts[11:16]
        dia(fecha).movimientos.append(f"{hhmm} {tipo}")
        if tipo == "entrada":
            if entrada_ts is not None:
                dia(entrada_ts[:10]).incidencias.append(
                    f"entrada del {entrada_ts[11:16]} sin salida (jornada sin cerrar)")
            entrada_ts = ts
        else:  # salida
            if entrada_ts is None:
                dia(fecha).incidencias.append(f"salida a las {hhmm} sin entrada previa")
            else:
                horas = _horas_entre(entrada_ts, ts)
                dia(entrada_ts[:10]).horas += horas    # se imputa al dia de la entrada
                entrada_ts = None
    if entrada_ts is not None:
        dia(entrada_ts[:10]).incidencias.append("entrada sin salida (jornada sin cerrar)")

    for d in dias.values():
        d.horas = round(d.horas, 2)
    return [dias[f] for f in sorted(dias)]


def resumen_mes(fichajes: list[Fichaje], year: int, month: int) -> list[DiaResumen]:
    """Resumen de UN mes a partir de la secuencia AMPLIADA (±1 dia, ver
    fichajes_mes_ampliado): empareja sobre toda la secuencia —los turnos
    nocturnos de fin de mes cierran bien e imputan sus horas al dia de la
    ENTRADA— y devuelve solo los dias que caen dentro del mes pedido. PURO."""
    pref = f"{year:04d}-{month:02d}-"
    return [d for d in resumen_por_dia(fichajes) if d.fecha.startswith(pref)]


def _horas_entre(ts0: str, ts1: str) -> float:
    t0 = datetime.strptime(ts0, "%Y-%m-%d %H:%M:%S")
    t1 = datetime.strptime(ts1, "%Y-%m-%d %H:%M:%S")
    return max(0.0, (t1 - t0).total_seconds() / 3600.0)
