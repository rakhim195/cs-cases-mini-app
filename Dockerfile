FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PORT is provided by the hosting platform (Render / Koyeb / Railway);
# core.config reads it and main.py binds 0.0.0.0:$PORT.
EXPOSE 8000
CMD ["python", "main.py"]
