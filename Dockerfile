# Humanitarian Geocoder - Multi-stage Docker Build

# ---------------------------------------------------------------------------
# Stage 1: Build the React/TypeScript frontend
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Install npm deps first (layer cache)
COPY frontend/package*.json ./
RUN npm install --prefer-offline

# Copy source and build
COPY frontend/ ./
RUN npm run build
# Outputs to /app/static (via vite.config.ts outDir: '../static')

# ---------------------------------------------------------------------------
# Stage 2: Python builder (compile wheels with GDAL)
# ---------------------------------------------------------------------------
FROM python:3.11-slim as builder

# Install build dependencies for GDAL
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV GDAL_CONFIG=/usr/bin/gdal-config
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Create working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Install runtime dependencies for GDAL
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV GDAL_CONFIG=/usr/bin/gdal-config
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN useradd -m -u 1000 appuser

# Create working directory
WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy compiled frontend assets
COPY --from=frontend-build /app/static ./static/

# Copy application files
COPY --chown=appuser:appuser geocode.py .
COPY --chown=appuser:appuser xlsforms.py .
COPY --chown=appuser:appuser manage.py .
COPY --chown=appuser:appuser config/ ./config/
COPY --chown=appuser:appuser apps/ ./apps/
COPY --chown=appuser:appuser scripts/ ./scripts/
RUN chmod +x scripts/entrypoint.sh

# GeoDjango uses the system GDAL/GEOS installed above (via gdal-config).
ENV DJANGO_SETTINGS_MODULE=config.settings

# Create data directory for boundary files (can be bind-mounted from host)
RUN mkdir -p /data && chown appuser:appuser /data

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()"

# Run the application (ingest runs automatically on first start if the DB is empty)
CMD ["sh", "scripts/entrypoint.sh"]
