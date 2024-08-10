import sqlite3
from typing import Dict, Any, List
from cachetools import TTLCache
import time
import logging
import hashlib

class DBManager:
    def __init__(self, database: str):
        self.database = database
        self.ofertas_cache = TTLCache(maxsize=1000, ttl=24*3600)
        self.init_db()

    def init_db(self) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS ofertas
                         (id TEXT PRIMARY KEY, titulo TEXT, precio TEXT, precio_original TEXT, link TEXT, imagen TEXT, tag TEXT, timestamp REAL, enviada INTEGER DEFAULT 0)''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_enviada ON ofertas(enviada)")
            conn.commit()

    def actualizar_estructura_db(self) -> None:
        try:
            with sqlite3.connect(self.database) as conn:
                c = conn.cursor()
                c.execute("PRAGMA table_info(ofertas)")
                columnas = [col[1] for col in c.fetchall()]
                if 'imagen' not in columnas:
                    c.execute("ALTER TABLE ofertas ADD COLUMN imagen TEXT")
                if 'tag' not in columnas:
                    c.execute("ALTER TABLE ofertas ADD COLUMN tag TEXT")
                if 'enviada' not in columnas:
                    c.execute("ALTER TABLE ofertas ADD COLUMN enviada INTEGER DEFAULT 0")
                c.execute("CREATE INDEX IF NOT EXISTS idx_enviada ON ofertas(enviada)")
                conn.commit()
            logging.info("Estructura de la base de datos actualizada")
        except sqlite3.Error as e:
            logging.error(f"Error al actualizar la estructura de la base de datos: {e}")

    def cargar_ofertas_enviadas(self) -> set:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM ofertas WHERE enviada = 1")
            return set(row[0] for row in c.fetchall())

    def guardar_oferta(self, oferta: Dict[str, Any]) -> None:
        timestamp = oferta.get('timestamp', time.time())
        if not isinstance(timestamp, (int, float)):
            timestamp = time.time()
            logging.warning(f"Timestamp inválido para la oferta {oferta['id']}: {oferta.get('timestamp')}. Usando tiempo actual.")

        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO ofertas (id, titulo, precio, precio_original, link, imagen, tag, timestamp, enviada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (oferta['id'], oferta['titulo'], oferta['precio'], oferta['precio_original'], oferta['link'], oferta['imagen'], oferta['tag'], timestamp, 0))
            conn.commit()
        
        oferta['timestamp'] = timestamp
        oferta['enviada'] = False
        self.ofertas_cache[oferta['id']] = oferta

    def marcar_oferta_como_enviada(self, oferta: Dict[str, Any]) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("UPDATE ofertas SET enviada = 1 WHERE id = ?", (oferta['id'],))
            conn.commit()
        
        oferta['enviada'] = True
        self.ofertas_cache[oferta['id']] = oferta

    def filtrar_ofertas_no_enviadas(self, ofertas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ofertas_enviadas = self.cargar_ofertas_enviadas()
        nuevas_ofertas = []
        for oferta in ofertas:
            oferta_id = self.generar_id_oferta(oferta['titulo'], oferta['precio'], oferta['link'])
            if oferta_id not in ofertas_enviadas:
                oferta['id'] = oferta_id
                nuevas_ofertas.append(oferta)
            else:
                logging.debug(f"Oferta ignorada (ya enviada): {oferta['titulo']}")
        return nuevas_ofertas

    def generar_id_oferta(self, titulo: str, precio: str, link: str) -> str:
        # Usar solo una parte del link para evitar variaciones menores
        link_parts = link.split('?')[0]  # Eliminar parámetros de la URL
        return hashlib.md5(f"{titulo}|{precio}|{link_parts}".encode()).hexdigest()

    def limpiar_ofertas_antiguas(self) -> int:
        tiempo_limite = time.time() - 30 * 24 * 3600  # 30 días
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM ofertas WHERE timestamp < ?", (tiempo_limite,))
            ofertas_eliminadas = c.rowcount
            conn.commit()
        return ofertas_eliminadas

    def actualizar_timestamp(self, oferta_id: str, nuevo_timestamp: float) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("UPDATE ofertas SET timestamp = ? WHERE id = ?", (nuevo_timestamp, oferta_id))
            conn.commit()

    def corregir_timestamps(self) -> None:
        tiempo_actual = time.time()
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("SELECT id, timestamp FROM ofertas")
            filas = c.fetchall()
            correcciones = 0
            for fila in filas:
                oferta_id, timestamp = fila
                if timestamp is None or not isinstance(timestamp, (int, float)):
                    self.actualizar_timestamp(oferta_id, tiempo_actual)
                    correcciones += 1
            conn.commit()
        if correcciones > 0:
            logging.info(f"Se corrigieron {correcciones} timestamps inválidos en la base de datos")
