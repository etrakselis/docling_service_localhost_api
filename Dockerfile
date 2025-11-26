# ------------------------------------------------------------
# 1. Base Image
# ------------------------------------------------------------
FROM python:3.11-slim

# ------------------------------------------------------------
# 2. System dependencies for OCR, PDFs, and Docling
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2 \
    libxslt1.1 \
    libxslt1-dev \
    libgl1 \
    libglib2.0-0 \
    libgl1-mesa-glx \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# 3. Workdir
# ------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------
# 4. Copy dependency file & install Python deps
# ------------------------------------------------------------
COPY requirements.txt .

# Torch CPU wheels come from the PyTorch index when using --extra-index-url
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------
# 5. Copy application code
# ------------------------------------------------------------
COPY api_server.py .

# ------------------------------------------------------------
# 6. Environment variables (override via docker-compose or .env)
# ------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# ------------------------------------------------------------
# 7. Expose FastAPI port
# ------------------------------------------------------------
EXPOSE 8000

# ------------------------------------------------------------
# 8. Run server
# ------------------------------------------------------------
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
