FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# the pinned base still ships a zlib with fixable HIGH findings (Trivy): take the patched package until the base digest
# is refreshed to one that has it, then delete this line
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade zlib1g && rm -rf /var/lib/apt/lists/*
WORKDIR /bot
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt
COPY core.py app.py ./
USER 10001:10001
CMD ["python", "app.py"]
