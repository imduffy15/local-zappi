FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/imduffy15/local-zappi"
LABEL org.opencontainers.image.description="Experimental Zappi local UDP relay and passive telemetry"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py telemetry.py ctl.py ./
CMD ["python", "/app/server.py"]
