FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system signalgate && useradd --system --gid signalgate --create-home signalgate
WORKDIR /app

COPY backend/requirements.txt backend/requirements-hosted.txt /tmp/backend/
RUN python -m pip install --upgrade pip \
    && pip install -r /tmp/backend/requirements-hosted.txt

COPY backend /app/backend
WORKDIR /app/backend

USER signalgate
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
