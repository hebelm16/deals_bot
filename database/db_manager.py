import sqlite3
import hashlib
import time
import logging
from typing import Dict, Any, List

class DBManager:
    def __init__(self, database: str):
        self.database = database
        self.init_db()

    def init_db(self) -> None:
        with sqlite3.connect(self.database) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS ofertas (
                    id TEXT PRIMARY KEY,
                    titulo TEXT,
                    precio TEXT,
                    link TEXT,
                    timestamp INTEGER
                )
            ''')

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

    def es_oferta_repetida(self, oferta: Dict[str, Any]) -> bool:
        oferta_id = self.generar_id_oferta(oferta)
        with sqlite3.connect(self.database) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ofertas WHERE id = ?", (oferta_id,))
            return cursor.fetchone() is not None

    def guardar_oferta(self, oferta: Dict[str, Any]) -> None:
        oferta_id = self.generar_id_oferta(oferta)
        with sqlite3.connect(self.database) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ofertas (id, titulo, precio, link, timestamp) VALUES (?, ?, ?, ?, ?)",
                (oferta_id, oferta['titulo'], oferta['precio'], oferta['link'], int(time.time()))
            )

    def limpiar_ofertas_antiguas(self, dias: int = 30) -> int:
        tiempo_limite = int(time.time()) - (dias * 24 * 60 * 60)
        with sqlite3.connect(self.database) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ofertas WHERE timestamp < ?", (tiempo_limite,))
            ofertas_eliminadas = cursor.rowcount
            conn.commit()
        logging.info(f"Se eliminaron {ofertas_eliminadas} ofertas antiguas")
        return ofertas_eliminadas

    def obtener_todas_las_ofertas(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.database) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, titulo, precio, link, timestamp FROM ofertas")
            return [
                {
                    'id': row[0],
                    'titulo': row[1],
                    'precio': row[2],
                    'link': row[3],
                    'timestamp': row[4]
                }
                for row in cursor.fetchall()
            ]
