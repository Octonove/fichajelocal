"""FichajeLocal — registro horario para pymes, 100% en tu PC.

Un kiosco de fichaje en el ordenador del negocio: cada empleado ficha entrada y
salida con su PIN, y cada asiento queda ENCADENADO criptograficamente al
anterior (SHA-256): editar un registro sin dejar rastro es imposible, que es
exactamente lo que Inspeccion de Trabajo espera de un registro fiable. Informe
mensual en PDF y CSV listos para la gestoria. Sin nube, sin cuotas por
empleado, sin cuentas: los datos de jornada de tu equipo no salen del negocio.
"""

from __future__ import annotations

APP_NAME = "FichajeLocal"
APP_VERSION = "1.0.1"   # fuente unica de version: build-installer.ps1 la inyecta al .iss
