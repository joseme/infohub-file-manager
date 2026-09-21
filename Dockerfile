# InfoHub File Manager - Flet web dashboard
FROM python:3.12-slim

ARG ARG_UID=1000
ARG ARG_GID=1000

RUN groupadd -g "$ARG_GID" infohub && \
    useradd -l -u "$ARG_UID" -m -d /app -s /bin/bash -g infohub infohub

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt flet-web

COPY --chown=infohub:infohub app.py config_manager.py ./

RUN chown -R infohub:infohub /app

USER infohub

ENV APP_PORT=8500 \
    PYTHONUNBUFFERED=1

EXPOSE 8500

CMD ["python", "app.py"]
