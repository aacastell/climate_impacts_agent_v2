# interpret()'s real, lightweight Lambda image — split from narrate()'s (see Dockerfile.narrate)
# for a real, measured reason, not tidiness: interpret_handler.py no longer touches the
# precomputed store at all (ADR-004's restored decision — it returns real identifiers only, the
# frontend fetches and parses the precomputed file itself), so it needs none of
# climate_pipeline's xarray/netCDF4/numpy dependency — confirmed live: this Lambda's handler
# imports in ~114ms with only boto3+httpx installed. A shared image with narrate() (which still
# needs those, for its own real server-side verification-gate lookups) would mean interpret()'s
# cold start paid for weight it never actually uses. Build context is the repo root — see
# infra/stacks/api_stack.py for the real build invocation.
FROM public.ecr.aws/lambda/python:3.12

# Still needs climate_pipeline for CROP_FIELDS/output_field_name (climate_pipeline.process.
# field_names) — a real, deliberately lightweight module with no xarray/numpy/netCDF4 import of
# its own (see that module's own docstring).
COPY pipeline/climate_pipeline ${LAMBDA_TASK_ROOT}/climate_pipeline
COPY api/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY api/interpret_handler.py api/interpret_lambda_handler.py ${LAMBDA_TASK_ROOT}/

CMD ["interpret_lambda_handler.handler"]
