FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY seed.py .

# El CSV se monta como volumen en /data
CMD ["python", "seed.py"]
