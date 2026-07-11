import pytest

from paper_agent.config import Settings, load_settings


ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PAPER_AGENT_MODEL",
    "SEMANTIC_SCHOLAR_API_KEY",
    "OPENALEX_MAIL_ADDRESS",
    "DASHSCOPE_API_KEY",
    "BAILIAN_REGION",
    "BAILIAN_EMBEDDING_MODEL",
    "VECTOR_COLLECTION",
    "RETRIEVAL_CANDIDATE_K",
)


def test_load_settings_uses_safe_defaults(monkeypatch):
    for variable in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    assert load_settings() == Settings()


def test_load_settings_reads_environment(monkeypatch):
    values = {
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_BASE_URL": "https://example.test/v1",
        "PAPER_AGENT_MODEL": "example-model",
        "SEMANTIC_SCHOLAR_API_KEY": "semantic-scholar-key",
        "OPENALEX_MAIL_ADDRESS": "researcher@example.test",
        "DASHSCOPE_API_KEY": "  dashscope-key  ",
        "BAILIAN_REGION": "  shanghai  ",
        "BAILIAN_EMBEDDING_MODEL": "  custom-embedding  ",
        "VECTOR_COLLECTION": "  custom-chunks  ",
        "RETRIEVAL_CANDIDATE_K": "  42  ",
    }
    for variable, value in values.items():
        monkeypatch.setenv(variable, value)

    assert load_settings() == Settings(
        openai_api_key="openai-key",
        openai_base_url="https://example.test/v1",
        paper_agent_model="example-model",
        semantic_scholar_api_key="semantic-scholar-key",
        openalex_mail_address="researcher@example.test",
        dashscope_api_key="dashscope-key",
        bailian_region="shanghai",
        bailian_embedding_model="custom-embedding",
        vector_collection="custom-chunks",
        retrieval_candidate_k=42,
    )


def test_settings_repr_hides_api_keys():
    settings = Settings(
        openai_api_key="sentinel-openai-secret",
        paper_agent_model="example-model",
        semantic_scholar_api_key="sentinel-semantic-scholar-secret",
        dashscope_api_key="sentinel-dashscope-secret",
    )

    representation = repr(settings)

    assert "sentinel-openai-secret" not in representation
    assert "sentinel-semantic-scholar-secret" not in representation
    assert "sentinel-dashscope-secret" not in representation
    assert "example-model" in representation


@pytest.mark.parametrize("value", ["not-an-integer", "1.5", ""])
def test_load_settings_rejects_non_integer_candidate_k(monkeypatch, value):
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_K", value)

    with pytest.raises(ValueError, match="RETRIEVAL_CANDIDATE_K must be an integer"):
        load_settings()


@pytest.mark.parametrize("value", ["0", "-1"])
def test_load_settings_rejects_candidate_k_less_than_one(monkeypatch, value):
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_K", value)

    with pytest.raises(ValueError, match="RETRIEVAL_CANDIDATE_K must be at least 1"):
        load_settings()
