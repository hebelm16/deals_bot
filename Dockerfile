# Usar una imagen más reciente de Playwright que se alinee con una versión de Python estable.
FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar primero el archivo de requerimientos para aprovechar el cache de Docker
COPY requirements.txt .

# Instalar las dependencias de Python
RUN pip install -r requirements.txt

# Copiar el resto de los archivos de tu proyecto al contenedor
COPY . .

# El comando para ejecutar el bot. Esto reemplaza al Procfile.
CMD ["python", "main.py"]
