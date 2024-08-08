from abc import ABC, abstractmethod

class BaseScraper(ABC):
    def __init__(self, url: str, tag: str):
        self.url = url
        self.tag = tag

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.strip().split())

    @abstractmethod
    def obtener_ofertas(self):
        pass
