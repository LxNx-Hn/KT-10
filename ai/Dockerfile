FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY ai/requirements.txt ai/requirements.txt
RUN pip install --no-cache-dir -r ai/requirements.txt

RUN groupadd --system app && \
    useradd --system --gid app --create-home --home-dir /home/app app

ENV HOME=/home/app

COPY --chown=app:app ai/ ai/
COPY --chown=app:app data/ data/
RUN mkdir -p ai/data/cache/osmnx ai/data/cache/odsay ai/data/cache/elevation \
    ai/data/cache/route_features ai/data/cache/tmap ai/data/cache/ors \
    && chown -R app:app ai/data/cache

USER app

EXPOSE 8001
CMD ["uvicorn", "main:app", "--app-dir", "ai", "--host", "0.0.0.0", "--port", "8001"]
