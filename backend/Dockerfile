FROM python:3.12-slim

WORKDIR /app

# System deps for scientific wheels are provided by manylinux; slim is enough.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY data/fitted /app/data/fitted

ENV PYTHONPATH=/app/backend
EXPOSE 8000

CMD ["uvicorn", "pitwall.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
