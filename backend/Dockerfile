# --- 1-bosqich: g'ildiraklarni yig'ish -----------------------------------
# build-essential faqat shu yerda qoladi — yakuniy image'ga kompilyator
# tushmaydi (kichikroq va hujum yuzasi torroq).
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# --- 2-bosqich: ishga tushirish muhiti -----------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl — HEALTHCHECK uchun; bash — entrypoint uchun.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY . .

# Windows'da klon qilingan repo'da `entrypoint.sh` CRLF bo'lib kelishi mumkin —
# u holda Linux `env: 'bash\r': No such file or directory` bilan yiqiladi.
# `.gitattributes` buni oldini oladi, bu esa ikkinchi darvoza.
RUN sed -i 's/\r$//' /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh \
    && adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
