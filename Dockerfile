FROM python:3.13-slim
LABEL org.opencontainers.image.source="https://github.com/imduffy15/local-zappi"
LABEL org.opencontainers.image.description="Experimental Zappi local UDP relay and passive telemetry"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py telemetry.py ctl.py protocol.py control.py ./
COPY web ./web
CMD ["python", "/app/server.py"]
