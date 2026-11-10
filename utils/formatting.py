"""Formateo seguro de mensajes de Telegram (HTML escapado y truncado)."""

import html
import re
from typing import Optional
from urllib.parse import urlsplit

from utils.models import Oferta

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
HOOK_LIMIT = 180


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def _corta(value: object, limit: int) -> str:
    """Recorta texto plano antes de escaparlo (evita cortar entidades HTML)."""
    texto = " ".join(str(value or "").split())
    if len(texto) <= limit:
        return texto
    if limit <= 1:
        return ""
    return texto[: limit - 1].rstrip() + "…"


def _url_segura(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    candidata = str(url).strip()
    try:
        partes = urlsplit(candidata)
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return None
    return html.escape(candidata, quote=True)


def render_offer_text(
    oferta: Oferta,
    limit: int = CAPTION_LIMIT,
    include_hook: bool = True,
) -> str:
    """
    Construye el texto HTML de una oferta respetando el límite de Telegram.

    Escapa todos los campos que provienen del scraping. Si el mensaje no cabe,
    recorta primero el título, después la información extra y por último el
    gancho, de modo que el HTML siga siendo válido.
    """
    titulo = oferta.titulo or "Oferta"
    precio = oferta.precio or "No disponible"
    original = oferta.precio_original
    info = oferta.info_cupon
    cupon = oferta.cupon
    gancho = oferta.gancho_ia if include_hook else None
    emoji = oferta.emoji or "✨"
    tag = oferta.tag or ""
    link = _url_segura(oferta.link)

    def construir(
        titulo_max: int,
        info_max: int,
        gancho_max: int,
        con_info: bool,
        con_gancho: bool,
    ) -> str:
        lineas: list[str] = []
        if con_gancho and gancho:
            lineas.append(f"<i>{_esc(_corta(gancho, gancho_max))}</i>")
            lineas.append("")
        lineas.append(f"{emoji} <b>{_esc(_corta(titulo, titulo_max))}</b>")
        lineas.append("")
        lineas.append(f"💰 <b>Precio:</b> {_esc(_corta(precio, 60))}")
        if original and str(original).strip().lower() not in (
            "",
            "no disponible",
            "none",
        ):
            lineas.append(f"📉 <b>Antes:</b> <s>{_esc(_corta(original, 60))}</s>")
        if con_info and info:
            lineas.append(f"🎟️ <b>Info Extra:</b> {_esc(_corta(info, info_max))}")
        if cupon:
            lineas.append(f"✂️ <b>Cupón:</b> <code>{_esc(_corta(cupon, 40))}</code>")
        if link:
            lineas.append("")
            lineas.append(f'🔗 <a href="{link}">Ir a la Oferta</a>')
        if tag:
            lineas.append("")
            lineas.append(f"🏷️ {_esc(_corta(tag, 40))}")
        return "\n".join(lineas)

    variantes = [
        (200, 240, HOOK_LIMIT, True, True),
        (150, 180, 140, True, True),
        (110, 100, 120, True, True),
        (90, 0, 90, False, True),
        (70, 0, 0, False, False),
        (45, 0, 0, False, False),
    ]
    for titulo_max, info_max, gancho_max, con_info, con_gancho in variantes:
        texto = construir(titulo_max, info_max, gancho_max, con_info, con_gancho)
        if len(texto) <= limit:
            return texto

    # Último recurso: título corto y sin adornos.
    texto = f"{emoji} <b>{_esc(_corta(titulo, 60))}</b>"
    if len(texto) <= limit:
        return texto
    return _esc(_corta(titulo, max(10, limit - 4)))


def texto_plano(html_texto: str) -> str:
    """Convierte el HTML generado a texto plano (respaldo sin parse_mode)."""
    sin_etiquetas = re.sub(r"<[^>]+>", "", html_texto or "")
    return html.unescape(sin_etiquetas).strip()
