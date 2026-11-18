"""Gestión del modo evento (Black Friday, Prime Day, Cyber Monday, etc.)."""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from database.db_manager import DBManager

logger = logging.getLogger(__name__)

CLAVE_ESTADO = "evento.estado"
CLAVE_CUOTA = "evento.cuota_hoy"
MAX_HORAS_EVENTO = 720


def formatear_hashtag(nombre: str) -> str:
    """Convierte 'black_friday' o 'prime-day' en '#BlackFriday' o '#PrimeDay'."""
    limpio = str(nombre or "").strip().lstrip("#")
    partes = [
        re.sub(r"[^\w]", "", parte)
        for parte in re.split(r"[\s_-]+", limpio)
        if parte
    ]
    partes = [parte for parte in partes if parte]
    if not partes:
        raise ValueError("El nombre del evento debe contener letras o números.")
    slug = "".join(parte[0].upper() + parte[1:] for parte in partes)
    return f"#{slug[:32]}"


def etiqueta_evento(nombre: str) -> str:
    """Etiqueta visible en las publicaciones durante un evento."""
    return f"🔥 {formatear_hashtag(nombre)}"


@dataclass
class EstadoEvento:
    activo: bool = False
    nombre: str = ""
    etiqueta: str = ""
    inicio_ts: float = 0.0
    fin_ts: float = 0.0
    fecha_hoy: str = ""
    ia_usadas_hoy: int = 0
    pub_usadas_hoy: int = 0


