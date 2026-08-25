import sys
from pathlib import Path

# understanding() reuses the already-real, already-tested geocode/crop/timecode tools from the
# pipeline package rather than duplicating them — a genuine code dependency, not the kind of
# accidental build-graph coupling this project spent real effort removing elsewhere (that was
# about CI stages implicitly re-triggering each other's work, not about intentional code reuse).
_PIPELINE_ROOT = Path(__file__).resolve().parents[3] / "pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))
