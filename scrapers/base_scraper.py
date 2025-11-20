from abc import ABC, abstractmethod

class BaseScraper(ABC):
    def __init__(self, name: str, url: str, tag: str):
        self.name = name
        self.url = url
        self.tag = tag

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.strip().split())

    @abstractmethod
    async def obtener_ofertas(self):
        pass