class GestorEvento:
    """Controla activación, expiración, frecuencia y topes diarios de un evento."""

    def __init__(self, db_manager: DBManager, config: Any):
        self.db_manager = db_manager
        self.config = config
        self.estado = EstadoEvento(fecha_hoy=self._hoy())

    @staticmethod
    def _hoy(ahora: Optional[float] = None) -> str:
        ts = time.time() if ahora is None else ahora
        return time.strftime("%Y-%m-%d", time.localtime(ts))

    def _asegurar_dia_actual(self, ahora: Optional[float] = None) -> None:
        hoy = self._hoy(ahora)
        if self.estado.fecha_hoy != hoy:
            self.estado.fecha_hoy = hoy
            self.estado.ia_usadas_hoy = 0
            self.estado.pub_usadas_hoy = 0

    def esta_activo(self, ahora: Optional[float] = None) -> bool:
        ts = time.time() if ahora is None else ahora
        return self.estado.activo and ts < self.estado.fin_ts

    def etiqueta(self, ahora: Optional[float] = None) -> Optional[str]:
        return self.estado.etiqueta if self.esta_activo(ahora) else None

    def aplicar_etiqueta(
        self, tag: Optional[str], ahora: Optional[float] = None
    ) -> str:
        base = (tag or "").strip()
        etiqueta = self.etiqueta(ahora)
        if not etiqueta:
            return base
        if etiqueta in base:
            return base
        return f"{base} {etiqueta}".strip() if base else etiqueta

    def intervalo_ciclo(self, ahora: Optional[float] = None) -> int:
        if self.esta_activo(ahora):
            return max(60, int(getattr(self.config, "EVENTO_INTERVAL_SECONDS", 900)))
        return max(60, int(getattr(self.config, "LOOP_INTERVAL_SECONDS", 7200)))

    def cupo_publicaciones_restante(self, ahora: Optional[float] = None) -> int:
        if not self.esta_activo(ahora):
            return int(getattr(self.config, "MAX_OFERTAS_POR_EJECUCION", 20))
        self._asegurar_dia_actual(ahora)
        max_dia = max(0, int(getattr(self.config, "EVENTO_MAX_OFERTAS_DIA", 100)))
        return max(0, max_dia - self.estado.pub_usadas_hoy)

    def max_ofertas_ciclo(self, ahora: Optional[float] = None) -> int:
        if not self.esta_activo(ahora):
            return int(getattr(self.config, "MAX_OFERTAS_POR_EJECUCION", 20))
        por_ciclo = max(
            1, int(getattr(self.config, "EVENTO_MAX_OFERTAS_POR_EJECUCION", 5))
        )
        return min(por_ciclo, self.cupo_publicaciones_restante(ahora))

    def puede_usar_ia(self, ahora: Optional[float] = None) -> bool:
        if not self.esta_activo(ahora):
            return True
        self._asegurar_dia_actual(ahora)
        max_ia = max(0, int(getattr(self.config, "EVENTO_MAX_IA_DIA", 350)))
        return self.estado.ia_usadas_hoy < max_ia

    async def registrar_llamada_ia(self, ahora: Optional[float] = None) -> None:
        if not self.esta_activo(ahora):
            return
        self._asegurar_dia_actual(ahora)
        self.estado.ia_usadas_hoy += 1
        await self._guardar_cuota()

    async def registrar_publicacion(self, ahora: Optional[float] = None) -> None:
        if not self.esta_activo(ahora):
            return
        self._asegurar_dia_actual(ahora)
        self.estado.pub_usadas_hoy += 1
        await self._guardar_cuota()

    async def activar(
        self, nombre: str, horas: int, ahora: Optional[float] = None
    ) -> EstadoEvento:
        if not isinstance(horas, int) or horas < 1 or horas > MAX_HORAS_EVENTO:
            raise ValueError(
                f"La duración debe estar entre 1 y {MAX_HORAS_EVENTO} horas."
            )
        etiqueta = etiqueta_evento(nombre)
        ts = time.time() if ahora is None else ahora
        self._asegurar_dia_actual(ts)
        self.estado.activo = True
        self.estado.nombre = str(nombre).strip()
        self.estado.etiqueta = etiqueta
        self.estado.inicio_ts = ts
        self.estado.fin_ts = ts + (horas * 3600)
        await self._guardar_estado()
        await self._guardar_cuota()
        return self.estado

    async def extender(
        self, horas: int, ahora: Optional[float] = None
    ) -> Optional[EstadoEvento]:
        if not isinstance(horas, int) or horas < 1 or horas > MAX_HORAS_EVENTO:
            raise ValueError(
                f"La extensión debe estar entre 1 y {MAX_HORAS_EVENTO} horas."
            )
        ts = time.time() if ahora is None else ahora
        if not self.esta_activo(ts):
            return None
        self.estado.fin_ts = min(
            ts + MAX_HORAS_EVENTO * 3600, self.estado.fin_ts + horas * 3600
        )
        await self._guardar_estado()
        return self.estado

    async def desactivar(self) -> Optional[str]:
        if not self.estado.activo:
            return None
        nombre = self.estado.nombre
        self.estado.activo = False
        self.estado.nombre = ""
        self.estado.etiqueta = ""
        self.estado.inicio_ts = 0.0
        self.estado.fin_ts = 0.0
        await self._guardar_estado()
        return nombre

    async def verificar_expiracion(
        self, ahora: Optional[float] = None
    ) -> Optional[str]:
        ts = time.time() if ahora is None else ahora
        if self.estado.activo and ts >= self.estado.fin_ts:
            return await self.desactivar()
        return None

    async def cargar(self, ahora: Optional[float] = None) -> Optional[str]:
        ts = time.time() if ahora is None else ahora
        hoy = self._hoy(ts)
        self.estado = EstadoEvento(fecha_hoy=hoy)

        cuota_raw = await self.db_manager.get_ajuste(CLAVE_CUOTA)
        if cuota_raw:
            try:
                cuota = json.loads(cuota_raw)
                if cuota.get("fecha") == hoy:
                    self.estado.ia_usadas_hoy = max(0, int(cuota.get("ia", 0)))
                    self.estado.pub_usadas_hoy = max(0, int(cuota.get("pub", 0)))
            except (ValueError, TypeError):
                logger.warning("Cuota diaria de evento corrupta; se reinicia")

        estado_raw = await self.db_manager.get_ajuste(CLAVE_ESTADO)
        if not estado_raw:
            return None

        try:
            if estado_raw.startswith("{"):
                datos = json.loads(estado_raw)
                activo = bool(datos.get("activo"))
                nombre = str(datos.get("nombre") or "").strip()
                inicio_ts = float(datos.get("inicio_ts") or 0.0)
                fin_ts = float(datos.get("fin_ts") or 0.0)
            elif "|" in estado_raw:
                # Compatibilidad con el formato anterior "nombre|fin_ts|contador".
                nombre, fin_str, contador_str = estado_raw.split("|", 2)
                activo = True
                inicio_ts = ts
                fin_ts = float(fin_str)
                if self.estado.ia_usadas_hoy == 0:
                    self.estado.ia_usadas_hoy = max(0, int(contador_str))
            else:
                return None
        except (ValueError, TypeError):
            logger.warning("Estado de evento corrupto en BD; se ignora")
            await self._guardar_estado()
            return None

        if not activo or not nombre:
            return None

        if ts >= fin_ts:
            await self._guardar_estado()
            return nombre

        try:
            etiqueta = etiqueta_evento(nombre)
        except ValueError:
            await self._guardar_estado()
            return None

        self.estado.activo = True
        self.estado.nombre = nombre
        self.estado.etiqueta = etiqueta
        self.estado.inicio_ts = inicio_ts
        self.estado.fin_ts = fin_ts
        return None

    def resumen(self, ahora: Optional[float] = None) -> dict[str, Any]:
        ts = time.time() if ahora is None else ahora
        self._asegurar_dia_actual(ts)
        activo = self.esta_activo(ts)
        restante_seg = max(0, int(self.estado.fin_ts - ts)) if activo else 0
        return {
            "activo": activo,
            "nombre": self.estado.nombre if activo else "",
            "etiqueta": self.estado.etiqueta if activo else "",
            "fin_ts": self.estado.fin_ts if activo else 0.0,
            "restante_segundos": restante_seg,
            "ia_usadas_hoy": self.estado.ia_usadas_hoy,
            "ia_max_dia": int(getattr(self.config, "EVENTO_MAX_IA_DIA", 350)),
            "pub_usadas_hoy": self.estado.pub_usadas_hoy,
            "pub_max_dia": int(getattr(self.config, "EVENTO_MAX_OFERTAS_DIA", 100)),
            "intervalo_segundos": self.intervalo_ciclo(ts),
            "max_por_ciclo": self.max_ofertas_ciclo(ts),
        }

    async def _guardar_estado(self) -> None:
        payload = json.dumps(
            {
                "activo": self.estado.activo,
                "nombre": self.estado.nombre,
                "inicio_ts": self.estado.inicio_ts,
                "fin_ts": self.estado.fin_ts,
            }
        )
        await self.db_manager.set_ajuste(CLAVE_ESTADO, payload)

    async def _guardar_cuota(self) -> None:
        payload = json.dumps(
            {
                "fecha": self.estado.fecha_hoy,
                "ia": self.estado.ia_usadas_hoy,
                "pub": self.estado.pub_usadas_hoy,
            }
        )
        try:
            await self.db_manager.set_ajuste(CLAVE_CUOTA, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo guardar la cuota diaria del evento: %s", exc)
