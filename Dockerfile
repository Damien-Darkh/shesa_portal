FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Binds to 0.0.0.0:5000 so DSM's reverse proxy can reach it at 127.0.0.1:8081
# (the container runs on Synology with port mapping 127.0.0.1:8081->5000).
# This port is never exposed outside the container host itself.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]