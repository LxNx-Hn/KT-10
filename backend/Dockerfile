FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

RUN groupadd --system app && \
    useradd --system --gid app --create-home --home-dir /home/app app

ENV HOME=/home/app

COPY --chown=app:app backend/ backend/
COPY --chown=app:app data/ data/
RUN mkdir -p /var/cache/kt10/vworld /var/cache/kt10/shade \
    && chown -R app:app /var/cache/kt10

USER app

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
