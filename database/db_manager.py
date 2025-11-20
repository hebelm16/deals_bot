import aiosqlite
import hashlib
import time
import logging
from typing import Dict, Any, List

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
            await conn.commit()

    def generar_id_oferta(self, oferta: Dict[str, Any]) -> str:
        campos = [
            oferta['titulo'],
            oferta['precio'],
            oferta['link'],
            oferta.get('imagen', ''),
            oferta.get('precio_original', '')
        ]
        contenido = '|'.join([str(campo) for campo in campos if campo])
        return hashlib.sha256(contenido.encode()).hexdigest()



    async def guardar_oferta(self, oferta: Dict[str, Any]) -> None:
        oferta_id = self.generar_id_oferta(oferta)
        async with aiosqlite.connect(self.database) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO ofertas (id, titulo, precio, precio_original, link, imagen, tag, cupon, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    oferta_id,
                    oferta['titulo'],
                    oferta['precio'],
                    oferta.get('precio_original'),
                    oferta['link'],
                    oferta.get('imagen'),
                    oferta['tag'],
                    oferta.get('cupon'),
                    int(time.time())
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
        # Obtiene IDs de las últimas 48 horas para una verificación rápida en memoria
        tiempo_limite = int(time.time()) - (2 * 24 * 60 * 60)
        async with aiosqlite.connect(self.database) as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT id FROM ofertas WHERE timestamp >= ?", (tiempo_limite,))
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
