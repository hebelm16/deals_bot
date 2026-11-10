#!/bin/sh
# Prepara el volumen persistente y ejecuta el bot con un usuario sin privilegios.
set -e

if [ "$(id -u)" = "0" ]; then
    if [ -d /data ]; then
        if ! chown -R app:app /data 2>/dev/null; then
            echo "Aviso: no se pudo cambiar el propietario de /data" >&2
        fi
    fi
    exec gosu app "$@"
fi

exec "$@"
