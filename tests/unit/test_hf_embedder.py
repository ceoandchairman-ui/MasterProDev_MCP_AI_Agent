"""HuggingFace feature-extraction embeddings (the endpoint the legacy host used) and the factory that picks the format."""

from types import SimpleNamespace

import httpx
import pytest

from mpd_assistant.retrieval.embeddings import (
    HF_INFERENCE_BASE,
    EmbeddingError,
    HuggingFaceEmbedder,
    OpenAICompatibleEmbedder,
    build_embedder,
)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def no_sleep(seconds):
    return None


def embedder(handler, **kw):
    return HuggingFaceEmbedder("hf_SECRETKEY", "BAAI/bge-m3", client=client(handler), sleep=no_sleep, **kw)


async def test_it_posts_the_inputs_to_the_model_path_and_returns_one_vector_per_text():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], request.read()))
        return httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4]])

    out = await embedder(handler).embed(["alpha", "beta"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]
    url, auth, body = seen[0]
    assert url == f"{HF_INFERENCE_BASE}/models/BAAI/bge-m3/pipeline/feature-extraction"
    assert auth == "Bearer hf_SECRETKEY" and b'"inputs"' in body and b"alpha" in body


async def test_large_inputs_are_sent_in_batches_and_kept_in_order():
    sizes = []

    def handler(request):
        import json

        batch = json.loads(request.read())["inputs"]
        sizes.append(len(batch))
        return httpx.Response(200, json=[[float(t)] for t in batch])

    texts = [str(i) for i in range(70)]
    out = await embedder(handler).embed(texts)
    assert sizes == [32, 32, 6] and [v[0] for v in out] == [float(i) for i in range(70)]


async def test_a_busy_model_is_retried_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=[[1.0, 2.0]])

    assert await embedder(handler).embed(["x"]) == [[1.0, 2.0]] and len(calls) == 3


async def test_retries_give_up_and_the_error_names_the_status_but_never_the_key_or_body():
    def handler(request):
        return httpx.Response(402, json={"error": "You have no remaining credits hf_SECRETKEY"})

    with pytest.raises(EmbeddingError) as exc:
        await embedder(handler).embed(["x"])
    assert "HTTP 402" in str(exc.value) and "SECRETKEY" not in str(exc.value) and "credits" not in str(exc.value)

    def always_busy(request):
        return httpx.Response(503, text="loading")

    with pytest.raises(EmbeddingError, match="HTTP 503"):
        await embedder(always_busy).embed(["x"])


async def test_network_failures_are_wrapped():
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(EmbeddingError, match="ConnectTimeout"):
        await embedder(handler).embed(["x"])


@pytest.mark.parametrize(
    "payload",
    [{"error": "x"}, [[0.1]], [[[0.1, 0.2]], [[0.3, 0.4]]], [["a", "b"], ["c", "d"]], [[], []], "text"],
    ids=["object", "wrong count", "token level", "non numbers", "empty vectors", "string"],
)
async def test_unexpected_response_shapes_are_rejected(payload):
    with pytest.raises(EmbeddingError, match="unexpected response shape"):
        await embedder(lambda request: httpx.Response(200, json=payload)).embed(["one", "two"])


async def test_invalid_json_is_rejected():
    with pytest.raises(EmbeddingError, match="invalid JSON"):
        await embedder(lambda request: httpx.Response(200, content=b"<html>")).embed(["x"])


# --- the factory ---------------------------------------------------------------------------
def cfg(**kw):
    base = {"EMBEDDING_API_KEY": None, "HUGGINGFACE_API_KEY": "hf_x", "EMBEDDING_BASE_URL": None, "EMBEDDING_FORMAT": "auto", "EMBEDDING_MODEL": "BAAI/bge-m3", "LLM_BASE_URL": "https://router.huggingface.co/v1"}
    return SimpleNamespace(**{**base, **kw})


def test_no_key_means_no_embedder():
    assert build_embedder(cfg(HUGGINGFACE_API_KEY=None)) is None


def test_auto_picks_the_huggingface_format_without_a_base_url_or_with_hf_inference():
    assert isinstance(build_embedder(cfg()), HuggingFaceEmbedder)
    assert isinstance(build_embedder(cfg(EMBEDDING_BASE_URL="https://router.huggingface.co/hf-inference")), HuggingFaceEmbedder)


def test_auto_picks_the_openai_format_for_any_other_address():
    other = build_embedder(cfg(EMBEDDING_BASE_URL="https://api.deepinfra.com/v1/openai", EMBEDDING_API_KEY="k"))
    assert isinstance(other, OpenAICompatibleEmbedder)


def test_the_format_can_be_forced_and_a_dedicated_key_wins():
    assert isinstance(build_embedder(cfg(EMBEDDING_FORMAT="openai")), OpenAICompatibleEmbedder)
    forced = build_embedder(cfg(EMBEDDING_FORMAT="huggingface", EMBEDDING_BASE_URL="https://my.proxy.example", EMBEDDING_API_KEY="own"))
    assert isinstance(forced, HuggingFaceEmbedder) and forced._key == "own" and forced._url.startswith("https://my.proxy.example/models/")
