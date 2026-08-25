"""RAG retrieval — real mechanism, deliberately empty corpus (see corpus.py). ADR-007: "RAG
retrieves literature explaining mechanisms, never numerical results." This module only ever
returns passage text; nothing here can return a number, by construction — there's no numeric
field anywhere in a corpus entry's shape for a bug to accidentally leak.

No vector database: at the corpus size this project actually needs (a curated set of mechanism
passages, not a general-purpose document store), plain in-memory cosine similarity over
precomputed embeddings is the right amount of infrastructure, not a shortcut. Reaching for
OpenSearch/pgvector ahead of a demonstrated need would be exactly the kind of premature
infrastructure this project has repeatedly rejected elsewhere (Airflow, Kubeflow, Triton — see
ADR-006).
"""

import math

from langfuse import observe


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_text(bedrock_runtime_client, text: str, embedding_model_id: str) -> list[float]:
    import json

    response = bedrock_runtime_client.invoke_model(
        modelId=embedding_model_id,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    return body["embedding"]


@observe(name="narration:retrieve", as_type="retriever")
def retrieve(bedrock_runtime_client, embedding_model_id: str, corpus: list[dict], query: str, top_k: int = 3) -> list[dict]:
    """corpus: [{"text": str, "source": str, "embedding": list[float]}, ...] — embeddings
    precomputed once (see corpus.py), not recomputed per query. Returns the top_k passages by
    cosine similarity, each {"text": ..., "source": ...} — never a numeric value."""
    if not corpus:
        return []

    query_embedding = embed_text(bedrock_runtime_client, query, embedding_model_id)
    scored = sorted(
        corpus, key=lambda entry: cosine_similarity(query_embedding, entry["embedding"]), reverse=True
    )
    return [{"text": entry["text"], "source": entry["source"]} for entry in scored[:top_k]]
