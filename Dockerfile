# Usar imagen de Playwright 1.40.0 con Python 3.10 (estable)
# IMPORTANTE: Los navegadores en esta imagen están compilados para Playwright 1.40.0
# Por eso es crítico que requirements.txt especifique playwright==1.40.0
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar primero el archivo de requerimientos para aprovechar el cache de Docker
COPY requirements.txt .

# Instalar las dependencias de Python
# IMPORTANTE: NO actualizar Playwright, la versión 1.40.0 está fija en requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de los archivos de tu proyecto al contenedor
COPY . .

# El comando para ejecutar el bot. Esto reemplaza al Procfile.
CMD ["python", "main.py"]
