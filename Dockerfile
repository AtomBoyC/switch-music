# syntax=docker/dockerfile:1
# Switch Music — multi-platform playlist migration workbench
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Switch Music" \
      org.opencontainers.image.description="Self-hosted playlist migration, dedupe & sync between Spotify, YouTube Music, NetEase, QQ Music, Kugou and Apple Music" \
      org.opencontainers.image.source="https://github.com/AtomBoyC/switch-music"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONWARNINGS=ignore \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8765 \
    SWITCH_MUSIC_DATA_DIR=/data \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./
COPY backend ./backend
COPY static ./static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The entrypoint fixes /data ownership and then drops to an unprivileged user (PUID/PGID, default 10001).
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8765'), timeout=4)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "app.py"]
