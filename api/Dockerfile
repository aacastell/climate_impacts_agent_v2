# Lambda container image, not a ZIP package — climate_pipeline's real dependencies (xarray,
# netCDF4, dask) are heavy enough that a container image is the practical packaging choice here,
# same reasoning AWS itself gives for scientific-computing Lambda workloads. Build context is the
# repo root — see infra/stacks/api_stack.py for the real build invocation.
FROM public.ecr.aws/lambda/python:3.12

COPY pipeline/climate_pipeline ${LAMBDA_TASK_ROOT}/climate_pipeline
COPY api/requirements.txt ${LAMBDA_TASK_ROOT}/api-requirements.txt
COPY pipeline/requirements.txt ${LAMBDA_TASK_ROOT}/pipeline-requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/api-requirements.txt -r ${LAMBDA_TASK_ROOT}/pipeline-requirements.txt

COPY api/*.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_handler.interpret_lambda_handler"]
