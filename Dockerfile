# Usar una imagen de Python 3.10 con Playwright preinstalado
# Esta imagen es estable y soporta versiones de Playwright >= 1.40.0
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar primero el archivo de requerimientos para aprovechar el cache de Docker
COPY requirements.txt .

# Instalar las dependencias de Python
# El navegador de Playwright ya viene instalado en la imagen
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de los archivos de tu proyecto al contenedor
COPY . .

# El comando para ejecutar el bot. Esto reemplaza al Procfile.
CMD ["python", "main.py"]
