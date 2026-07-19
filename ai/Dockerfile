FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgeos-dev libgdal-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY ai/requirements.txt ai/requirements.txt
RUN pip install --no-cache-dir -r ai/requirements.txt

COPY ai/ ai/
COPY data/ data/

EXPOSE 8001
CMD ["uvicorn", "main:app", "--app-dir", "ai", "--host", "0.0.0.0", "--port", "8001"]
