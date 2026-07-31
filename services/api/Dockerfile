FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app/services/api

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        texlive-fonts-recommended \
        texlive-latex-extra \
        texlive-xetex \
    && rm -rf /var/lib/apt/lists/*

COPY services/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app/src
COPY services/api /app/services/api
COPY participant_sales_brief_generation_prompt.md /app/participant_sales_brief_generation_prompt.md
COPY plugins/relay/skills /app/plugins/relay/skills
COPY frontend/downloads/relay-downloads.json /app/frontend/downloads/relay-downloads.json

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
