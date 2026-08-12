FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEDGER_INBOX_DATA_DIR=/data

RUN useradd --create-home --uid 10001 ledger
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

USER ledger
VOLUME ["/data"]
EXPOSE 8080
CMD ["ledger-inbox", "serve", "--host", "0.0.0.0", "--port", "8080"]
