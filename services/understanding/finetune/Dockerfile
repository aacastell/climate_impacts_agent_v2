# Lambda container image, same reasoning as api/Dockerfile: climate_pipeline's real dependencies
# (xarray, netCDF4, dask) are heavy enough that a container image is the practical choice, and
# this needs the same package understanding()'s own service does (agent/tools.py's real
# geocode()/crop()/timecode()) plus mlflow for logging the check's result as a real time series.
# Build context is the repo root — see infra/stacks/model_services_stack.py for the real build
# invocation.
FROM public.ecr.aws/lambda/python:3.12

COPY pipeline/climate_pipeline ${LAMBDA_TASK_ROOT}/climate_pipeline
COPY pipeline/requirements.txt ${LAMBDA_TASK_ROOT}/pipeline-requirements.txt
COPY services/understanding/requirements.txt ${LAMBDA_TASK_ROOT}/understanding-requirements.txt
COPY services/understanding/finetune/requirements.txt ${LAMBDA_TASK_ROOT}/finetune-requirements.txt
RUN pip install --no-cache-dir \
    -r ${LAMBDA_TASK_ROOT}/pipeline-requirements.txt \
    -r ${LAMBDA_TASK_ROOT}/understanding-requirements.txt \
    -r ${LAMBDA_TASK_ROOT}/finetune-requirements.txt

# Flat, same layout services/understanding/*.py already lives in — check_drift.py's own
# sys.path.insert lines were written for local CLI use (relative to its file location on disk);
# copying everything into one flat LAMBDA_TASK_ROOT means its plain `from model_client import
# ...`-style imports resolve directly against Lambda's own default sys.path entry, no code
# change needed for this to work in both places.
COPY services/understanding/*.py ${LAMBDA_TASK_ROOT}/
COPY services/understanding/finetune/*.py ${LAMBDA_TASK_ROOT}/

CMD ["drift_check_handler.handler"]
