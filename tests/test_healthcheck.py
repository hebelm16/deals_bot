import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _crear_db(ruta: Path, timestamp: int) -> None:
    conexion = sqlite3.connect(ruta)
    conexion.execute("CREATE TABLE ajustes (clave TEXT PRIMARY KEY, valor TEXT)")
    conexion.execute(
        "INSERT INTO ajustes (clave, valor) VALUES ('ultimo_ciclo_ok', ?)",
        (str(timestamp),),
    )
    conexion.commit()
    conexion.close()


def _ejecutar(ruta_db: Path) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "DATABASE": str(ruta_db), "HEARTBEAT_MAX_HOURS": "6"}
    return subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "healthcheck.py")],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_healthcheck_ok(tmp_path):
    ruta = tmp_path / "ok.db"
    _crear_db(ruta, int(time.time()))
    assert _ejecutar(ruta).returncode == 0


def test_healthcheck_ciclo_antiguo(tmp_path):
    ruta = tmp_path / "viejo.db"
    _crear_db(ruta, int(time.time()) - 7 * 3600)
    resultado = _ejecutar(ruta)
    assert resultado.returncode == 1
    assert "Último ciclo" in resultado.stderr


def test_healthcheck_sin_base_arrancando(tmp_path):
    assert _ejecutar(tmp_path / "nueva.db").returncode == 0
