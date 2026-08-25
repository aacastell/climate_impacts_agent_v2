"""The RAG corpus — deliberately empty. This is not a stub for the retrieval mechanism (that's
real, see retrieval.py) — it's an honest placeholder for content that needs real sourcing and
review, not something to fabricate overnight to make the system look more complete than it is.

Filling this in for real means: sourcing genuine passages from real IPCC-assessed literature on
heat/water stress mechanisms per crop, attributing each to its real source, and reviewing them for
accuracy — a curation task, not a code-writing one. See docs/overnight-2026-08-25.md and
CORPUS_SOURCES_CANDIDATES.md (real, found-not-fabricated candidate sources — NASA-first,
agronomic-mechanism-focused — ready for review, not yet excerpted into entries below).

Expected shape once populated, one entry per passage:
{"text": "...", "source": "...", "embedding": [...]}  # embedding precomputed once via
retrieval.embed_text(), not recomputed per query.
"""

CORPUS: list[dict] = []
