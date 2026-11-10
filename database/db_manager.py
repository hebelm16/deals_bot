"""Persistencia SQLite: ofertas, deduplicación, suscripciones y ajustes."""

import hashlib
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite

from utils.models import Oferta

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# Parámetros de seguimiento que no cambian el producto y generan duplicados.
TRACKING_PARAMS = {
    "ref",
    "ref_",
    "tag",
    "ascsubtag",
    "linkcode",
    "camp",
    "creative",
    "source",
    "src",
    "mkt",
    "th",
    "psc",
    "smid",
    "pf_rd_p",
    "pf_rd_r",
    "_encoding",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ofertas (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    precio TEXT,
    precio_original TEXT,
    link TEXT NOT NULL,
    link_canonico TEXT,
    imagen TEXT,
    tag TEXT,
    cupon TEXT,
    info_cupon TEXT,
    gancho_ia TEXT,
    timestamp INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'enviada',
    message_id INTEGER
);
CREATE TABLE IF NOT EXISTS suscripciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    keyword TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT,
    actualizado INTEGER
);
"""


def canonicalizar_link(link: Optional[str]) -> str:
    """Normaliza una URL para detectar duplicados con parámetros de seguimiento."""
    if not link:
        return ""
    candidata = str(link).strip()
    try:
        partes = urlsplit(candidata)
    except ValueError:
        return candidata
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return candidata

    host = partes.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    ruta = partes.path.rstrip("/") or "/"
    query = []
    for clave, valor in parse_qsl(partes.query, keep_blank_values=True):
        clave_lower = clave.lower()
        if clave_lower.startswith("utm_") or clave_lower in TRACKING_PARAMS:
            continue
        if clave_lower.startswith(("pd_rd_", "pf_rd_")):
            continue
        query.append((clave, valor))
    query.sort()
    return urlunsplit(("https", host, ruta, urlencode(query, doseq=True), ""))


class DBManager:
    def __init__(self, database: str):
        self.database = database
        directorio = os.path.dirname(os.path.abspath(database))
        if directorio:
            try:
                os.makedirs(directorio, exist_ok=True)
            except OSError as exc:
                raise RuntimeError(
                    f"No se puede crear el directorio de la base de datos "
                    f"'{directorio}': {exc}"
                ) from exc

    @asynccontextmanager
    async def _conexion(self) -> AsyncIterator[aiosqlite.Connection]:
        conexion = await aiosqlite.connect(self.database, timeout=30)
        try:
            await conexion.execute("PRAGMA busy_timeout=5000")
            yield conexion
        finally:
            await conexion.close()

    async def init_db(self) -> None:
        try:
            async with self._conexion() as conn:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.executescript(SCHEMA_SQL)
                await self._migrar(conn)
                await conn.commit()
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                f"No se pudo inicializar la base de datos '{self.database}': {exc}. "
                "En Railway, monta un volumen en /data y define DATABASE=/data/ofertas.db."
            ) from exc
        logger.info("Base de datos lista en %s", os.path.abspath(self.database))

    async def _migrar(self, conn: aiosqlite.Connection) -> None:
        cursor = await conn.execute("PRAGMA user_version")
        fila = await cursor.fetchone()
        version = int(fila[0]) if fila else 0

        cursor = await conn.execute("PRAGMA table_info(ofertas)")
        columnas = {fila[1] for fila in await cursor.fetchall()}
        columnas_nuevas = {
            "link_canonico": "TEXT",
            "info_cupon": "TEXT",
            "gancho_ia": "TEXT",
            "estado": "TEXT NOT NULL DEFAULT 'enviada'",
            "message_id": "INTEGER",
        }
        for nombre, tipo in columnas_nuevas.items():
            if nombre not in columnas:
                await conn.execute(
                    f"ALTER TABLE ofertas ADD COLUMN {nombre} {tipo}"
                )
                logger.info("Migración: columna ofertas.%s añadida", nombre)

        # Rellena la URL canónica de las filas antiguas.
        cursor = await conn.execute(
            "SELECT id, link FROM ofertas WHERE link_canonico IS NULL OR link_canonico = ''"
        )
        for oferta_id, link in await cursor.fetchall():
            await conn.execute(
                "UPDATE ofertas SET link_canonico = ? WHERE id = ?",
                (canonicalizar_link(link), oferta_id),
            )

        # Normaliza palabras clave antiguas antes de deduplicar.
        await conn.execute(
            "UPDATE suscripciones SET keyword = lower(trim(keyword)) "
            "WHERE keyword <> lower(trim(keyword))"
        )
        # Elimina suscripciones duplicadas antes de crear el índice único.
        await conn.execute(
            "DELETE FROM suscripciones WHERE id NOT IN "
            "(SELECT MIN(id) FROM suscripciones GROUP BY user_id, keyword)"
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_suscripciones_user_keyword "
            "ON suscripciones(user_id, keyword)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ofertas_timestamp ON ofertas(timestamp)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ofertas_link_canonico ON ofertas(link_canonico)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ofertas_estado ON ofertas(estado)")
        await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        if version != SCHEMA_VERSION:
            logger.info("Esquema migrado de la versión %s a %s", version, SCHEMA_VERSION)

    def generar_ids_oferta(self, oferta: Oferta) -> List[str]:
        """IDs compatibles: fórmula nueva (link) y fórmulas antiguas."""
        ids = [hashlib.sha256(str(oferta.link or "").encode()).hexdigest()]
        ids.extend(
            self._ids_legado(
                oferta.titulo,
                oferta.precio,
                oferta.link,
                oferta.imagen,
                oferta.precio_original,
            )
        )
        return ids

    def generar_id_oferta(self, oferta: Oferta) -> str:
        return self.generar_ids_oferta(oferta)[0]

    @staticmethod
    def _ids_legado(
        titulo: Optional[str],
        precio: Optional[str],
        link: Optional[str],
        imagen: Optional[str],
        precio_original: Optional[str],
    ) -> List[str]:
        """Reproduce el hash antiguo con y sin conversión de None a texto."""
        valores_vacios = [
            titulo or "",
            precio or "",
            link or "",
            imagen or "",
            precio_original or "",
        ]
        valores_texto = [str(titulo), str(precio), str(link), str(imagen), str(precio_original)]
        return [
            hashlib.sha256("|".join(valores_vacios).encode()).hexdigest(),
            hashlib.sha256("|".join(valores_texto).encode()).hexdigest(),
        ]

    async def guardar_oferta(self, oferta: Oferta, estado: str = "pendiente") -> str:
        oferta_id = self.generar_id_oferta(oferta)
        canonico = canonicalizar_link(oferta.link)
        async with self._conexion() as conn:
            await conn.execute(
                """
                INSERT INTO ofertas (
                    id, titulo, precio, precio_original, link, link_canonico,
                    imagen, tag, cupon, info_cupon, gancho_ia, timestamp, estado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    titulo = excluded.titulo,
                    precio = excluded.precio,
                    precio_original = excluded.precio_original,
                    link = excluded.link,
                    link_canonico = excluded.link_canonico,
                    imagen = excluded.imagen,
                    tag = excluded.tag,
                    cupon = excluded.cupon,
                    info_cupon = excluded.info_cupon,
                    gancho_ia = excluded.gancho_ia,
                    timestamp = excluded.timestamp,
                    estado = excluded.estado
                """,
                (
                    oferta_id,
                    oferta.titulo,
                    oferta.precio,
                    oferta.precio_original,
                    oferta.link,
                    canonico,
                    oferta.imagen,
                    oferta.tag,
                    oferta.cupon,
                    oferta.info_cupon,
                    oferta.gancho_ia,
                    oferta.timestamp,
                    estado,
                ),
            )
            await conn.commit()
        return oferta_id

    async def marcar_oferta_enviada(self, oferta_id: str, message_id: Optional[int]) -> None:
        async with self._conexion() as conn:
            await conn.execute(
                "UPDATE ofertas SET estado = 'enviada', message_id = ? WHERE id = ?",
                (message_id, oferta_id),
            )
            await conn.commit()

    async def marcar_oferta_fallida(self, oferta_id: str) -> None:
        async with self._conexion() as conn:
            await conn.execute(
                "UPDATE ofertas SET estado = 'fallida' WHERE id = ?", (oferta_id,)
            )
            await conn.commit()

    async def obtener_indices_existentes(self) -> Tuple[Set[str], Set[str]]:
        """
        Devuelve (ids_conocidos, urls_canonicas) para el filtro de duplicados.

        Las ofertas fallidas y las pendientes antiguas se excluyen para que se
        reintenten en el siguiente ciclo.
        """
        ids: Set[str] = set()
        canonicos: Set[str] = set()
        ahora = int(time.time())
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT id, titulo, precio, link, imagen, precio_original, "
                "link_canonico, estado, timestamp FROM ofertas"
            )
            filas = await cursor.fetchall()

        for fila in filas:
            (
                oferta_id,
                titulo,
                precio,
                link,
                imagen,
                precio_original,
                link_canonico,
                estado,
                timestamp,
            ) = fila
            estado = estado or "enviada"
            if estado == "fallida":
                continue
            if estado == "pendiente" and int(timestamp or 0) < ahora - 3600:
                continue
            ids.add(oferta_id)
            ids.update(self._ids_legado(titulo, precio, link, imagen, precio_original))
            canonicos.add(link_canonico or canonicalizar_link(link))
        return ids, canonicos

    async def obtener_ids_recientes(self) -> Set[str]:
        """Compatibilidad: solo el conjunto de IDs conocidos."""
        ids, _ = await self.obtener_indices_existentes()
        return ids

    async def limpiar_ofertas_antiguas(self, dias: int) -> int:
        limite = int(time.time()) - (dias * 24 * 60 * 60)
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "DELETE FROM ofertas WHERE timestamp < ?", (limite,)
            )
            eliminadas = cursor.rowcount
            await conn.commit()
        logger.info("Se eliminaron %s ofertas antiguas", eliminadas)
        return eliminadas

    async def obtener_todas_las_ofertas(self) -> List[Dict[str, Any]]:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT id, titulo, precio, link, timestamp, estado FROM ofertas"
            )
            return [
                {
                    "id": fila[0],
                    "titulo": fila[1],
                    "precio": fila[2],
                    "link": fila[3],
                    "timestamp": fila[4],
                    "estado": fila[5],
                }
                for fila in await cursor.fetchall()
            ]

    async def agregar_suscripcion(self, user_id: str, chat_id: str, keyword: str) -> bool:
        limpia = " ".join((keyword or "").split()).lower()
        if not limpia:
            return False
        async with self._conexion() as conn:
            try:
                await conn.execute(
                    "INSERT INTO suscripciones (user_id, chat_id, keyword) VALUES (?, ?, ?)",
                    (str(user_id), str(chat_id), limpia),
                )
                await conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    async def eliminar_suscripcion(self, user_id: str, keyword: str) -> bool:
        limpia = " ".join((keyword or "").split()).lower()
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "DELETE FROM suscripciones WHERE user_id = ? AND keyword = ?",
                (str(user_id), limpia),
            )
            eliminada = cursor.rowcount > 0
            await conn.commit()
            return eliminada

    async def obtener_suscripciones_por_usuario(self, user_id: str) -> List[str]:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT keyword FROM suscripciones WHERE user_id = ? ORDER BY keyword",
                (str(user_id),),
            )
            return [fila[0] for fila in await cursor.fetchall()]

    async def contar_suscripciones_usuario(self, user_id: str) -> int:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM suscripciones WHERE user_id = ?", (str(user_id),)
            )
            fila = await cursor.fetchone()
            return int(fila[0]) if fila else 0

    async def eliminar_suscripciones_por_chat(self, chat_id: str) -> int:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "DELETE FROM suscripciones WHERE chat_id = ?", (str(chat_id),)
            )
            eliminadas = cursor.rowcount
            await conn.commit()
            return eliminadas

    async def eliminar_todas_suscripciones_usuario(self, user_id: str) -> int:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "DELETE FROM suscripciones WHERE user_id = ?", (str(user_id),)
            )
            eliminadas = cursor.rowcount
            await conn.commit()
            return eliminadas

    async def obtener_todas_las_suscripciones(self) -> List[Dict[str, str]]:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT id, user_id, chat_id, keyword FROM suscripciones"
            )
            return [
                {
                    "id": fila[0],
                    "user_id": fila[1],
                    "chat_id": fila[2],
                    "keyword": fila[3],
                }
                for fila in await cursor.fetchall()
            ]

    async def get_ajuste(self, clave: str, default: Optional[str] = None) -> Optional[str]:
        async with self._conexion() as conn:
            cursor = await conn.execute(
                "SELECT valor FROM ajustes WHERE clave = ?", (clave,)
            )
            fila = await cursor.fetchone()
            return fila[0] if fila else default

    async def set_ajuste(self, clave: str, valor: str) -> None:
        async with self._conexion() as conn:
            await conn.execute(
                "INSERT INTO ajustes (clave, valor, actualizado) VALUES (?, ?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, "
                "actualizado = excluded.actualizado",
                (clave, str(valor), int(time.time())),
            )
            await conn.commit()

    async def marcar_ciclo(self, exito: bool, detalle: str = "") -> None:
        ahora = int(time.time())
        await self.set_ajuste("ultimo_ciclo_ts", str(ahora))
        await self.set_ajuste("ultimo_ciclo_exito", "1" if exito else "0")
        await self.set_ajuste("ultimo_ciclo_detalle", (detalle or "")[:500])
        if exito:
            await self.set_ajuste("ultimo_ciclo_ok", str(ahora))

    async def estadisticas(self) -> Dict[str, int]:
        async with self._conexion() as conn:
            resultado: Dict[str, int] = {}
            for nombre, consulta in {
                "ofertas": "SELECT COUNT(*) FROM ofertas",
                "suscripciones": "SELECT COUNT(*) FROM suscripciones",
                "pendientes": "SELECT COUNT(*) FROM ofertas WHERE estado = 'pendiente'",
                "fallidas": "SELECT COUNT(*) FROM ofertas WHERE estado = 'fallida'",
                "duplicadas": "SELECT COUNT(*) FROM ofertas WHERE estado = 'duplicada'",
            }.items():
                cursor = await conn.execute(consulta)
                fila = await cursor.fetchone()
                resultado[nombre] = int(fila[0]) if fila else 0
            return resultado
