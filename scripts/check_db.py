"""Script manual para revisar la base de datos.

Uso: python scripts/check_db.py
"""

import asyncio
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from database.db_manager import DBManager  # noqa: E402


async def main() -> None:
    db = DBManager(os.getenv("DATABASE", "ofertas.db"))
    await db.init_db()
    print("Estadísticas:", await db.estadisticas())


if __name__ == "__main__":
    asyncio.run(main())
