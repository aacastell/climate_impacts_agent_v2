"""Same as before, but shells out to the AWS CLI instead of boto3 (not installed locally) —
stdlib only, real Bedrock Titan Embed v2 calls, no placeholder vectors.
"""

import json
import subprocess
import tempfile
from pathlib import Path

ENTRIES = [
    {
        "text": (
            "Sustained heat stress is projected to force a geographic shift in the US Corn "
            "Belt's most productive maize-growing zone, as prolonged periods of high "
            "temperature disrupt the crop's typical growth patterns in regions that are "
            "currently its most productive."
        ),
        "source": "NASA GISS — Yang & Wang, \"Heat stress to jeopardize crop production in the US Corn Belt\"",
    },
    {
        "text": (
            "Across many staple crops, measurable heat stress tends to begin in a similar "
            "general temperature range, though the exact threshold and its severity vary "
            "significantly by crop. Water availability is a major moderating factor — a given "
            "temperature can be far more damaging to a water-stressed plant than to one with "
            "adequate soil moisture."
        ),
        "source": "NASA (SciTechDaily) — \"Climate Change and Its Environmental Impacts on Crop Growth\"",
    },
    {
        "text": (
            "Sustained heat stress disrupts core plant physiology across many staple crops: it "
            "impairs photosynthesis, alters respiration rates, and — often most consequentially "
            "for final yield — damages fertility processes specifically during a crop's "
            "reproductive growth stages, rather than uniformly throughout its life cycle."
        ),
        "source": "PMC — \"Physiological, Biochemical, and Molecular Mechanisms of Heat Stress Tolerance in Plants\"",
    },
    {
        "text": (
            "In maize specifically, heat stress occurring during the grain-filling stage "
            "disrupts the molecular processes that determine kernel development. This means the "
            "timing of a heat event relative to the crop's growth stage can matter as much as "
            "the event's raw intensity or duration."
        ),
        "source": "Frontiers in Plant Science — \"Molecular mechanism of heat stress during grain filling in maize\"",
    },
    {
        "text": (
            "Cereal crops, including wheat, show heat-stress mechanisms that are often centered "
            "on their reproductive and grain-development stages rather than earlier vegetative "
            "growth, which is why modeling approaches for cereal heat sensitivity generally try "
            "to account for crop growth stage, not just ambient temperature alone."
        ),
        "source": "ScienceDirect — \"Heat stress in cereals: mechanisms and modelling\"",
    },
    {
        "text": (
            "Maize and soybean show measurably different heat-tolerance characteristics from "
            "each other, and both show real geographic heterogeneity in how heat stress affects "
            "them — the same ambient temperature can have a different physiological effect "
            "depending on the region's typical climate and how locally acclimated the crop "
            "variety is, not on temperature alone."
        ),
        "source": "Nature Food (2026) — \"Temperature thresholds of extreme heat-induced yield loss in maize and soybean\"",
    },
    {
        "text": (
            "Across staple crops including rice, wheat, and maize, the reproductive growth "
            "stage — flowering and grain or seed set — is consistently the most drought-"
            "sensitive phase, more so than earlier vegetative growth. This means the timing of "
            "a drought event relative to a crop's growth stage is often a stronger factor in "
            "outcome than the raw severity of the water deficit alone."
        ),
        "source": "Frontiers in Plant Science (2025) — \"Mechanistic insights into drought stress management in staple crops\"",
    },
    {
        "text": (
            "In rice specifically, drought stress occurring at the flowering stage disrupts key "
            "physiological traits tied to grain formation, with the degree of disruption "
            "scaling with how severe the water deficit is during that particular stage."
        ),
        "source": "Nature Scientific Reports — \"Drought stress at flowering stage: rice physiological traits, yield, quality\"",
    },
    {
        "text": (
            "Soybean cultivars vary meaningfully in their resilience to drought occurring during "
            "flowering and early seed-set — the developmental window identified as particularly "
            "sensitive to water stress for this crop — which has direct implications for which "
            "cultivars are more inherently drought-tolerant."
        ),
        "source": "PMC — \"Resilience of soybean cultivars to drought stress during flowering and early-seed-setting\"",
    },
    {
        "text": (
            "At the molecular level, drought stress in maize triggers measurable changes in "
            "gene expression within reproductive tissue specifically, providing a mechanistic "
            "(not just observational) explanation for why drought occurring during this growth "
            "window is particularly consequential for maize yield outcomes."
        ),
        "source": "PMC — \"Effects of drought on gene expression in maize reproductive tissue\" (RNA-Seq study)",
    },
    {
        "text": (
            "Rice responds to drought stress through a combination of visible morphological "
            "changes and underlying molecular responses. These combined insights inform which "
            "specific physiological traits breeding programs target when trying to improve "
            "drought tolerance in rice."
        ),
        "source": "Frontiers in Plant Science (2023) — \"Drought stress in rice: morpho-physiological and molecular responses\"",
    },
]


def embed(text: str) -> list[float]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"inputText": text}, f)
        in_path = f.name
    out_path = in_path + ".out"
    subprocess.run(
        [
            "aws", "bedrock-runtime", "invoke-model",
            "--model-id", "amazon.titan-embed-text-v2:0",
            "--body", f"fileb://{in_path}",
            "--content-type", "application/json",
            "--accept", "application/json",
            "--profile", "dev", "--region", "us-east-2",
            out_path,
        ],
        check=True, capture_output=True,
    )
    body = json.loads(Path(out_path).read_text())
    return body["embedding"]


def main() -> None:
    out = []
    for entry in ENTRIES:
        embedding = embed(entry["text"])
        out.append({"text": entry["text"], "source": entry["source"], "embedding": embedding})
        print(f"embedded ({len(embedding)}d): {entry['source'][:60]}...")

    Path("corpus_with_embeddings.json").write_text(json.dumps(out))
    print(f"\nWrote {len(out)} entries to corpus_with_embeddings.json")


if __name__ == "__main__":
    main()
