from types import SimpleNamespace

import pytest

import core.external_retriever as retrievers


@pytest.mark.parametrize("error", [ValueError("Unknown EMBEDDING_PROVIDER"), RuntimeError("Qdrant vector dimension mismatch"), RuntimeError("missing dependency")])
def test_configuration_errors_never_become_memory_fallback(monkeypatch, error):
    monkeypatch.setattr(retrievers, "get_settings", lambda: SimpleNamespace(vector_store_backend="qdrant"))
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(retrievers, "QdrantExternalRetriever", fail)
    with pytest.raises(type(error), match=str(error)):
        retrievers.ExternalRetrieverFacade._build_backend()


def test_connection_outage_has_explicit_degraded_backend(monkeypatch):
    monkeypatch.setattr(retrievers, "get_settings", lambda: SimpleNamespace(vector_store_backend="qdrant"))
    def fail(**kwargs):
        raise ConnectionError("offline")
    monkeypatch.setattr(retrievers, "QdrantExternalRetriever", fail)
    backend = retrievers.ExternalRetrieverFacade._build_backend()
    assert backend.get_stats()["effective_backend"] == "memory_fallback"


def test_count_does_not_filter_compatible_embedding_versions(monkeypatch):
    captured = []
    client = SimpleNamespace(count=lambda **kwargs: captured.append(kwargs) or SimpleNamespace(count=1))
    backend = object.__new__(retrievers.QdrantExternalRetriever)
    backend.client, backend.collection_name = client, "external"
    backend._count_cache = {}
    backend.embedding_version = "new-version"
    monkeypatch.setattr(backend, "_match_filter", lambda key, value: (key, value))
    monkeypatch.setattr(backend, "_filter", lambda fields: fields)
    assert backend.count_documents(ticker="NVDA") == 1
    assert all(field[0] != "embedding_version" for field in captured[0]["count_filter"])
