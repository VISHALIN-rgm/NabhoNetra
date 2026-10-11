FROM node:20-slim AS web
WORKDIR /w
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
ARG VITE_API_URL=
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN useradd -m app && mkdir -p /data
COPY backend/ ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY --from=web /w/dist ./frontend/dist
RUN chown -R app /app /data
ENV HOST=0.0.0.0 PORT=8000 DB_PATH=/data/nabhonetra.db PYTHONUNBUFFERED=1
VOLUME /data
USER app
WORKDIR /app/backend
CMD ["python", "server.py"]
