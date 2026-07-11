from paper_agent.config import Settings, load_settings


ENVIRONMENT_VARIABLES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PAPER_AGENT_MODEL",
    "SEMANTIC_SCHOLAR_API_KEY",
    "OPENALEX_MAIL_ADDRESS",
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
    }
    for variable, value in values.items():
        monkeypatch.setenv(variable, value)

    assert load_settings() == Settings(
        openai_api_key="openai-key",
        openai_base_url="https://example.test/v1",
        paper_agent_model="example-model",
        semantic_scholar_api_key="semantic-scholar-key",
        openalex_mail_address="researcher@example.test",
    )


def test_settings_repr_hides_api_keys():
    settings = Settings(
        openai_api_key="sentinel-openai-secret",
        paper_agent_model="example-model",
        semantic_scholar_api_key="sentinel-semantic-scholar-secret",
    )

    representation = repr(settings)

    assert "sentinel-openai-secret" not in representation
    assert "sentinel-semantic-scholar-secret" not in representation
    assert "example-model" in representation
