import sqlite3
from typing import Dict, Any
from cachetools import TTLCache
import time
import logging

class DBManager:
    def __init__(self, database: str):
        self.database = database
        self.ofertas_cache = TTLCache(maxsize=1000, ttl=24*3600)
        self.init_db()

    def init_db(self) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS ofertas
                         (id TEXT PRIMARY KEY, titulo TEXT, precio TEXT, precio_original TEXT, link TEXT, imagen TEXT, tag TEXT, timestamp REAL)''')
            conn.commit()

    def cargar_ofertas_enviadas(self) -> Dict[str, Any]:
        if self.ofertas_cache:
            return self.ofertas_cache
        
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM ofertas")
            filas = c.fetchall()
        
        ofertas = {}
        for fila in filas:
            try:
                oferta_id, titulo, precio, precio_original, link, imagen, tag, timestamp = fila
                
                try:
                    timestamp = float(timestamp)
                except (ValueError, TypeError):
                    logging.warning(f"Timestamp inválido para la oferta {oferta_id}: {timestamp}. Usando tiempo actual.")
                    timestamp = time.time()
                    self.corregir_timestamp(oferta_id, timestamp)
                
                ofertas[oferta_id] = {
                    'titulo': titulo,
                    'precio': precio,
                    'precio_original': precio_original,
                    'link': link,
                    'imagen': imagen,
                    'tag': tag,
                    'timestamp': timestamp
                }
            except Exception as e:
                logging.error(f"Error al procesar fila de la base de datos: {e}. Fila: {fila}")
        
        self.ofertas_cache.update(ofertas)
        return ofertas

    def guardar_oferta(self, oferta: Dict[str, Any]) -> None:
        try:
            timestamp = oferta.get('timestamp')
            if timestamp is None or not isinstance(timestamp, (int, float)):
                logging.warning(f"Timestamp inválido o ausente para la oferta {oferta['id']}: {timestamp}. Usando tiempo actual.")
                timestamp = time.time()
            else:
                timestamp = float(timestamp)
        except Exception as e:
            logging.error(f"Error al procesar timestamp para la oferta {oferta['id']}: {e}")
            timestamp = time.time()

        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO ofertas (id, titulo, precio, precio_original, link, imagen, tag, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (oferta['id'], oferta['titulo'], oferta['precio'], oferta['precio_original'], oferta['link'], oferta['imagen'], oferta['tag'], timestamp))
            conn.commit()
        
        oferta['timestamp'] = timestamp
        self.ofertas_cache[oferta['id']] = oferta

    def limpiar_ofertas_antiguas(self) -> None:
        tiempo_limite = time.time() - 7 * 24 * 3600  # 7 días
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM ofertas WHERE timestamp < ?", (tiempo_limite,))
            conn.commit()

    def actualizar_estructura_db(self) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("PRAGMA table_info(ofertas)")
            columnas = [col[1] for col in c.fetchall()]
            if 'imagen' not in columnas:
                c.execute("ALTER TABLE ofertas ADD COLUMN imagen TEXT")
            if 'tag' not in columnas:
                c.execute("ALTER TABLE ofertas ADD COLUMN tag TEXT")
            conn.commit()

        logging.info("Estructura de la base de datos actualizada")

    def corregir_timestamps(self) -> None:
        tiempo_actual = time.time()
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("SELECT id, timestamp FROM ofertas")
            filas = c.fetchall()
            for fila in filas:
                oferta_id, timestamp = fila
                try:
                    float(timestamp)
                except (ValueError, TypeError):
                    logging.warning(f"Corrigiendo timestamp inválido para la oferta {oferta_id}: {timestamp}")
                    c.execute("UPDATE ofertas SET timestamp = ? WHERE id = ?", (tiempo_actual, oferta_id))
            conn.commit()
        logging.info("Timestamps corregidos en la base de datos")

    def corregir_timestamp(self, oferta_id: str, nuevo_timestamp: float) -> None:
        with sqlite3.connect(self.database) as conn:
            c = conn.cursor()
            c.execute("UPDATE ofertas SET timestamp = ? WHERE id = ?", (nuevo_timestamp, oferta_id))
            conn.commit()
        logging.info(f"Timestamp corregido para la oferta {oferta_id}")
