#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="groq-transcriber"
CONTAINER_NAME="groq-transcriber-bot"
ENV_FILE="${ENV_FILE:-.env}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but not found on PATH."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file '$ENV_FILE' not found. Create it (see .env.example)."
  exit 1
fi

echo "Building image '$IMAGE_NAME'..."
docker build -t "$IMAGE_NAME" .

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}\$"; then
  echo "Stopping existing container '$CONTAINER_NAME'..."
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  echo "Removing existing container '$CONTAINER_NAME'..."
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo "Starting container '$CONTAINER_NAME'..."
docker run -d --name "$CONTAINER_NAME" --env-file "$ENV_FILE" --restart unless-stopped "$IMAGE_NAME"

echo "Container is running."
echo "View logs with: docker logs -f $CONTAINER_NAME"
