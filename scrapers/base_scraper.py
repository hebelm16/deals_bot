from abc import ABC, abstractmethod
from typing import List
from utils.models import Oferta

class BaseScraper(ABC):
    emoji = "✨"

    def __init__(self, name: str, url: str, tag: str):
        self.name = name
        self.url = url
        self.tag = tag

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.strip().split())

    @abstractmethod
    async def obtener_ofertas(self) -> List[Oferta]:
        pass
