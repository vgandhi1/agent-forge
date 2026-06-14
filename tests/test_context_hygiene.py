from core.context_hygiene import is_runtime_context, sanitize_decisions


def test_flags_framework_runtime():
    assert is_runtime_context("integrate Ollama within Windows using WSL")
    assert is_runtime_context("set AGENTFORGE_OLLAMA_HOST to the gateway")
    assert is_runtime_context("use qwen2.5:7b-instruct for the reviewer")
    assert is_runtime_context("endpoint http://127.0.0.1:11434")


def test_ignores_product_decisions():
    assert not is_runtime_context("locked 5-label taxonomy for warranty narratives")
    assert not is_runtime_context("needs_review when confidence < 0.55")
    assert not is_runtime_context("regex-first extraction at the API boundary")


def test_sanitize_drops_runtime_entries():
    decisions = {
        "taxonomy": "5 labels: soft_reset, cloud_sync, connectivity_loss, power_cycle, no_fault",
        "ollama_integration_technique": "integrating Ollama within Windows using WSL",
        "llm_provider": "switched pipeline to ollama because no anthropic api key",
        "extraction": "regex-first, Pydantic at API boundaries",
    }
    clean = sanitize_decisions(decisions)
    assert "taxonomy" in clean
    assert "extraction" in clean
    assert "ollama_integration_technique" not in clean  # value leaks runtime
    assert "llm_provider" not in clean                   # key + value leak runtime
    assert len(clean) == 2


def test_sanitize_keeps_all_when_clean():
    decisions = {"a": "use FastAPI", "b": "macro-F1 >= 0.88"}
    assert sanitize_decisions(decisions) == decisions
