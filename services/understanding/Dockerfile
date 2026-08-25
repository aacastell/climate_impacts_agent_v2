# Build context must be the repo root (not services/understanding/) — this needs both
# pipeline/climate_pipeline (the real, already-tested geocode/crop/timecode tools) and this
# service's own code. See infra/stacks/understanding_service_stack.py for the real build
# invocation.
FROM python:3.12-slim

WORKDIR /app

COPY pipeline/climate_pipeline /app/climate_pipeline
COPY services/understanding/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/understanding/*.py /app/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
