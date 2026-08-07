FROM python:3.12-slim

WORKDIR /app

# System deps for scientific wheels are provided by manylinux; slim is enough.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY data/fitted /app/data/fitted

ENV PYTHONPATH=/app/backend
WORKDIR /app/backend

# NOT a server. The CMD here used to be `uvicorn pitwall.api.main:app`, written
# during the Phase 0 scaffold against a plan that changed: Phase 5's API was
# deliberately deferred and that module does not exist, so the image could not
# start. It is now what it is actually for — reproducing the artifacts.
CMD ["python", "-m", "pytest", "-q"]
