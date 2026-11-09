# Build from the kit's root, so the image can take the kit's card builder, task order and settings registry (one
# definition each):
#   docker build -f bot/Dockerfile .
# bot/Dockerfile.dockerignore keeps the build context to the files copied below.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# the pinned base still ships a zlib with fixable HIGH findings (Trivy): take the patched package until the base digest
# is refreshed to one that has it, then delete this line
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade zlib1g && rm -rf /var/lib/apt/lists/*
WORKDIR /bot
COPY bot/requirements.txt .
RUN pip install --require-hashes -r requirements.txt
COPY scripts/card.py scripts/reply.py scripts/settings.py plugins/agentkit/scripts/board.py kit/
# settings.py reads the registry from ../config next to its own folder
COPY config/settings.json config/
COPY bot/core.py bot/app.py ./
USER 10001:10001
CMD ["python", "app.py"]
