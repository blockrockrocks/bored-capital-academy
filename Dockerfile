FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY bca ./bca
COPY course ./course
# editable install: code locates course/ relative to the source tree
RUN pip install --no-cache-dir -e .
# data/ (SQLite + snapshots) and logs/ must live on a persistent volume
ENV BCA_DB=/app/data/academy.sqlite3 BCA_DATA_DIR=/app/data BCA_LOG_DIR=/app/logs
VOLUME ["/app/data", "/app/logs"]
EXPOSE 8000
CMD ["python", "-m", "bca", "web", "serve", "--host", "0.0.0.0", "--port", "8000"]
