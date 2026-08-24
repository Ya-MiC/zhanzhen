FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY zhanzhen ./zhanzhen
COPY web ./web
COPY rules_builtin.yaml ./
RUN pip install --no-cache-dir ".[web,excel,pdf]"
ENV ZZ_DATA_DIR=/data
VOLUME ["/data"]
ENV ZZ_PORT=8710
EXPOSE 8710
CMD ["sh", "-c", "uvicorn zhanzhen.webapp:app --host 0.0.0.0 --port ${ZZ_PORT:-8710}"]
