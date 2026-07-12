# FichajeLocal

**Registro horario para pymes, 100% en tu PC**: un kiosco de fichaje en el ordenador del mostrador. Cada empleado toca su nombre, marca su PIN, y la app registra entrada o salida automáticamente. El informe mensual sale **listo para tu gestoría** (PDF y CSV) — sin nube, sin cuotas por empleado, sin cuentas.

> En España el registro de jornada es **obligatorio desde 2019** para toda empresa con empleados (art. 34.9 ET), se conserva 4 años y las multas van de 751 € a 7.500 € por centro. FichajeLocal lo resuelve gratis y sin que los datos de jornada de tu equipo salgan del negocio.

## 🔗 La diferencia: cadena de integridad

Cada fichaje queda **encadenado criptográficamente** (SHA-256) al anterior, firmando también **quién** ficha: editar, borrar o reordenar un asiento intermedio rompe la cadena y el informe lo delata — al contrario que un Excel, que cualquiera puede retocar. Las correcciones de olvidos se añaden como asientos nuevos también encadenados: el rastro completo queda siempre a la vista.

**Alcance honesto** (importante): la cadena garantiza que nadie ha alterado un asiento suelto ni el orden. Por sí sola, en un equipo cuyo dueño es la propia empresa, **no puede impedir que alguien con acceso al fichero reescriba todo el historial** desde cero. La defensa práctica es sencilla y ya viene incorporada: **cada informe y cada copia mensual llevan su "huella" y su número de asientos**; si los conservas en tu **gestoría** (un tercero de confianza), una reescritura o un recorte posteriores dejan de cuadrar con lo ya entregado y se detectan. Guarda los PDF/copias cada mes.

> Despliegue: usa FichajeLocal **siempre en la misma cuenta de Windows** del PC del mostrador. Los datos se guardan en `%APPDATA%\FichajeLocal\fichajes.db` (por usuario de Windows); si fichas desde otra cuenta, el registro se guardaría por separado. Configura la **copia de seguridad automática** a un USB o carpeta de red desde Administración → Ajustes.

## ⬇️ Descargar (Windows 10/11)

### ➡️ [**Descargar FichajeLocal (instalador .exe)**](https://github.com/Octonove/fichajelocal/releases/latest/download/FichajeLocal-Setup.exe)

Descarga **directa** del instalador, sin registro. También puedes ver la [última versión y notas](https://github.com/Octonove/fichajelocal/releases/latest).

> Si Windows muestra *"Windows protegió tu PC"* (es normal en programas nuevos sin firma): pulsa **Más información → Ejecutar de todas formas**. Se instala sin permisos de administrador.

## Funciones

- **Kiosco táctil**: reloj grande, botones por empleado con su estado (dentro/fuera), teclado PIN en pantalla. Opción de pantalla completa.
- **Entrada/salida automática**: la app sabe si estás dentro o fuera; solo marcas tu PIN.
- **PINs seguros**: jamás se guardan en claro (PBKDF2-SHA256 con salt por empleado). PIN de administración aparte.
- **Administración**: alta/baja de empleados, corrección de olvidos (como asiento encadenado, nunca edición), verificación de integridad con un clic.
- **Informe mensual PDF** con horas por día y empleado, incidencias (jornadas sin cerrar, salidas sin entrada) y el **sello de integridad** de la cadena; **CSV** con separador `;` listo para Excel/gestoría.
- **Copia de seguridad automática** al cerrar (a USB o carpeta de red), con sello de integridad.

## Stack

Python 3 + Tkinter (ttk) · SQLite (stdlib) + cadena SHA-256 · PyMuPDF (informes PDF).

Depende del paquete compartido de la suite [`octonove-core`](https://github.com/Octonove/octonove-core) (tema, config): debe estar en el `sys.path` del entorno (vía `.pth` o copia junto al proyecto).

## Compilar

```powershell
.\build\build.ps1              # ejecutable (PyInstaller onedir)
.\build\build-installer.ps1    # instalador (Inno Setup)
```

## Tests

```powershell
python -m pytest tests/ -q
```

## Licencia

[MIT](LICENSE) — © 2026 Octonove.

*FichajeLocal es una herramienta de registro: no constituye asesoramiento laboral ni jurídico.*
