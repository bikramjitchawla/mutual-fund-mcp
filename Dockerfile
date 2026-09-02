FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MF_PROVIDER=mfapi \
    PORT=8000

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["mutual-fund-mcp", "--transport", "http", "--host", "0.0.0.0"]

