"""Orquestador del bot de ofertas."""

import asyncio
import hashlib
import html
import importlib
import inspect
import logging
import os
import random
import signal
import time
from io import BytesIO
from typing import Any, Dict, List, Optional

from filelock import FileLock
from filelock import Timeout as FileLockTimeout
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.error import (
    BadRequest,
    Conflict,
    Forbidden,
    NetworkError,
    RetryAfter,
    TimedOut,
)
from telegram.ext import Application

from bot.handlers import setup_handlers
from config import Config
from database.db_manager import DBManager, canonicalizar_link
from utils.ai_helper import gancho_respaldo, generar_gancho, registrar_error_ia
from utils.formatting import (
    CAPTION_LIMIT,
    MESSAGE_LIMIT,
    render_offer_text,
    texto_plano,
)
from utils.health_server import start_health_server
from utils.images import ImagenDescargada, resolver_imagen
from utils.keywords import compilar_patron
from utils.models import Oferta

logger = logging.getLogger("OfertasBot")


class OfertasBot:
    def __init__(
        self,
        config: Optional[Config] = None,
        db_manager: Optional[DBManager] = None,
        scrapers: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or Config()
        self.db_manager = db_manager or DBManager(self.config.DATABASE)
        self.scrapers = scrapers if scrapers is not None else self.init_scrapers()
        self.application: Optional[Application] = None
        self.bot = None
        self.lock = asyncio.Lock()
        carpeta_db = os.path.dirname(os.path.abspath(self.config.DATABASE))
        self.lock_file = os.path.join(carpeta_db, ".ofertasbot.lock")
        self.stop_event = asyncio.Event()
        self._apagado = False
        self._health_server = None
        self._inicio = time.time()
        self._salud: Dict[str, Any] = {
            "last_cycle_ts": None,
            "last_cycle_ok": False,
            "last_error": None,
        }
        self._ultimos_errores_scrapers: Dict[str, str] = {}
        self._imagenes_cache: Dict[str, ImagenDescargada] = {}
        self._placeholder_bytes: Optional[bytes] = None
        self._imagen_stats: Dict[str, int] = {
            "url": 0,
            "descargada": 0,
            "placeholder": 0,
            "texto": 0,
        }

    # ------------------------------------------------------------------ arranque
    def init_scrapers(self) -> Dict[str, Any]:
        scrapers: Dict[str, Any] = {}
        for scraper_config in self.config.SCRAPERS:
            try:
                modulo = importlib.import_module(scraper_config["module"])
                clase = getattr(modulo, scraper_config["class"])
                instancia = clase(
                    name=scraper_config["name"],
                    url=scraper_config["url"],
                    tag=scraper_config["tag"],
                )
                scrapers[scraper_config["name"]] = {
                    "instance": instancia,
                    "enabled": bool(scraper_config.get("enabled", True)),
                }
                logger.info("Scraper '%s' cargado", scraper_config["name"])
            except (ImportError, AttributeError, TypeError) as exc:
                logger.error(
                    "No se pudo cargar el scraper '%s': %s",
                    scraper_config.get("name"),
                    exc,
                    exc_info=True,
                )
        return scrapers

    async def _cargar_estado_fuentes(self) -> None:
        for nombre, info in self.scrapers.items():
            guardado = await self.db_manager.get_ajuste(f"fuente.{nombre}.enabled")
            if guardado is not None:
                info["enabled"] = guardado == "1"

    async def _guardar_estado_fuente(self, nombre: str, habilitada: bool) -> None:
        if nombre not in self.scrapers:
            return
        self.scrapers[nombre]["enabled"] = habilitada
        await self.db_manager.set_ajuste(
            f"fuente.{nombre}.enabled", "1" if habilitada else "0"
        )

    async def run(self) -> None:
        lock = FileLock(self.lock_file, timeout=0)
        try:
            with lock:
                logger.info("Bloqueo adquirido en %s", self.lock_file)
                await self.db_manager.init_db()
                await self._cargar_estado_fuentes()
                await self._iniciar_aplicacion()
                await self._iniciar_red()
                self._instalar_senales()
                self._iniciar_health_server()

                logger.info(
                    "Ciclo de scraping cada %ss (primera ejecución inmediata)",
                    self.config.LOOP_INTERVAL_SECONDS,
                )
                self.application.job_queue.run_repeating(
                    self.scheduled_check_ofertas,
                    interval=self.config.LOOP_INTERVAL_SECONDS,
                    first=1,
                    name="ciclo_ofertas",
                )
                self.application.job_queue.run_repeating(
                    self._tarea_heartbeat,
                    interval=self.config.HEARTBEAT_INTERVAL_SECONDS,
                    first=30,
                    name="heartbeat",
                )
                await self.stop_event.wait()
        except FileLockTimeout:
            logger.error(
                "Otra instancia del bot ya está en ejecución (bloqueo %s). Saliendo.",
                self.lock_file,
            )
        except asyncio.CancelledError:
            logger.info("Ejecución cancelada; cerrando ordenadamente")
        except Exception as exc:  # noqa: BLE001 - se registra y se intenta cerrar
            logger.critical("Error fatal al iniciar el bot: %s", exc, exc_info=True)
        finally:
            await self._apagar()

    async def _iniciar_aplicacion(self) -> None:
        self.application = Application.builder().token(self.config.TOKEN).build()
        if self.application.job_queue is None:
            raise RuntimeError(
                "Falta el extra job-queue de python-telegram-bot. "
                "Instala 'python-telegram-bot[job-queue]'."
            )
        self.bot = self.application.bot
        self.application.bot_data["bot"] = self
        setup_handlers(self.application, self)
        await self.application.initialize()
        await self.application.start()

        comandos = [
            BotCommand("start", "Mensaje de bienvenida y ayuda"),
            BotCommand("ayuda", "Muestra los comandos disponibles"),
            BotCommand("alerta", "Crea una alerta para una palabra clave"),
            BotCommand("mis_alertas", "Mira tus palabras suscritas"),
            BotCommand("borrar_alerta", "Elimina una alerta existente"),
            BotCommand("estado", "Estado de fuentes y ciclo (Admin)"),
            BotCommand("diagnostico", "Diagnóstico técnico (Admin)"),
            BotCommand("test_ia", "Prueba la conexión con la IA (Admin)"),
        ]
        try:
            await self.bot.set_my_commands(comandos)
        except Exception as exc:  # noqa: BLE001
            logger.error("No se pudieron configurar los comandos: %s", exc)

    async def _iniciar_red(self) -> None:
        if self.config.USE_WEBHOOKS and self.config.WEBHOOK_URL:
            secreto = self.config.WEBHOOK_SECRET or hashlib.sha256(
                self.config.TOKEN.encode()
            ).hexdigest()[:32]
            url_webhook = f"{self.config.WEBHOOK_URL}/webhook"
            logger.info("Iniciando en modo webhook en el puerto %s", self.config.PORT)
            try:
                await self.application.updater.start_webhook(
                    listen="0.0.0.0",
                    port=self.config.PORT,
                    url_path="webhook",
                    webhook_url=url_webhook,
                    secret_token=secreto,
                    drop_pending_updates=False,
                )
                return
            except Exception as exc:  # noqa: BLE001 - se intenta polling como respaldo
                logger.error(
                    "No se pudo iniciar el webhook (%s). Se usará polling.", exc
                )
                try:
                    if self.application.updater.running:
                        await self.application.updater.stop()
                except Exception:  # noqa: BLE001
                    pass

        logger.info("Iniciando en modo polling")
        await self.bot.delete_webhook(drop_pending_updates=False)
        await self.application.updater.start_polling(
            drop_pending_updates=False,
            error_callback=self._telegram_error_callback,
            timeout=self.config.TELEGRAM_POLLING_TIMEOUT,
            poll_interval=self.config.TELEGRAM_POLLING_INTERVAL,
        )

    def _instalar_senales(self) -> None:
        loop = asyncio.get_running_loop()

        def solicitar_parada(*_args) -> None:
            if not self.stop_event.is_set():
                logger.info("Señal de parada recibida; cerrando el bot")
                self.stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, solicitar_parada)
            except (NotImplementedError, RuntimeError):
                try:
                    signal.signal(sig, lambda *_: loop.call_soon_threadsafe(solicitar_parada))
                except ValueError:
                    logger.debug("No se pudo instalar el handler de %s", sig)

    def _iniciar_health_server(self) -> None:
        if self.config.HEALTH_PORT <= 0:
            return
        try:
            self._health_server = start_health_server(
                self.config.HEALTH_PORT, self.health_snapshot
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("No se pudo arrancar el servidor de salud: %s", exc)

    async def _apagar(self) -> None:
        if self._apagado:
            return
        self._apagado = True
        if self._health_server is not None:
            try:
                self._health_server.shutdown()
                self._health_server.server_close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error al cerrar el servidor de salud: %s", exc)
        if self.application is not None:
            try:
                await self.application.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error al detener la aplicación: %s", exc)
            try:
                await self.application.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error al apagar la aplicación: %s", exc)
        logger.info("El bot se ha detenido")

    async def stop(self) -> None:
        self.stop_event.set()

    def health_snapshot(self) -> Dict[str, Any]:
        ultimo = self._salud.get("last_cycle_ts")
        edad = int(time.time() - ultimo) if ultimo else None
        en_arranque = ultimo is None and (time.time() - self._inicio) < 900
        ok = bool(self._salud.get("last_cycle_ok")) and edad is not None and (
            edad < self.config.HEARTBEAT_MAX_HOURS * 3600
        )
        return {
            "ok": ok or en_arranque,
            "last_cycle_ts": ultimo,
            "age_seconds": edad,
            "last_error": self._salud.get("last_error"),
            "sources": {
                nombre: bool(info["enabled"]) for nombre, info in self.scrapers.items()
            },
        }

    # ------------------------------------------------------------------ scraping
    async def _scrape_all_sources(self) -> Dict[str, List[Oferta]]:
        habilitados = [
            (nombre, info["instance"])
            for nombre, info in self.scrapers.items()
            if info["enabled"]
        ]
        if not habilitados:
            logger.warning("No hay scrapers habilitados")
            return {}

        tareas: Dict[str, asyncio.Future] = {}
        for nombre, scraper in habilitados:
            metodo = scraper.obtener_ofertas
            corrutina = (
                metodo() if inspect.iscoroutinefunction(metodo) else asyncio.to_thread(metodo)
            )
            tareas[nombre] = asyncio.wait_for(
                corrutina, timeout=self.config.SCRAPER_TIMEOUT_SECONDS
            )

        resultados = await asyncio.gather(*tareas.values(), return_exceptions=True)
        ofertas: Dict[str, List[Oferta]] = {}
        self._ultimos_errores_scrapers = {}

        for (nombre, _), resultado in zip(tareas.items(), resultados, strict=True):
            if isinstance(resultado, Exception):
                self._ultimos_errores_scrapers[nombre] = str(resultado)[:250]
                logger.error("Error en scraper '%s': %s", nombre, resultado)
                continue
            if not resultado:
                self._ultimos_errores_scrapers[nombre] = "0 ofertas"
                logger.warning("Scraper '%s' no devolvió ofertas", nombre)
                continue
            ofertas[nombre] = resultado
            logger.info("Scraper '%s': %s ofertas", nombre, len(resultado))
        return ofertas

    async def _filter_new_deals(
        self, all_deals: Dict[str, List[Oferta]]
    ) -> Dict[str, List[Oferta]]:
        ids_conocidos, canonicos = await self.db_manager.obtener_indices_existentes()
        logger.info(
            "Deduplicación contra %s IDs y %s URLs canónicas",
            len(ids_conocidos),
            len(canonicos),
        )

        def es_nueva(oferta: Oferta) -> bool:
            if any(
                oferta_id in ids_conocidos
                for oferta_id in self.db_manager.generar_ids_oferta(oferta)
            ):
                return False
            return canonicalizar_link(oferta.link) not in canonicos

        return {
            nombre: [oferta for oferta in ofertas if es_nueva(oferta)]
            for nombre, ofertas in all_deals.items()
        }

    # ------------------------------------------------------------------ publicación
    def seleccionar_ofertas_equilibradas(
        self, *listas_de_ofertas: List[List[Oferta]]
    ) -> List[Oferta]:
        listas_no_vacias = [lista for lista in listas_de_ofertas if lista]
        if not listas_no_vacias:
            return []

        max_ofertas = self.config.MAX_OFERTAS_POR_EJECUCION
        iteradores = [iter(lista) for lista in listas_no_vacias]
        seleccionadas: List[Oferta] = []
        vistos: set[tuple[str, str]] = set()

        while len(seleccionadas) < max_ofertas:
            agregadas = 0
            for iterador in iteradores:
                try:
                    oferta = next(iterador)
                except StopIteration:
                    continue
                clave = (oferta.titulo or "", oferta.link or "")
                if clave in vistos:
                    continue
                vistos.add(clave)
                seleccionadas.append(oferta)
                agregadas += 1
                if len(seleccionadas) == max_ofertas:
                    break
            if agregadas == 0:
                break

        random.shuffle(seleccionadas)
        return seleccionadas

    async def _generar_gancho(self, oferta: Oferta) -> Optional[str]:
        try:
            gancho = await asyncio.wait_for(
                generar_gancho(
                    oferta.titulo,
                    oferta.precio,
                    oferta.precio_original,
                    requerido=self.config.AI_HOOK_REQUIRED,
                ),
                timeout=self.config.AI_HOOK_TIMEOUT_SECONDS,
            )
            return gancho
        except asyncio.TimeoutError:
            registrar_error_ia("bot", "timeout del gancho")
            logger.warning("Timeout generando gancho para '%s'", oferta.titulo)
            return (
                None
                if self.config.AI_HOOK_REQUIRED
                else gancho_respaldo(
                    oferta.titulo, oferta.precio, oferta.precio_original
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error generando gancho: %s", exc)
            return (
                None
                if self.config.AI_HOOK_REQUIRED
                else gancho_respaldo(
                    oferta.titulo, oferta.precio, oferta.precio_original
                )
            )

    async def _process_new_deals(
        self,
        new_deals_by_source: Dict[str, List[Oferta]],
        deadline: Optional[float] = None,
    ) -> int:
        seleccionadas = self.seleccionar_ofertas_equilibradas(
            *[ofertas for ofertas in new_deals_by_source.values()]
        )
        logger.info("Ofertas seleccionadas para publicar: %s", len(seleccionadas))
        if not seleccionadas:
            return 0

        suscripciones = await self.db_manager.obtener_todas_las_suscripciones()
        patrones = []
        for suscripcion in suscripciones:
            try:
                patrones.append(
                    (suscripcion, compilar_patron(suscripcion["keyword"]))
                )
            except ValueError:
                logger.warning(
                    "Suscripción con palabra clave inválida ignorada: %r",
                    suscripcion["keyword"],
                )

        enviadas = 0
        for oferta in seleccionadas:
            if deadline is not None and time.monotonic() > deadline:
                logger.warning("Presupuesto del ciclo agotado; quedan ofertas sin publicar")
                break

            gancho = await self._generar_gancho(oferta)
            if not gancho and self.config.AI_HOOK_REQUIRED:
                logger.warning(
                    "Oferta omitida por falta de gancho IA (regla estricta): %s",
                    oferta.titulo,
                )
                continue
            oferta.gancho_ia = gancho

            try:
                oferta_id = await self.db_manager.guardar_oferta(
                    oferta, estado="pendiente"
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("No se pudo guardar la oferta antes de enviar: %s", exc)
                continue

            message_id = await self.enviar_oferta_con_reintento(oferta)
            if not message_id:
                await self.db_manager.marcar_oferta_fallida(oferta_id)
                logger.error("No se pudo enviar la oferta: %s", oferta.titulo)
                continue

            await self.db_manager.marcar_oferta_enviada(oferta_id, message_id)
            enviadas += 1
            logger.info("Oferta publicada: %s (%s)", oferta.titulo, oferta.tag)
            await self._enviar_alertas(oferta, patrones)
            await asyncio.sleep(max(1, self.config.SEND_OFFER_INTERVAL_SECONDS))
        return enviadas

    def _teclado(self, oferta: Oferta) -> Optional[InlineKeyboardMarkup]:
        link = (oferta.link or "").strip()
        if not link.startswith(("http://", "https://")):
            return None
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔗 Ver Oferta 🔗", url=link)]]
        )

    @staticmethod
    def _imagen_valida(oferta: Oferta) -> bool:
        imagen = (oferta.imagen or "").strip()
        return imagen.startswith(("http://", "https://"))

    async def _obtener_imagen(self, oferta: Oferta) -> Optional[ImagenDescargada]:
        """Descarga la imagen (y su og:image de respaldo) y la cachea por enlace."""
        if not self.config.DESCARGAR_IMAGENES:
            return None
        clave = oferta.link or oferta.imagen or ""
        if not clave:
            return None
        if clave in self._imagenes_cache:
            return self._imagenes_cache[clave]
        try:
            imagen = await resolver_imagen(
                oferta,
                max_bytes=self.config.IMAGE_MAX_BYTES,
                timeout=self.config.IMAGE_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error resolviendo imagen de %s: %s", oferta.link, exc)
            imagen = None
        if imagen:
            if len(self._imagenes_cache) >= 10:
                self._imagenes_cache.pop(next(iter(self._imagenes_cache)))
            self._imagenes_cache[clave] = imagen
        return imagen

    def _datos_placeholder(self) -> Optional[bytes]:
        """Carga (una vez) la imagen de respaldo para ofertas sin foto."""
        if self._placeholder_bytes is None:
            ruta = self.config.PLACEHOLDER_IMAGE
            try:
                with open(ruta, "rb") as archivo:
                    self._placeholder_bytes = archivo.read()
            except OSError as exc:
                logger.warning(
                    "No se pudo leer la imagen de respaldo %s: %s", ruta, exc
                )
                self._placeholder_bytes = b""
        return self._placeholder_bytes or None

    async def _enviar_foto_url(
        self,
        chat_id: str | int,
        url: str,
        caption: str,
        teclado: Optional[InlineKeyboardMarkup],
    ):
        for intento in (1, 2):
            try:
                return await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=url,
                    caption=caption if intento == 1 else texto_plano(caption),
                    reply_markup=teclado,
                    parse_mode="HTML" if intento == 1 else None,
                )
            except BadRequest as exc:
                logger.warning("Telegram rechazó la foto por URL (%s)", exc)
        return None

    async def _enviar_foto_bytes(
        self,
        chat_id: str | int,
        datos: bytes,
        nombre: str,
        caption: str,
        teclado: Optional[InlineKeyboardMarkup],
    ):
        for intento in (1, 2):
            try:
                return await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(BytesIO(datos), filename=nombre),
                    caption=caption if intento == 1 else texto_plano(caption),
                    reply_markup=teclado,
                    parse_mode="HTML" if intento == 1 else None,
                )
            except BadRequest as exc:
                logger.warning("Telegram rechazó la imagen subida (%s)", exc)
        return None

    async def _enviar_mensaje(
        self,
        chat_id: str | int,
        oferta: Oferta,
        caption: str,
        mensaje: str,
        teclado: Optional[InlineKeyboardMarkup],
        usar_foto: bool,
    ):
        if usar_foto and self._imagen_valida(oferta):
            enviado = await self._enviar_foto_url(
                chat_id, oferta.imagen, caption, teclado
            )
            if enviado:
                self._imagen_stats["url"] += 1
                return enviado

        imagen = await self._obtener_imagen(oferta)
        if imagen:
            enviado = await self._enviar_foto_bytes(
                chat_id, imagen.contenido, imagen.nombre, caption, teclado
            )
            if enviado:
                self._imagen_stats["descargada"] += 1
                return enviado

        if self.config.USAR_PLACEHOLDER:
            datos = self._datos_placeholder()
            if datos:
                enviado = await self._enviar_foto_bytes(
                    chat_id, datos, "oferta_sin_imagen.jpg", caption, teclado
                )
                if enviado:
                    self._imagen_stats["placeholder"] += 1
                    return enviado

        self._imagen_stats["texto"] += 1
        try:
            return await self.bot.send_message(
                chat_id=chat_id,
                text=mensaje,
                reply_markup=teclado,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except BadRequest as exc:
            logger.warning("HTML rechazado (%s); se envía como texto plano", exc)
            return await self.bot.send_message(
                chat_id=chat_id,
                text=texto_plano(mensaje),
                reply_markup=teclado,
                parse_mode=None,
                disable_web_page_preview=True,
            )

    async def enviar_oferta_con_reintento(self, oferta: Oferta) -> Optional[int]:
        caption = render_offer_text(oferta, limit=CAPTION_LIMIT)
        mensaje = render_offer_text(oferta, limit=MESSAGE_LIMIT)
        teclado = self._teclado(oferta)
        usar_foto = self._imagen_valida(oferta)

        for intento in range(max(1, self.config.SEND_OFFER_MAX_RETRIES)):
            try:
                enviado = await self._enviar_mensaje(
                    self.config.CHANNEL_ID,
                    oferta,
                    caption,
                    mensaje,
                    teclado,
                    usar_foto,
                )
                return enviado.message_id
            except RetryAfter as exc:
                espera = int(getattr(exc, "retry_after", 5)) + 1
                logger.warning("Límite de Telegram; esperando %ss", espera)
                await asyncio.sleep(espera)
            except (NetworkError, TimedOut, Conflict) as exc:
                logger.error(
                    "Error de red al enviar (intento %s/%s): %s",
                    intento + 1,
                    self.config.SEND_OFFER_MAX_RETRIES,
                    exc,
                )
                await asyncio.sleep(
                    self.config.SEND_OFFER_RETRY_SLEEP_SECONDS * (intento + 1)
                )
            except Forbidden as exc:
                logger.critical("El bot no tiene permiso en el canal: %s", exc)
                return None
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Error inesperado al enviar '%s': %s",
                    oferta.titulo,
                    exc,
                    exc_info=True,
                )
                return None
        return None

    async def _enviar_alertas(
        self, oferta: Oferta, patrones: List[tuple[Dict[str, str], Any]]
    ) -> None:
        if not patrones:
            return
        titulo = (oferta.titulo or "").lower()
        info = (oferta.info_cupon or "").lower()
        teclado = self._teclado(oferta)
        usar_foto = self._imagen_valida(oferta)

        for suscripcion, patron in patrones:
            if not (patron.search(titulo) or patron.search(info)):
                continue
            prefijo = (
                f"🔔 <b>Alerta: {html.escape(suscripcion['keyword'], quote=False)}</b>\n\n"
            )
            caption = prefijo + render_offer_text(
                oferta, limit=max(200, 1000 - len(prefijo))
            )
            mensaje = prefijo + render_offer_text(
                oferta, limit=max(300, 4000 - len(prefijo))
            )
            try:
                await self._enviar_mensaje(
                    suscripcion["chat_id"],
                    oferta,
                    caption,
                    mensaje,
                    teclado,
                    usar_foto,
                )
                logger.info(
                    "Alerta enviada a %s por '%s'",
                    suscripcion["chat_id"],
                    suscripcion["keyword"],
                )
            except Forbidden:
                eliminadas = await self.db_manager.eliminar_suscripciones_por_chat(
                    suscripcion["chat_id"]
                )
                logger.info(
                    "Usuario %s bloqueó el bot; %s suscripciones eliminadas",
                    suscripcion["chat_id"],
                    eliminadas,
                )
                continue
            except RetryAfter as exc:
                await asyncio.sleep(int(getattr(exc, "retry_after", 5)) + 1)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Error enviando alerta a %s: %s", suscripcion["chat_id"], exc
                )
            await asyncio.sleep(max(0.2, self.config.ALERT_SEND_INTERVAL_SECONDS))

    # ------------------------------------------------------------------ ciclo
    async def scheduled_check_ofertas(self, context=None) -> None:
        try:
            await asyncio.wait_for(
                self.check_ofertas(), timeout=self.config.CYCLE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error("El ciclo excedió el tiempo límite de %ss", self.config.CYCLE_TIMEOUT_SECONDS)
            await self._registrar_fallo_ciclo("timeout del ciclo")
        except (NetworkError, TimedOut) as exc:
            logger.warning("Error de red temporal en el ciclo: %s", exc)
            await self._registrar_fallo_ciclo(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.error("Error en el ciclo principal: %s", exc, exc_info=True)
            await self._registrar_fallo_ciclo(str(exc))

    async def _registrar_fallo_ciclo(self, detalle: str) -> None:
        self._salud["last_cycle_ok"] = False
        self._salud["last_error"] = detalle[:250]
        try:
            await self.db_manager.marcar_ciclo(False, detalle)
        except Exception as exc:  # noqa: BLE001
            logger.error("No se pudo registrar el fallo del ciclo: %s", exc)
        await self.enviar_notificacion_error(RuntimeError(detalle))

    async def check_ofertas(self) -> None:
        inicio = time.monotonic()
        deadline = inicio + max(30, self.config.CYCLE_TIMEOUT_SECONDS - 30)
        async with self.lock:
            try:
                scraped = await self._scrape_all_sources()
                nuevas = await self._filter_new_deals(scraped)
                enviadas = await self._process_new_deals(nuevas, deadline=deadline)
                limpiadas = await self.db_manager.limpiar_ofertas_antiguas(
                    dias=self.config.DIAS_LIMPIEZA_OFERTAS_ANTIGUAS
                )
            except Exception as exc:
                self._salud["last_cycle_ok"] = False
                self._salud["last_error"] = str(exc)[:250]
                raise

            total_nuevas = sum(len(ofertas) for ofertas in nuevas.values())
            detalle = (
                f"nuevas={total_nuevas} enviadas={enviadas} limpiadas={limpiadas}"
            )
            self._salud["last_cycle_ts"] = int(time.time())
            self._salud["last_cycle_ok"] = True
            self._salud["last_error"] = None
            await self.db_manager.marcar_ciclo(True, detalle)
            logger.info("Resumen del ciclo: %s", detalle)

    async def _tarea_heartbeat(self, context=None) -> None:
        try:
            ultimo_ok = await self.db_manager.get_ajuste("ultimo_ciclo_ok")
            if not ultimo_ok:
                return
            ahora = time.time()
            if ahora - int(ultimo_ok) <= self.config.HEARTBEAT_MAX_HOURS * 3600:
                return
            ultima_alerta = await self.db_manager.get_ajuste("ultima_alerta_heartbeat")
            if ultima_alerta and ahora - int(ultima_alerta) < self.config.HEARTBEAT_INTERVAL_SECONDS:
                return
            fecha = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ultimo_ok)))
            await self.enviar_mensaje_admin(
                "⚠️ <b>Bot sin ciclos exitosos</b>\n\n"
                f"Último ciclo correcto: <code>{fecha}</code>.\n"
                "Revisa Railway (logs, volumen y variables de entorno)."
            )
            await self.db_manager.set_ajuste(
                "ultima_alerta_heartbeat", str(int(ahora))
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Error en el heartbeat: %s", exc)

    # ------------------------------------------------------------------ avisos
    async def enviar_mensaje_admin(self, texto: str) -> None:
        if not self.config.USER_ID or not self.bot:
            logger.warning("No hay administrador configurado para enviar el aviso")
            return
        try:
            await self.bot.send_message(
                chat_id=self.config.USER_ID,
                text=texto[:MESSAGE_LIMIT],
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("No se pudo enviar el aviso al administrador: %s", exc)

    async def enviar_notificacion_error(self, error: Exception) -> None:
        detalle = html.escape(f"{type(error).__name__}: {error}"[:800], quote=False)
        await self.enviar_mensaje_admin(
            "🚨 <b>Error en el bot de ofertas</b>\n\n"
            f"<code>{detalle}</code>"
        )

    # ------------------------------------------------------------------ compatibilidad
    def formatear_mensaje_oferta(self, oferta: Oferta) -> Dict[str, Any]:
        return {
            "text": render_offer_text(oferta, limit=CAPTION_LIMIT),
            "reply_markup": self._teclado(oferta),
            "parse_mode": "HTML",
        }

    def _telegram_error_callback(self, error: Exception) -> None:
        if isinstance(error, RetryAfter):
            logger.warning(
                "Telegram pidió esperar %ss", getattr(error, "retry_after", "?")
            )
        elif isinstance(error, Conflict):
            logger.warning(
                "Conflicto de instancias: otra instancia está usando getUpdates"
            )
        elif isinstance(error, (NetworkError, TimedOut)):
            logger.warning("Error de red de Telegram: %s", error)
        else:
            logger.error("Error de Telegram: %s", error)
