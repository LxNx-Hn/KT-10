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
# 운영 배치가 컨테이너 안에서 실행된다. PostgreSQL은 compose 네트워크에만
# 있어 호스트에서 직접 붙을 수 없으므로, 탈퇴 계정 파기 같은 주기 작업은
# 이 이미지 안에서 돌려야 한다.
COPY --chown=app:app scripts/ scripts/
RUN mkdir -p /var/cache/kt10/vworld /var/cache/kt10/shade \
    && chown -R app:app /var/cache/kt10

USER app

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
