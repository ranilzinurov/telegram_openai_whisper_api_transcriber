FROM python:3.12-slim

# lint hint:
# docker run --rm -i hadolint/hadolint < Dockerfile
#
# rules:
# https://github.com/hadolint/hadolint?tab=readme-ov-file#rules

WORKDIR /app
COPY . /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends libmagic1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

ENV GROQ_MODEL='whisper-large-v3'
ENV PYTHONUNBUFFERED=1

CMD ["python", "goodsecretarybot.py"]
