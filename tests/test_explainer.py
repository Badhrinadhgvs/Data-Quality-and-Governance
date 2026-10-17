import pandas as pd

from explainer import generate_explanation, masked_evidence


def test_fallback_without_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("EXPLAINER_API_KEY", raising=False)
    df = pd.DataFrame([{"name": "Rajesh Kumar", "email": "r@example.com"}, {"name": "Rajesh Kumaar", "email": "r@example.com"}])
    match = {"record_a": "0", "record_b": "1", "field_scores": {"name": .95}, "score": .95, "band": "High"}
    result = generate_explanation(match, df, {"name": "name", "email": "email"})
    assert result["llm_status"] == "template_fallback"
    assert result["proposed_fix"]["action"] in {"merge_records", "standardize_value", "flag_for_review"}


def test_masking_does_not_expose_raw_values():
    df = pd.DataFrame([{"name": "Rajesh Kumar", "email": "r@example.com"}, {"name": "Rajesh Kumaar", "email": "r@example.com"}])
    match = {"record_a": "0", "record_b": "1", "field_scores": {"name": .95}, "score": .95, "band": "High"}
    evidence = masked_evidence(match, df)
    assert "Rajesh Kumar" not in str(evidence)
    assert "r@example.com" not in str(evidence)
