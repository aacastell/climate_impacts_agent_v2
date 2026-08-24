"""Writes the small JSON manifest DVC tracks in place of the raw payload — see ADR-006 Step 8."""

import json
from pathlib import Path


def write_manifest(manifest: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return out_path
