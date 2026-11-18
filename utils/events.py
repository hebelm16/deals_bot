"""Gestión del modo evento (Black Friday, Prime Day, etc.)"""

import time
from typing import NamedTuple, Optional

from database.db_manager import DBManager


class Evento(NamedTuple):
    nombre: str
    fin_ts: float
    contador_ia: int

_estado_evento: Optional[Evento] = None

def esta_activo() -> bool:
    if not _estado_evento:
        return False
    return time.time() < _estado_evento.fin_ts

def nombre_evento() -> Optional[str]:
    return _estado_evento.nombre if esta_activo() else None

def incrementar_contador_ia() -> None:
    global _estado_evento
    if _estado_evento:
        _estado_evento = _estado_evento._replace(contador_ia=_estado_evento.contador_ia + 1)

def usar_ia() -> bool:
    if not esta_activo():
        return True
    return _estado_evento.contador_ia < 350

async def cargar_evento(db: DBManager) -> None:
    global _estado_evento
    data = await db.get_ajuste("evento.estado")
    if not data:
        return
    nombre, fin_ts, contador = data.split("|")
    _estado_evento = Evento(nombre, float(fin_ts), int(contador))

async def activar_evento(db: DBManager, nombre: str, horas: int) -> None:
    global _estado_evento
    fin = time.time() + (horas * 3600)
    _estado_evento = Evento(nombre, fin, 0)
    await db.set_ajuste("evento.estado", f"{nombre}|{fin}|0")

async def desactivar_evento(db: DBManager) -> None:
    global _estado_evento
    _estado_evento = None
    await db.set_ajuste("evento.estado", "")
