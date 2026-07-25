FROM python:3.12-slim-bookworm AS build

COPY services/ingestion_lambda/requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cmake \
        g++ \
        libcurl4-openssl-dev \
        make \
        unzip \
    && pip install --no-cache-dir --target /opt/function \
        -r /tmp/requirements.txt \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim-bookworm

ENV LANG=C.UTF-8 \
    PYTHONPATH=/opt/function \
    SAL_USE_VCLPLUGIN=svp

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        fonts-dejavu-core \
        fonts-liberation2 \
        libreoffice-impress \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/function
COPY --from=build /opt/function /opt/function
COPY src/knowledge_core /opt/function/knowledge_core
COPY services/ingestion_lambda/handler.py /opt/function/handler.py

ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
CMD ["handler.lambda_handler"]
