"""Servidor HTTP mínimo de salud para Railway (opcional)."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def start_health_server(
    port: int, snapshot: Callable[[], Dict[str, Any]]
) -> ThreadingHTTPServer:
    """Arranca un servidor HTTP interno que expone /health en un hilo."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - API de http.server
            if self.path not in ("/", "/health"):
                self.send_response(404)
                self.end_headers()
                return
            datos = snapshot()
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if datos.get("ok") else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *args):  # noqa: A003 - silenciar logs de acceso
            return

    servidor = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, name="health", daemon=True)
    hilo.start()
    logger.info("Servidor de salud escuchando en el puerto %s", port)
    return servidor
