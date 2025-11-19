# Usar la imagen oficial de Playwright que incluye Python y todas las dependencias.
# Asegúrate de que la versión de Python coincida con la de tu proyecto si es necesario.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

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
