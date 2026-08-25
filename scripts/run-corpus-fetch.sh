#!/usr/bin/env bash
# Runs all 15 RAG corpus source fetches in parallel — each its own fully
# independent CodeBuild project (see infra/app.py's CORPUS_FETCH_STEPS and
# pipeline/climate_pipeline/fetch/corpus.py), same fetch/process separation
# ADR-006 already established for ISIMIP data, same per-component
# independence as every other fetch/process step in this project.
#
# Real candidate sources, not fabricated — found via web search (see
# services/narration/CORPUS_SOURCES_CANDIDATES.md). This only fetches raw
# content into S3 (raw/corpus/); it never curates it into the actual
# retrievable corpus (services/narration/corpus.py) — that stays a human
# review step.
#
# Deliberately not Airflow, even though this is a genuinely new data type:
# ADR-006's real trigger for Airflow is "multiple recurring pipelines," and
# this is an occasional pull, same shape as ISIMIP fetch, not a second
# recurring pipeline — see conversation for the fuller reasoning.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_WAIT_MINUTES=15

CORPUS_FETCH_PROJECTS=(
  "ClimateImpactsFetchCorpusNasaGissCornBeltHeatStress"
  "ClimateImpactsFetchCorpusNasaClimateChangeCropGrowth"
  "ClimateImpactsFetchCorpusNasaDroughtFamineWarnings"
  "ClimateImpactsFetchCorpusNasaHarvestGeoCropsim"
  "ClimateImpactsFetchCorpusNatureFoodMaizeSoybeanHeatThresholds"
  "ClimateImpactsFetchCorpusPnasTemperatureGlobalCropYields"
  "ClimateImpactsFetchCorpusFrontiersMaizeGrainFillingHeat"
  "ClimateImpactsFetchCorpusSciencedirectCerealHeatMechanisms"
  "ClimateImpactsFetchCorpusPmcHeatStressToleranceMechanisms"
  "ClimateImpactsFetchCorpusSpringerHeatStressReview2025"
  "ClimateImpactsFetchCorpusFrontiersDroughtStapleCrops"
  "ClimateImpactsFetchCorpusNatureRiceFloweringDrought"
  "ClimateImpactsFetchCorpusPmcSoybeanDroughtFlowering"
  "ClimateImpactsFetchCorpusPmcMaizeDroughtReproductiveRnaseq"
  "ClimateImpactsFetchCorpusFrontiersRiceDroughtResponses"
)

MAX_WAIT_MINUTES="$MAX_WAIT_MINUTES" "$ROOT/scripts/run-codebuild-parallel.sh" "${CORPUS_FETCH_PROJECTS[@]}"

echo "==> All 15 corpus source fetches completed"
