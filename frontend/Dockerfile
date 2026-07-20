FROM node:20-slim
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
COPY data/ /app/data/

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
