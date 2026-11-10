import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class Oferta:
    titulo: str
    precio: str
    link: str
    tag: str
    timestamp: int
    precio_original: Optional[str] = None
    imagen: Optional[str] = None
    cupon: Optional[str] = None
    gancho_ia: Optional[str] = None
    info_cupon: Optional[str] = None
    emoji: str = "✨"

    @classmethod
    def create(cls, titulo: str, precio: str, link: str, tag: str, emoji: str = "✨", **kwargs):
        timestamp = kwargs.get('timestamp', int(time.time()))
        return cls(
            titulo=titulo,
            precio=precio,
            link=link,
            tag=tag,
            timestamp=timestamp,
            precio_original=kwargs.get('precio_original'),
            imagen=kwargs.get('imagen'),
            cupon=kwargs.get('cupon'),
            gancho_ia=kwargs.get('gancho_ia'),
            info_cupon=kwargs.get('info_cupon'),
            emoji=emoji
        )
