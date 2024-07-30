import psycopg2
from psycopg2.extras import DictCursor
import os
from typing import Dict, Any
from cachetools import TTLCache
import time
import logging

class DBManager:
    def __init__(self):
        self.database_url = os.environ['DATABASE_URL']
        self.ofertas_cache = TTLCache(maxsize=1000, ttl=24*3600)
        self.init_db()

    def get_connection(self):
        return psycopg2.connect(self.database_url, sslmode='require')

    def init_db(self) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('''CREATE TABLE IF NOT EXISTS ofertas
                               (id TEXT PRIMARY KEY, titulo TEXT, precio TEXT, precio_original TEXT, 
                                link TEXT, imagen TEXT, tag TEXT, timestamp DOUBLE PRECISION)''')
                conn.commit()

    def cargar_ofertas_enviadas(self) -> Dict[str, Any]:
        if self.ofertas_cache:
            return self.ofertas_cache
        
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT * FROM ofertas")
                filas = cur.fetchall()
        
        ofertas = {}
        for fila in filas:
            try:
                oferta = dict(fila)
                ofertas[oferta['id']] = oferta
            except Exception as e:
                logging.error(f"Error al procesar fila de la base de datos: {e}. Fila: {fila}")
        
        self.ofertas_cache.update(ofertas)
        return ofertas

    def guardar_oferta(self, oferta: Dict[str, Any]) -> None:
        try:
            timestamp = float(oferta.get('timestamp', time.time()))
        except ValueError:
            timestamp = time.time()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ofertas (id, titulo, precio, precio_original, link, imagen, tag, timestamp) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET 
                    titulo = EXCLUDED.titulo,
                    precio = EXCLUDED.precio,
                    precio_original = EXCLUDED.precio_original,
                    link = EXCLUDED.link,
                    imagen = EXCLUDED.imagen,
                    tag = EXCLUDED.tag,
                    timestamp = EXCLUDED.timestamp
                """, (oferta['id'], oferta['titulo'], oferta['precio'], oferta['precio_original'],
                      oferta['link'], oferta['imagen'], oferta['tag'], timestamp))
                conn.commit()
        
        oferta['timestamp'] = timestamp
        self.ofertas_cache[oferta['id']] = oferta

    def limpiar_ofertas_antiguas(self) -> None:
        tiempo_limite = time.time() - 7 * 24 * 3600  # 7 días
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ofertas WHERE timestamp < %s", (tiempo_limite,))
                conn.commit()

    def filtrar_nuevas_ofertas(self, ofertas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        nuevas_ofertas = []
        ofertas_enviadas = self.cargar_ofertas_enviadas()
    
        for oferta in ofertas:
            if oferta['id'] not in ofertas_enviadas:
                nuevas_ofertas.append(oferta)
    
        return nuevas_ofertas

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