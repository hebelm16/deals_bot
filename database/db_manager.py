import aiosqlite
import hashlib
import time
import logging
from typing import Dict, Any, List
from utils.models import Oferta

class DBManager:
    def __init__(self, database: str):
        self.database = database

    async def init_db(self) -> None:
        async with aiosqlite.connect(self.database) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS ofertas (
                    id TEXT PRIMARY KEY,
                    titulo TEXT,
                    precio TEXT,
                    precio_original TEXT,
                    link TEXT,
                    imagen TEXT,
                    tag TEXT,
                    cupon TEXT,
                    timestamp INTEGER
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS suscripciones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    chat_id TEXT,
                    keyword TEXT
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_ofertas_timestamp ON ofertas(timestamp)')
            await conn.commit()

    def generar_id_oferta(self, oferta: Oferta) -> str:
        campos = [
            oferta.titulo,
            oferta.precio,
            oferta.link,
            oferta.imagen or '',
            oferta.precio_original or ''
        ]
        contenido = '|'.join([str(campo) for campo in campos if campo])
        return hashlib.sha256(contenido.encode()).hexdigest()



    async def guardar_oferta(self, oferta: Oferta) -> None:
        oferta_id = self.generar_id_oferta(oferta)
        async with aiosqlite.connect(self.database) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO ofertas (id, titulo, precio, precio_original, link, imagen, tag, cupon, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    oferta_id,
                    oferta.titulo,
                    oferta.precio,
                    oferta.precio_original,
                    oferta.link,
                    oferta.imagen,
                    oferta.tag,
                    oferta.cupon,
                    oferta.timestamp
                )
            )
            await conn.commit()

    async def limpiar_ofertas_antiguas(self, dias: int) -> int:
        tiempo_limite = int(time.time()) - (dias * 24 * 60 * 60)
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("DELETE FROM ofertas WHERE timestamp < ?", (tiempo_limite,))
            ofertas_eliminadas = cursor.rowcount
            await conn.commit()
        logging.info(f"Se eliminaron {ofertas_eliminadas} ofertas antiguas")
        return ofertas_eliminadas

    async def obtener_ids_recientes(self) -> set:
        # Obtiene todos los IDs de la base de datos (ya está limitada a 30 días por la limpieza)
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT id FROM ofertas")
            return {row[0] for row in await cursor.fetchall()}

    async def obtener_todas_las_ofertas(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT id, titulo, precio, link, timestamp FROM ofertas")
            return [
                {
                    'id': row[0],
                    'titulo': row[1],
                    'precio': row[2],
                    'link': row[3],
                    'timestamp': row[4]
                }
                for row in await cursor.fetchall()
            ]

    async def agregar_suscripcion(self, user_id: str, chat_id: str, keyword: str) -> bool:
        async with aiosqlite.connect(self.database) as conn:
            # Check if it already exists
            cursor = await conn.cursor()
            await cursor.execute(
                "SELECT id FROM suscripciones WHERE user_id = ? AND keyword = ?", 
                (user_id, keyword.lower())
            )
            if await cursor.fetchone():
                return False  # Ya está suscrito
            
            await conn.execute(
                "INSERT INTO suscripciones (user_id, chat_id, keyword) VALUES (?, ?, ?)",
                (user_id, chat_id, keyword.lower())
            )
            await conn.commit()
            return True

    async def eliminar_suscripcion(self, user_id: str, keyword: str) -> bool:
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute(
                "DELETE FROM suscripciones WHERE user_id = ? AND keyword = ?", 
                (user_id, keyword.lower())
            )
            deleted = cursor.rowcount > 0
            await conn.commit()
            return deleted

    async def obtener_suscripciones_por_usuario(self, user_id: str) -> List[str]:
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT keyword FROM suscripciones WHERE user_id = ?", (user_id,))
            return [row[0] for row in await cursor.fetchall()]

    async def obtener_todas_las_suscripciones(self) -> List[Dict[str, str]]:
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT user_id, chat_id, keyword FROM suscripciones")
            return [
                {'user_id': row[0], 'chat_id': row[1], 'keyword': row[2]}
                for row in await cursor.fetchall()
            ]
