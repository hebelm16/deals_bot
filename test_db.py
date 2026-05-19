import asyncio
from database.db_manager import DBManager

async def main():
    db = DBManager('ofertas.db')
    await db.init_db()
    s = await db.obtener_suscripciones_por_usuario('123')
    print(s)

asyncio.run(main())
