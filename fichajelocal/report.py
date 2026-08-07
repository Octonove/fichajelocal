"""Informe mensual de registro horario (PDF con PyMuPDF + CSV para la gestoria).

El PDF lleva el SELLO DE INTEGRIDAD: numero de asientos, huella de la cadena y
resultado de la verificacion — es lo que convierte el informe en un registro
defendible ante una inspeccion (editar la BD rompe la cadena y se ve aqui)."""

from __future__ import annotations

import csv
import html
from pathlib import Path

from .store import DiaResumen, Fichaje, resumen_mes

PW, PH, M = 595, 842, 42
TW = PW - 2 * M
NAVY = "#1e3a5f"

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class ReportError(Exception):
    pass


def _measure(html_str: str, width: float) -> float:
    import fitz
    d = fitz.open()
    try:
        pg = d.new_page(width=width + 80, height=4000)
        spare, _ = pg.insert_htmlbox(fitz.Rect(0, 0, width, 4000), html_str)
        return max(1.0, 4000 - spare)
    finally:
        d.close()


def _rgb(hexcolor: str):
    c = hexcolor.lstrip("#")
    return int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255


def exportar_pdf(out_path: str, *, negocio: str, year: int, month: int,
                 por_empleado: dict[str, list[Fichaje]],
                 integridad: tuple[bool, int | None, int], huella: str) -> str:
    """por_empleado: {nombre: [fichajes del mes de ese empleado]}."""
    import fitz
    if not por_empleado:
        raise ReportError("No hay fichajes en ese mes.")
    doc = fitz.open()
    try:
        page = doc.new_page(width=PW, height=PH)
        y = M

        def put(html_str: str, gap: float = 6.0):
            nonlocal y, page
            h = _measure(html_str, TW)
            if y + h > PH - M:
                page = doc.new_page(width=PW, height=PH)
                y = M
            page.insert_htmlbox(fitz.Rect(M, y, PW - M, min(y + h + 2, PH - M)), html_str)
            y += h + gap

        # cabecera
        page.draw_rect(fitz.Rect(0, 0, PW, 86), color=_rgb(NAVY), fill=_rgb(NAVY))
        page.insert_htmlbox(fitz.Rect(M, 16, PW - M, 56),
                            '<div style="font-family:sans-serif;font-size:20px;font-weight:bold;'
                            'color:#ffffff">Registro de jornada — '
                            f'{MESES[month]} {year}</div>')
        page.insert_htmlbox(fitz.Rect(M, 52, PW - M, 82),
                            f'<div style="font-family:sans-serif;font-size:10px;color:#b7c7da">'
                            f'{html.escape(negocio or "Negocio sin nombre")} · generado con '
                            f'FichajeLocal, 100% en el equipo del negocio</div>')
        y = 100

        # sello de integridad (claim honesto: ver store.py / README)
        ok, roto, total = integridad
        estado = ("&#10004; CADENA COHERENTE" if ok else
                  f"&#10008; CADENA ROTA en el asiento {roto}")
        color = "#16a34a" if ok else "#dc2626"
        put(f'<div style="font-family:sans-serif;font-size:10px;color:#334155;'
            f'line-height:1.5;border:1px solid #e2e8f0;padding:6px">'
            f'<b>Sello de integridad</b> — asientos totales: {total} · '
            f'<span style="color:{color};font-weight:bold">{estado}</span><br>'
            f'Huella de la cadena (hash del ultimo asiento): '
            f'<span style="font-size:8px">{html.escape(huella)}</span><br>'
            f'Cada asiento firma criptograficamente al anterior (SHA-256): editar, borrar o '
            f'reordenar un asiento intermedio rompe la cadena. Conserva los informes y copias '
            f'(cada uno lleva su huella y su numero de asientos): comparandolos se detecta '
            f'tambien un recorte al final del registro.</div>', 12)

        # por empleado. Las listas llegan AMPLIADAS ±1 dia (fichajes_mes_ampliado)
        # para que los turnos nocturnos de fin de mes emparejen; resumen_mes
        # descarta los dias del margen. Un empleado que solo tenga movimientos
        # en el margen (dias de otro mes) no aparece en el informe.
        alguno = False
        for nombre in sorted(por_empleado, key=str.casefold):
            dias = resumen_mes(por_empleado[nombre], year, month)
            if not dias:
                continue
            alguno = True
            total_h = sum(d.horas for d in dias)
            n_inc = sum(len(d.incidencias) for d in dias)
            put(f'<div style="font-family:sans-serif;font-size:14px;font-weight:bold;'
                f'color:{NAVY};border-bottom:1px solid #e2e8f0;padding-bottom:2px">'
                f'{html.escape(nombre)} — {total_h:.2f} h en el mes'
                + (f' · {n_inc} incidencia(s)' if n_inc else "") + '</div>', 5)
            filas = []
            for d in dias:
                movs = html.escape(" · ".join(d.movimientos))
                inc = ("<br><span style=\"color:#d97706\">&#9888; "
                       + html.escape("; ".join(d.incidencias)) + "</span>") if d.incidencias else ""
                filas.append(
                    f'<tr><td style="padding:3px 6px;white-space:nowrap;color:#64748b">{d.fecha}</td>'
                    f'<td style="padding:3px 6px">{movs}{inc}</td>'
                    f'<td style="padding:3px 6px;text-align:right;white-space:nowrap">'
                    f'<b>{d.horas:.2f} h</b></td></tr>')
            # tabla EN TROZOS: un bloque mas alto que la pagina se encogeria hasta
            # ser ilegible (insert_htmlbox reescala, no pagina).
            for i in range(0, len(filas), 10):
                put('<table style="font-family:sans-serif;font-size:9px;border-collapse:collapse;'
                    'width:100%">' + "".join(filas[i:i + 10]) + "</table>", 2)
            y += 10
        if not alguno:
            raise ReportError("No hay fichajes en ese mes.")

        pie = ('<div style="font-family:sans-serif;font-size:8px;color:#94a3b8">'
               'Generado con FichajeLocal (gratis y open source) · simplificaconia.com · '
               'Registro de jornada conforme al art. 34.9 del Estatuto de los Trabajadores: '
               'conservese 4 anos a disposicion de las personas trabajadoras, de sus '
               'representantes legales y de la Inspeccion de Trabajo.</div>')
        ph = _measure(pie, TW)
        if y + ph > PH - 20:
            page = doc.new_page(width=PW, height=PH)
        page.insert_htmlbox(fitz.Rect(M, PH - 20 - ph, PW - M, PH - 16), pie)

        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            doc.save(out_path, garbage=3, deflate=True)
        except Exception as exc:  # noqa: BLE001
            raise ReportError("No se pudo guardar el informe. Si lo tienes abierto en un "
                              "visor de PDF, cierralo y vuelve a intentarlo.") from exc
    finally:
        doc.close()
    return out_path


def _celda_csv(valor: str) -> str:
    """Neutraliza la inyeccion de formulas en Excel/LibreOffice: un valor que
    empieza por = + - @ (o tab/CR) se prefija con un apostrofo."""
    s = str(valor)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def exportar_csv(out_path: str, fichajes: list[Fichaje]) -> str:
    """CSV para la gestoria (separador ';', como espera Excel es-ES). El dia y
    el tipo mostrados son los EFECTIVOS (ts_real/tipo_real en correcciones)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["fecha", "hora", "empleado", "tipo", "tipo_real", "nota", "hash"])
        for x in fichajes:
            efectivo = x.ts_real if (x.tipo == "correccion" and x.ts_real) else x.ts
            w.writerow([efectivo[:10], efectivo[11:], _celda_csv(x.nombre), x.tipo,
                        x.tipo_real, _celda_csv(x.nota), x.hash])
    return out_path
