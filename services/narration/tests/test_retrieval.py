from retrieval import cosine_similarity, retrieve


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_zero_vector_does_not_divide_by_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_retrieve_returns_nothing_for_an_empty_corpus():
    # Real behavior for tonight's actual corpus.py state — must not crash on an empty corpus.
    result = retrieve(bedrock_runtime_client=None, embedding_model_id="unused", corpus=[], query="anything")
    assert result == []


def test_retrieve_ranks_by_similarity_and_never_returns_a_numeric_field():
    class _FakeBedrock:
        def invoke_model(self, **kwargs):
            import json

            class _Body:
                def read(_self):
                    return json.dumps({"embedding": [1.0, 0.0]}).encode("utf-8")

            return {"body": _Body()}

    corpus = [
        {"text": "closely related passage", "source": "a", "embedding": [1.0, 0.0]},
        {"text": "unrelated passage", "source": "b", "embedding": [0.0, 1.0]},
    ]

    result = retrieve(_FakeBedrock(), "unused-model", corpus, "query", top_k=2)

    assert result[0]["text"] == "closely related passage"
    for passage in result:
        assert set(passage.keys()) == {"text", "source"}
