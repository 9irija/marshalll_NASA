# Marswalk API. Build after `make pipeline corpus demo` so data/processed is populated.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR=/tmp/numba
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config config
COPY pipeline pipeline
COPY planner planner
COPY api api
COPY flight_controller flight_controller
COPY corpus/sources.yaml corpus/sources.yaml
COPY corpus/chunks corpus/chunks
COPY data/manifest.json data/manifest.json
COPY data/raw/m20 data/raw/m20
COPY data/raw/meda data/raw/meda
COPY data/processed/grid.npz data/processed/aoi_resolved.json data/processed/science_hotspots.json data/processed/context.npz data/processed/ml.npz data/processed/ml.json data/processed/geology_legend.json data/processed/
COPY data/processed/web data/processed/web
COPY data/processed/demo data/processed/demo
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
