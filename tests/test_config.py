import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from paper_agent.config import Settings, load_settings


SUPPORTED_SETTING_NAMES = (
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
    "RETRIEVAL_MODE",
    "RETRIEVAL_TOP_K",
    "RETRIEVAL_RRF_K",
)


@pytest.fixture(autouse=True)
def isolated_settings_environment(tmp_path, monkeypatch) -> None:
    for variable in SUPPORTED_SETTING_NAMES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)


def test_load_settings_uses_safe_defaults(monkeypatch):
    assert load_settings() == Settings()


def test_load_settings_uses_hybrid_retrieval_defaults(monkeypatch) -> None:
    settings = load_settings()
    assert settings.retrieval_mode == "auto"
    assert settings.retrieval_candidate_k == 30
    assert settings.retrieval_top_k == 8
    assert settings.retrieval_rrf_k == 60


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
        "RETRIEVAL_MODE": " hybrid ",
        "RETRIEVAL_TOP_K": " 9 ",
        "RETRIEVAL_RRF_K": " 61 ",
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
        retrieval_mode="hybrid",
        retrieval_top_k=9,
        retrieval_rrf_k=61,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("AUTO", "auto"), (" lexical ", "lexical"), ("Hybrid", "hybrid")],
)
def test_load_settings_normalizes_retrieval_mode(
    monkeypatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", raw)
    assert load_settings().retrieval_mode == expected


@pytest.mark.parametrize("raw", ["unknown", "", "vector"])
def test_load_settings_rejects_unknown_retrieval_mode(
    monkeypatch, raw: str
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", raw)
    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        load_settings()


@pytest.mark.parametrize(
    ("name", "raw", "message"),
    [
        ("RETRIEVAL_TOP_K", "0", "must be at least 1"),
        ("RETRIEVAL_RRF_K", "-1", "must be at least 1"),
        ("RETRIEVAL_TOP_K", "1.5", "must be an integer"),
        ("RETRIEVAL_RRF_K", "not-an-int", "must be an integer"),
    ],
)
def test_load_settings_rejects_invalid_retrieval_k(
    monkeypatch, name: str, raw: str, message: str
) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ValueError, match=rf"{name} {message}"):
        load_settings()


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


def test_load_settings_reads_dotenv_from_current_directory(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=file-key\nRETRIEVAL_MODE=hybrid\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.dashscope_api_key == "file-key"
    assert settings.retrieval_mode == "hybrid"


def test_process_environment_takes_precedence_over_dotenv(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=file-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "process-key")

    assert load_settings().dashscope_api_key == "process-key"


def test_load_settings_ignores_parent_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=parent-key\n",
        encoding="utf-8",
    )
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)

    assert load_settings().dashscope_api_key is None


def test_consecutive_loads_from_different_directories_do_not_leak(
    tmp_path, monkeypatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / ".env").write_text(
        "DASHSCOPE_API_KEY=first-key\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(first)
    first_settings = load_settings()
    monkeypatch.chdir(second)
    second_settings = load_settings()

    assert first_settings.dashscope_api_key == "first-key"
    assert second_settings.dashscope_api_key is None


def test_load_settings_does_not_mutate_process_environment(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=file-key\n",
        encoding="utf-8",
    )
    before = os.environ.copy()

    load_settings()

    assert os.environ == before


def test_blank_dotenv_strings_preserve_optional_and_default_behavior(
    tmp_path,
) -> None:
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=\nBAILIAN_REGION=\nVECTOR_COLLECTION=\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.openai_api_key is None
    assert settings.bailian_region == "beijing"
    assert settings.vector_collection == "momo_scholar_chunks_v1"


def test_blank_dotenv_retrieval_mode_preserves_validation(tmp_path) -> None:
    (tmp_path / ".env").write_text("RETRIEVAL_MODE=\n", encoding="utf-8")

    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        load_settings()


@pytest.mark.parametrize(
    "name",
    [
        "RETRIEVAL_CANDIDATE_K",
        "RETRIEVAL_TOP_K",
        "RETRIEVAL_RRF_K",
    ],
)
def test_blank_dotenv_retrieval_k_preserves_validation(
    tmp_path, name: str
) -> None:
    (tmp_path / ".env").write_text(f"{name}=\n", encoding="utf-8")

    with pytest.raises(ValueError, match=rf"{name} must be an integer"):
        load_settings()


def test_dotenv_example_is_safe_and_documents_retrieval_defaults() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    example_path = repository_root / ".env.example"

    assert example_path.exists()

    values = dotenv_values(example_path)
    assert values["DASHSCOPE_API_KEY"] == ""
    assert values["RETRIEVAL_MODE"] == "auto"
    assert values["RETRIEVAL_CANDIDATE_K"] == "30"
    assert values["RETRIEVAL_TOP_K"] == "8"
    assert values["RETRIEVAL_RRF_K"] == "60"
    assert not any(
        value
        for name, value in values.items()
        if name.endswith("API_KEY")
    )
