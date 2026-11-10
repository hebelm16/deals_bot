import time

from database.db_manager import DBManager, canonicalizar_link
from utils.models import Oferta


def crear_oferta(link="https://example.com/producto", titulo="Producto", precio="$10", **kwargs):
    return Oferta.create(
        titulo=titulo,
        precio=precio,
        link=link,
        tag="#Test",
        **kwargs,
    )


async def test_dedupe_por_id_y_url_canonica(db):
    oferta = crear_oferta(link="https://www.example.com/p/1?utm_source=feed&a=1")
    oferta_id = await db.guardar_oferta(oferta)

    ids, canonicos = await db.obtener_indices_existentes()
    assert oferta_id in ids
    assert canonicalizar_link(oferta.link) in canonicos

    variante = crear_oferta(link="https://example.com/p/1?a=1&utm_medium=email")
    assert canonicalizar_link(variante.link) in canonicos
    assert oferta_id not in db.generar_ids_oferta(variante)


async def test_reconoce_ids_legados(db):
    oferta = crear_oferta(titulo="Antiguo", precio="$5", link="https://example.com/legacy")
    await db.guardar_oferta(oferta)
    ids, _ = await db.obtener_indices_existentes()

    legados = DBManager._ids_legado(
        oferta.titulo,
        oferta.precio,
        oferta.link,
        oferta.imagen,
        oferta.precio_original,
    )
    assert all(legado in ids for legado in legados)


async def test_ofertas_fallidas_y_pendientes_antiguas_se_reintentan(db):
    fallida = crear_oferta(link="https://example.com/fallida")
    fallida_id = await db.guardar_oferta(fallida, estado="pendiente")
    await db.marcar_oferta_fallida(fallida_id)
    ids, _ = await db.obtener_indices_existentes()
    assert fallida_id not in ids

    reciente = crear_oferta(link="https://example.com/reciente")
    reciente_id = await db.guardar_oferta(reciente, estado="pendiente")
    ids, _ = await db.obtener_indices_existentes()
    assert reciente_id in ids

    antigua = crear_oferta(
        link="https://example.com/antigua", timestamp=int(time.time()) - 7200
    )
    antigua_id = await db.guardar_oferta(antigua, estado="pendiente")
    ids, _ = await db.obtener_indices_existentes()
    assert antigua_id not in ids


async def test_suscripciones_unicas_y_borrado(db):
    assert await db.agregar_suscripcion("1", "10", "SSD") is True
    assert await db.agregar_suscripcion("1", "10", "ssd") is False
    assert await db.contar_suscripciones_usuario("1") == 1

    assert await db.agregar_suscripcion("1", "10", "") is False
    assert await db.eliminar_suscripcion("1", "SSD") is True
    assert await db.eliminar_suscripcion("1", "SSD") is False


async def test_borrado_de_suscripciones_por_chat(db):
    await db.agregar_suscripcion("1", "10", "ssd")
    await db.agregar_suscripcion("2", "10", "tv")
    await db.agregar_suscripcion("3", "30", "tv")

    assert await db.eliminar_suscripciones_por_chat("10") == 2
    assert await db.obtener_suscripciones_por_usuario("1") == []


async def test_ajustes_y_estadisticas(db):
    await db.set_ajuste("clave", "valor")
    assert await db.get_ajuste("clave") == "valor"
    assert await db.get_ajuste("inexistente", "default") == "default"

    oferta = crear_oferta()
    await db.guardar_oferta(oferta, estado="pendiente")
    stats = await db.estadisticas()
    assert stats["ofertas"] == 1
    assert stats["pendientes"] == 1


async def test_migracion_de_base_antigua(tmp_path):
    import sqlite3

    ruta = tmp_path / "antigua.db"
    conexion = sqlite3.connect(ruta)
    conexion.executescript(
        """
        CREATE TABLE ofertas (
            id TEXT PRIMARY KEY, titulo TEXT, precio TEXT, precio_original TEXT,
            link TEXT, imagen TEXT, tag TEXT, cupon TEXT, timestamp INTEGER
        );
        CREATE TABLE suscripciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, chat_id TEXT, keyword TEXT
        );
        INSERT INTO suscripciones (user_id, chat_id, keyword) VALUES ('1', '10', 'ssd');
        INSERT INTO suscripciones (user_id, chat_id, keyword) VALUES ('1', '10', 'ssd');
        INSERT INTO ofertas (id, titulo, precio, link, timestamp)
            VALUES ('viejo', 'Vieja', '$1', 'https://example.com/vieja?utm_source=x', 1);
        """
    )
    conexion.commit()
    conexion.close()

    manager = DBManager(str(ruta))
    await manager.init_db()

    ids, canonicos = await manager.obtener_indices_existentes()
    assert "viejo" in ids
    assert "https://example.com/vieja" in canonicos
    assert await manager.contar_suscripciones_usuario("1") == 1
    await manager.agregar_suscripcion("1", "10", "ssd")
    assert await manager.contar_suscripciones_usuario("1") == 1
