# ============================================
# Base image: slim Python 3.11 with no extras
# ============================================
FROM python:3.11-slim

# Avoid Python writing .pyc files & enable buffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ============================================
# System deps needed for Docling + Paramiko
# ============================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libjpeg-dev \
    libpng-dev \
    libmagic1 \
    gcc \
    g++ \
    ssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Create app directory
# ============================================
WORKDIR /app

# ============================================
# Copy requirements first for caching
# ============================================
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# ============================================
# Copy your API code
# ============================================
COPY api_server.py .

# ============================================
# Expose FastAPI port
# ============================================
EXPOSE 8000

# ============================================
# Run the API with uvicorn
# ============================================
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
