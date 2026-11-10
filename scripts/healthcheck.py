#!/usr/bin/env python
"""Healthcheck para Docker/Railway: comprueba que el último ciclo fue reciente."""

import os
import sqlite3
import sys
import time

RUTA_DB = os.getenv("DATABASE", "/data/ofertas.db")
MAX_HORAS = int(os.getenv("HEARTBEAT_MAX_HOURS", "6"))


def main() -> int:
    if not os.path.exists(RUTA_DB):
        directorio = os.path.dirname(os.path.abspath(RUTA_DB))
        if not os.access(directorio, os.W_OK):
            print(f"Base de datos inaccesible: {RUTA_DB}", file=sys.stderr)
            return 1
        # Aún no se ha creado la base (primer arranque).
        return 0

    try:
        conexion = sqlite3.connect(f"file:{RUTA_DB}?mode=ro", uri=True, timeout=5)
        try:
            fila = conexion.execute(
                "SELECT valor FROM ajustes WHERE clave = 'ultimo_ciclo_ok'"
            ).fetchone()
        finally:
            conexion.close()
    except sqlite3.Error as exc:
        print(f"Error leyendo la base de datos: {exc}", file=sys.stderr)
        return 1

    if not fila:
        return 0

    try:
        edad = time.time() - int(fila[0])
    except (TypeError, ValueError):
        return 1

    if edad > MAX_HORAS * 3600:
        print(f"Último ciclo correcto hace {int(edad // 60)} minutos", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
