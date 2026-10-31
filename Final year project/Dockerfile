FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data MODEL_DIR=/app/models
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system healthlens \
    && useradd --system --gid healthlens --create-home healthlens \
    && mkdir /data && chown healthlens:healthlens /data
COPY app ./app
COPY models ./models
USER healthlens
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import ssl, urllib.request; urllib.request.urlopen('https://127.0.0.1:8000/ready', context=ssl.create_default_context(cafile='/certs/root-ca.pem'), timeout=4)"
CMD ["python", "-m", "app.serve", "--host", "0.0.0.0", "--port", "8000"]
