FROM python:3.12-slim
WORKDIR /bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core.py app.py ./
USER nobody
CMD ["python", "app.py"]
