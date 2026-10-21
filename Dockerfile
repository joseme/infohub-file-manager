# InfoHub File Manager - Flet web dashboard
FROM python:3.12-slim

ARG ARG_UID=1000
ARG ARG_GID=1000

RUN groupadd -g "$ARG_GID" infohub && \
    useradd -l -u "$ARG_UID" -m -d /app -s /bin/bash -g infohub infohub

WORKDIR /app

COPY requirements.txt ./
# Versiones fijas: Flet 1.x no es compatible con la app, y flet-web 0.85 con FastAPI 0.156
RUN pip install --no-cache-dir -r requirements.txt flet-web==0.85.2 fastapi==0.136.3

COPY --chown=infohub:infohub app.py config_manager.py ui_theme.py workspace_map.py ./
COPY --chown=infohub:infohub assets ./assets

RUN chown -R infohub:infohub /app

USER infohub

ENV APP_PORT=8500 \
    PYTHONUNBUFFERED=1

EXPOSE 8500

CMD ["python", "app.py"]
