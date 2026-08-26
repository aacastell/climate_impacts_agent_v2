import sys
from pathlib import Path

# Both paths: finetune's own modules import from services/understanding (model_client,
# orchestrator), and orchestrator.py itself imports climate_pipeline.agent.tools — the second
# path was missing here until a real (non-stubbed) run of build_training_dataset.py's own tests
# caught the resulting ModuleNotFoundError live.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "pipeline"))
