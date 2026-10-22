# Jev-style decision API in front of the Gemma 4 Ollama container. Stdlib only.
FROM python:3.12-slim
WORKDIR /app
COPY server.py jev.py bench.py calibrate.py feedback_export.py ./
COPY data ./data
RUN mkdir -p /app/runtime
ENV PYTHONUNBUFFERED=1 \
    JEV_HOST=0.0.0.0 \
    JEV_PORT=9931 \
    JEV_BACKEND_URL=http://127.0.0.1:11434 \
    JEV_CALIBRATION=/app/runtime/calibration.json
EXPOSE 9931
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9931/health', timeout=4)"
CMD ["python3", "server.py"]
