# Deals Bot

Bot de Telegram que recopila ofertas de varias fuentes, genera un gancho con IA
(opcional) y las publica en un canal. También envía alertas por mensaje directo
a los usuarios suscritos a palabras clave.

## Qué hace

- Rastrea Slickdeals (feed RSS), DealNews y DealsOfAmerica cada 2 horas.
- Deduplica por enlace canónico y por hash, incluyendo ofertas históricas.
- Puntúa las ofertas por descuento real, calidad de los datos y frescura, y
  elige las mejores manteniendo variedad entre fuentes.
- Genera un gancho con Gemini (rotación de claves y descubrimiento automático de
  modelos disponibles) y respaldo en Groq; si no hay IA, publica con una
  plantilla para no bloquear el canal.
- Publica con imagen y botón; si Telegram no puede descargar la imagen, el bot
  baja el fichero (o un candidato de la página) y lo sube directamente. Si no
  hay ninguna imagen disponible, usa `assets/oferta_sin_imagen.jpg` para que
  ninguna oferta salga sin foto.
- Escapa todo el HTML y recorta los mensajes a los límites de Telegram.
- Envía alertas por palabra clave y permite borrarlas o darse de baja.
- Guarda las ofertas como pendientes antes de enviarlas para evitar duplicados.
- Registra el último ciclo correcto y avisa al administrador si el bot se queda
  sin publicar.

## Requisitos

- Python 3.12 o superior.
- Un bot de Telegram, un canal donde publicar y tu id de usuario administrador.
- Opcional: claves de Gemini y/o Groq para los ganchos con IA.

## Instalación local

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                # completa token, canal y usuario
pytest -q
python main.py
```

En Windows, el entorno de desarrollo usado durante la auditoría se creó con:

```powershell
python -m venv .venv-dev
.venv-dev\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv-dev\Scripts\python.exe -m pytest -q
```

## Variables de entorno

Todas están documentadas en `.env.example`. Las mínimas son:

| Variable | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot |
| `TELEGRAM_CHANNEL_ID` | Canal de publicación (`@canal` o id numérico) |
| `TELEGRAM_USER_ID` | Administrador que recibe avisos y usa comandos de admin |
| `DATABASE` | Ruta de SQLite; en Railway: `/data/ofertas.db` |
| `GEMINI_API_KEYS` o `GEMINI_API_KEY` | Claves de Gemini separadas por coma |
| `GROQ_API_KEY` | Respaldo de IA |
| `AI_HOOK_REQUIRED` | `true` para no publicar ofertas sin gancho de IA |

## Despliegue en Railway

1. Conecta este repositorio a un servicio de Railway (builder: `Dockerfile`).
2. En **Variables**, define `TELEGRAM_*`, las claves de IA y
   `DATABASE=/data/ofertas.db`. No subas el `.env` al repositorio.
3. Crea un **Volume** y móntalo en `/data`. Sin volumen, SQLite se borra en cada
   redespliegue y se pierden suscripciones y deduplicación.
4. Desactiva **Serverless / App Sleeping** en el servicio: el bot usa polling y
   necesita ejecución continua.
5. Opcional: activa *networking*, define `HEALTH_PORT` igual al puerto público y
   configura el healthcheck en `/health`. La app expone estado, último ciclo y
   fuentes.
6. Protege la rama `main` y limita el auto-deploy a cambios revisados. Railway
   construye desde el repositorio público y cualquier push a la rama conectada
   se publica con las credenciales del bot.
7. Configura la política de reinicio en **On failure**.

El `Dockerfile` ya ejecuta como usuario sin privilegios, sin Playwright y con
`HEALTHCHECK` basado en el último ciclo correcto. El entrypoint prepara el
propietario del volumen `/data` antes de bajar privilegios con `gosu`.

## Comandos

| Comando | Quién | Función |
|---|---|---|
| `/start`, `/ayuda` | Todos | Ayuda y aviso de privacidad |
| `/alerta <palabra>` | Todos | Crea una alerta (máximo configurable) |
| `/mis_alertas` | Todos | Lista las alertas propias |
| `/borrar_alerta <palabra>` | Todos | Elimina una alerta |
| `/borrar_mis_datos` | Todos | Borra todas las suscripciones |
| `/estado` | Admin | Fuentes, último ciclo y totales |
| `/diagnostico` | Admin | IA, base de datos, pendientes, webhook y errores |
| `/test_ia` | Admin | Prueba real de IA y muestra el proveedor o el error |
| `/habilitar`, `/deshabilitar` | Admin | Cambian fuentes y lo persisten |

## Estructura

```
main.py                 Entrada y validación de configuración
config.py               Variables y catálogo de fuentes
bot/ofertas_bot.py      Ciclo, publicación, alertas y operación
bot/handlers.py         Comandos y botones
database/db_manager.py  SQLite, migraciones y deduplicación
scrapers/               Slickdeals (RSS), DealNews y DealsOfAmerica
utils/                  IA, formateo, palabras clave, salud y logging
scripts/healthcheck.py  Comprobación para Docker/Railway
tests/                  Pruebas unitarias y de integración
```

## Calidad

```bash
ruff check .
pytest -q
pip-audit -r requirements.txt
```

La integración continua en `.github/workflows/ci.yml` ejecuta lint, tests y
auditoría de dependencias en cada push y pull request.

## Seguridad

- Nunca versiones `.env`; usa las variables de Railway o un gestor de secretos.
- Si el token estuvo dentro de una imagen Docker construida en local, rótalo.
- No versiones `ofertas.db`: puede contener ids de usuario y palabras clave.
- El webhook usa `secret_token` y una ruta fija separada del token del bot.

## Solución de problemas

- **Todas las ofertas con el mismo texto** (“De X a Y. Buen momento…”): la IA no
  está devolviendo gancho y se está usando la plantilla. Ejecuta `/test_ia` y
  `/diagnostico`: muestran el proveedor, el modelo, los modelos descubiertos y
  el error exacto. El bot consulta a la API qué modelos Gemini puede usar tu
  clave y usa `gemini-3.6-flash` como principal; si no está disponible,
  prueba los modelos descubiertos y luego Groq. Puedes cambiar el principal con
  `GEMINI_MODEL_PREFERIDOS`.
- **Ofertas sin foto**: el bot intenta la URL, luego descarga el archivo o un
  candidato de la página (`og:image`, JSON-LD, `<img>`). Si no encuentra nada,
  usa la imagen de respaldo; revisa `/diagnostico` para ver el contador de
  imágenes por URL, descargadas, respaldo y texto.
- **Webhook caído**: se intenta polling automáticamente. Revisa `WEBHOOK_URL`
  (solo el dominio, sin `/webhook`) y que el puerto público coincida con `PORT`.
- **Sin suscripciones tras un redeploy**: falta el volumen en `/data` o
  `DATABASE` no apunta a `/data/ofertas.db`.
