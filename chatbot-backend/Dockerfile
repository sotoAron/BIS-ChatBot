# ─── Stage 1: builder ────────────────────────────────────────────────────────
# Instalamos todas las dependencias con pip install --user.
# Resultado: binarios (uvicorn, etc.) + paquetes quedan en /root/.local
# Esa carpeta se copia íntegra al stage de runtime.
FROM python:3.11-slim AS builder

WORKDIR /build

# Herramientas de compilación necesarias para extensiones C (chromadb, hiredis)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Instalar torch CPU-only PRIMERO para evitar descargar los wheels GPU (~2 GB)
RUN pip install --no-cache-dir --user \
    torch==2.3.1 \
    --index-url https://download.pytorch.org/whl/cpu

# Instalar el resto de dependencias en el mismo --user prefix
RUN pip install --no-cache-dir --user \
    -r requirements.txt

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Dependencias de sistema mínimas (chromadb necesita sqlite3, healthcheck necesita curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root con home directory explícito
RUN useradd --uid 1001 --create-home --shell /bin/bash appuser

# Copiar paquetes + binarios instalados por el builder (/root/.local)
# al home del usuario final (/home/appuser/.local)
COPY --from=builder /root/.local /home/appuser/.local

# Ajustar permisos para que appuser sea dueño de su .local
RUN chown -R appuser:appuser /home/appuser/.local

# Añadir el directorio de binarios del usuario al PATH del sistema.
# Orden: primero .local/bin (pip --user), luego /usr/local/bin (python base).
ENV PATH="/home/appuser/.local/bin:/usr/local/bin:${PATH}"

# Copiar código de la aplicación con el propietario correcto
COPY --chown=appuser:appuser ./app ./app

# Cambiar al usuario no-root
USER appuser

# Puerto de la aplicación
EXPOSE 8000

# Health check interno al contenedor
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# CMD usa python -m uvicorn como mecanismo seguro:
# garantiza que se use el intérprete Python correcto incluso si
# el binario 'uvicorn' no estuviera en PATH por alguna razón.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
