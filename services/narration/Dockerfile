# Build context must be the repo root — see services/understanding/Dockerfile for the same
# convention. This service has no dependency on the pipeline package (retrieval/generation/
# verification are self-contained), so it only needs its own directory copied in.
FROM python:3.12-slim

WORKDIR /app

COPY services/narration/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/narration/*.py /app/

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
