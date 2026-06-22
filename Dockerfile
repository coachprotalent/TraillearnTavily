FROM python:3.12-slim

WORKDIR /service

# Dépendances système pour lxml/trafilatura (libxml2/libxslt).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV SERVICE_PORT=8088
EXPOSE 8088

CMD ["python", "-m", "app.server"]
