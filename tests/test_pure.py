"""Tests de FichajeLocal: cadena de hashes, PINs, alternancia, horas e informes.
Ejecutar:  python -m pytest tests/ -q   (desde la carpeta FichajeLocal)"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fichajelocal import report  # noqa: E402
from fichajelocal.store import (GENESIS, Fichaje, Store, StoreError,  # noqa: E402
                                hash_asiento, resumen_por_dia)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "test.db"))
    yield s
    s.close()


# ---------------------------------------------------------------- empleados
def test_alta_y_pin(store):
    eid = store.add_empleado("Ana", "1234")
    assert store.verify_pin(eid, "1234")
    assert not store.verify_pin(eid, "9999")
    store.set_pin(eid, "5678")
    assert store.verify_pin(eid, "5678") and not store.verify_pin(eid, "1234")


def test_alta_validaciones(store):
    with pytest.raises(StoreError):
        store.add_empleado("", "1234")
    with pytest.raises(StoreError):
        store.add_empleado("Luis", "12")        # PIN corto
    with pytest.raises(StoreError):
        store.add_empleado("Luis", "abcd")      # PIN no numerico
    with pytest.raises(StoreError):
        store.add_empleado("Luis", "123456789")  # PIN demasiado largo (>8)
    store.add_empleado("Luis", "1234")
    with pytest.raises(StoreError):
        store.add_empleado("Luis", "9876")      # duplicado


def test_admin_pin_numerico_obligatorio(store):
    assert not store.admin_configurado()
    with pytest.raises(StoreError):
        store.set_admin_pin("clave")            # no tecleable en el pad -> rechazado
    store.set_admin_pin("4321")
    assert store.admin_configurado()
    assert store.verify_admin_pin("4321") and not store.verify_admin_pin("0000")


# ----------------------------------------------------------------- fichajes
def test_alternancia_automatica(store):
    eid = store.add_empleado("Ana", "1234")
    t1, _ = store.fichar(eid)
    t2, _ = store.fichar(eid)
    t3, _ = store.fichar(eid)
    assert (t1, t2, t3) == ("entrada", "salida", "entrada")


def test_correccion_no_altera_alternancia(store):
    eid = store.add_empleado("Ana", "1234")
    store.fichar(eid)                                    # entrada
    store.add_correccion(eid, "2026-07-10 14:00", "salida", "olvido")
    t, _ = store.fichar(eid)
    assert t == "salida"        # la correccion no cuenta como movimiento de alternancia


# ------------------------------------------------------------------- cadena
def test_cadena_integra_y_huella(store):
    eid = store.add_empleado("Ana", "1234")
    for _ in range(6):
        store.fichar(eid)
    ok, roto, total = store.verificar_cadena()
    assert ok and roto is None and total == 6
    assert store.huella() != GENESIS


def test_cadena_detecta_edicion(store, tmp_path):
    eid = store.add_empleado("Ana", "1234")
    for _ in range(5):
        store.fichar(eid)
    con = sqlite3.connect(str(tmp_path / "test.db"))
    con.execute("UPDATE fichajes SET ts='2026-01-01 00:00:00' WHERE id=3")
    con.commit()
    con.close()
    ok, roto, _total = store.verificar_cadena()
    assert not ok and roto == 3


def test_cadena_detecta_reatribucion_empleado(store, tmp_path):
    # empleado_id ESTA firmado: reasignar un fichaje a otro empleado rompe la cadena
    ana = store.add_empleado("Ana", "1234")
    bob = store.add_empleado("Bob", "5678")
    store.fichar(ana, tipo="entrada", ts="2026-07-01 08:00:00")
    con = sqlite3.connect(str(tmp_path / "test.db"))
    con.execute("UPDATE fichajes SET empleado_id=? WHERE empleado_id=?", (bob, ana))
    con.commit()
    con.close()
    ok, roto, _ = store.verificar_cadena()
    assert not ok and roto is not None


def test_hash_asiento_incluye_empleado_y_es_canonico():
    h1 = hash_asiento(GENESIS, 1, "Ana", "entrada", "2026-07-12 08:00:00", "")
    h2 = hash_asiento(GENESIS, 1, "Ana", "entrada", "2026-07-12 08:00:00", "")
    h3 = hash_asiento(GENESIS, 2, "Ana", "entrada", "2026-07-12 08:00:00", "")  # otro empleado
    assert h1 == h2 and h1 != h3 and len(h1) == 64
    # sin ambiguedad de separador: campos con '|' no colisionan
    a = hash_asiento(GENESIS, 1, "Ana", "entrada", "2026-07-12 08:00:00", "x|y")
    b = hash_asiento(GENESIS, 1, "Ana", "entrada", "2026-07-12 08:00:00|x", "y")
    assert a != b


# -------------------------------------------------------------------- horas
def _f(i, tipo, ts, nota="", ts_real="", tipo_real=""):
    return Fichaje(id=i, empleado_id=1, nombre="Ana", tipo=tipo, ts=ts, nota=nota,
                   hash="h", ts_real=ts_real, tipo_real=tipo_real)


def test_resumen_horas_con_pausa():
    fich = [_f(1, "entrada", "2026-07-12 08:00:00"),
            _f(2, "salida", "2026-07-12 14:00:00"),
            _f(3, "entrada", "2026-07-12 15:00:00"),
            _f(4, "salida", "2026-07-12 18:30:00")]
    dias = resumen_por_dia(fich)
    assert len(dias) == 1 and dias[0].horas == 9.5 and dias[0].incidencias == []


def test_resumen_cruza_medianoche():
    # turno nocturno 22:00 -> 06:00 = 8 h, imputadas al dia de la ENTRADA. La
    # salida se muestra como movimiento del dia 13 (sin horas ni incidencia): asi
    # el turno suma bien y no aparecen las falsas 'entrada sin salida'/'salida
    # sin entrada' que daba el agrupado por dias.
    fich = [_f(1, "entrada", "2026-07-12 22:00:00"),
            _f(2, "salida", "2026-07-13 06:00:00")]
    dias = {d.fecha: d for d in resumen_por_dia(fich)}
    assert dias["2026-07-12"].horas == 8.0
    assert dias["2026-07-12"].incidencias == []
    assert dias["2026-07-13"].horas == 0.0
    assert dias["2026-07-13"].incidencias == []      # NO hay 'salida sin entrada'


def test_resumen_correccion_reintegra_horas():
    # se olvido la salida; una correccion con la salida REAL debe cerrar la jornada
    fich = [_f(1, "entrada", "2026-07-12 08:00:00"),
            _f(2, "correccion", "2026-08-01 10:00:00", nota="olvido",
               ts_real="2026-07-12 15:00:00", tipo_real="salida")]
    dias = resumen_por_dia(fich)
    assert len(dias) == 1
    assert dias[0].fecha == "2026-07-12" and dias[0].horas == 7.0
    assert dias[0].incidencias == []


def test_fichajes_mes_correccion_va_al_mes_real(store):
    eid = store.add_empleado("Ana", "1234")
    store.fichar(eid, tipo="entrada", ts="2026-07-01 08:00:00")
    # correccion tecleada en agosto de un olvido de JULIO
    store.add_correccion(eid, "2026-07-01 15:00:00", "salida", "olvido")
    jul = store.fichajes_mes(2026, 7, eid)
    ago = store.fichajes_mes(2026, 8, eid)
    assert len(jul) == 2                 # la correccion cuenta en JULIO (ts_real)
    assert ago == []
    dias = resumen_por_dia(jul)
    assert dias[0].horas == 7.0


# ------------------------------------------------------------------ backup
def test_backup_con_sello(store, tmp_path):
    eid = store.add_empleado("Ana", "1234")
    store.fichar(eid)
    dest = store.backup(str(tmp_path / "bk"))
    assert Path(dest).is_file() and Path(dest).stat().st_size > 0
    sellos = list((tmp_path / "bk").glob("*.sello.txt"))
    assert sellos and "coherente: SI" in sellos[0].read_text(encoding="utf-8")
    con = sqlite3.connect(dest)
    n = con.execute("SELECT COUNT(*) FROM fichajes").fetchone()[0]
    con.close()
    assert n == 1


# ----------------------------------------------------------------- informes
def test_pdf_mensual(tmp_path, store):
    import fitz
    eid = store.add_empleado("Bar Paco Ana", "1234")
    store.fichar(eid, tipo="entrada", ts="2026-07-01 08:00:00")
    store.fichar(eid, tipo="salida", ts="2026-07-01 14:00:00")
    store.fichar(eid, tipo="entrada", ts="2026-07-02 08:05:00")   # sin salida
    fich = store.fichajes_mes(2026, 7, eid)
    out = str(tmp_path / "informe.pdf")
    report.exportar_pdf(out, negocio="Bar Paco & Cia <sl>", year=2026, month=7,
                        por_empleado={"Bar Paco Ana": fich},
                        integridad=store.verificar_cadena(), huella=store.huella())
    doc = fitz.open(out)
    text = "\n".join(doc[p].get_text("text") for p in range(doc.page_count))
    doc.close()
    assert "julio 2026" in text
    assert "CADENA COHERENTE" in text
    assert "6.00 h" in text
    assert "sin cerrar" in text
    assert "Bar Paco & Cia <sl>" in text     # escapado como texto


def test_pdf_sin_fichajes_lanza(tmp_path, store):
    with pytest.raises(report.ReportError):
        report.exportar_pdf(str(tmp_path / "x.pdf"), negocio="", year=2026, month=7,
                            por_empleado={}, integridad=(True, None, 0), huella=GENESIS)


def test_csv_incluye_y_neutraliza_formulas(tmp_path, store):
    eid = store.add_empleado("=1+1", "1234")     # nombre con prefijo peligroso
    store.fichar(eid, tipo="entrada", ts="2026-07-01 08:00:00")
    out = str(tmp_path / "r.csv")
    report.exportar_csv(out, store.fichajes_mes(2026, 7))
    contenido = Path(out).read_text(encoding="utf-8-sig")
    assert "fecha;hora;empleado;tipo" in contenido.splitlines()[0]
    assert "2026-07-01;08:00:00;'=1+1;entrada" in contenido   # prefijado con apostrofo
