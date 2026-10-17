"""Safe LLM explanation layer: Groq explains deterministic evidence; it never detects or applies fixes."""
from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core import clean_text, proposal_for_match

load_dotenv()

ALLOWED_ACTIONS = {"merge_records", "standardize_value", "flag_for_review"}


class ProposedFix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    survivor: str | None = None
    field_updates: dict[str, str] = Field(default_factory=dict)


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=200)
    reasoning: str
    proposed_fix: ProposedFix
    confidence: float = Field(ge=0, le=1)
    risk: str
    llm_status: str = "validated"


def _mask(value: Any) -> str:
    text = str(value or "").strip()
    return "***" if len(text) < 3 else f"{text[:1]}***{text[-1:]}"


def masked_evidence(match: dict[str, Any], df) -> dict[str, Any]:
    """Only field-level masked values and computed scores enter the LLM prompt."""
    a, b = int(match["record_a"]), int(match["record_b"])
    row_a, row_b = df.loc[a], df.loc[b]
    return {
        "record_a": str(a),
        "record_b": str(b),
        "masked_values_a": {str(k): _mask(v) for k, v in row_a.items()},
        "masked_values_b": {str(k): _mask(v) for k, v in row_b.items()},
        "field_scores": match["field_scores"],
        "computed_score": match["score"],
        "confidence_band": match["band"],
        "allowed_actions": sorted(ALLOWED_ACTIONS),
    }


def validate_fix(fix: dict[str, Any], match: dict[str, Any], schema: dict[str, str]) -> dict[str, Any]:
    """Validate both model-generated and human-edited fixes before persistence."""
    if fix.get("action") not in ALLOWED_ACTIONS:
        raise ValueError("proposed action is not allowed")
    survivor = fix.get("survivor")
    valid_ids = {str(match["record_a"]), str(match["record_b"])}
    if fix["action"] == "merge_records" and str(survivor) not in valid_ids:
        raise ValueError("survivor must be one of the matched records")
    updates = fix.get("field_updates", {}) or {}
    if not isinstance(updates, dict) or any(str(k) not in schema for k in updates):
        raise ValueError("field update contains an unknown column")
    return {"action": fix["action"], "survivor": str(survivor) if survivor is not None else None, "field_updates": {str(k): str(v) for k, v in updates.items()}}


def _validate(payload: Any, computed_score: float, match: dict[str, Any], schema: dict[str, str]) -> Explanation:
    result = Explanation.model_validate(payload)
    result.proposed_fix = ProposedFix.model_validate(validate_fix(result.proposed_fix.model_dump(), match, schema))
    # Displayed confidence always comes from code, never from the LLM.
    result.confidence = computed_score
    if result.proposed_fix.action == "merge_records" and not result.proposed_fix.survivor:
        raise ValueError("merge_records requires a survivor")
    if result.risk not in {"low", "medium", "high"}:
        raise ValueError("risk must be low, medium, or high")
    return result


def _fallback(match: dict[str, Any], df) -> dict[str, Any]:
    base = proposal_for_match(match, df)
    base["llm_status"] = "template_fallback"
    return base


def generate_explanation(match: dict[str, Any], df, schema: dict[str, str]) -> dict[str, Any]:
    """Call Groq when configured; retry malformed output once, then use a safe fallback."""
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("EXPLAINER_API_KEY")
    if not api_key:
        return _fallback(match, df)
    try:
        from openai import OpenAI
        # Keep the reviewer workflow responsive when the remote explainer is
        # unavailable. The deterministic fallback remains the source of truth.
        client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "15")),
        )
        evidence = masked_evidence(match, df)
        system = (
            "You are a data-governance explainer. The matcher already computed the evidence and score. "
            "Explain only; do not invent matches, raw PII, or actions outside the allowed list. "
            "Return one JSON object with summary, reasoning, proposed_fix, confidence, and risk. "
            "proposed_fix.action must be one of merge_records, standardize_value, flag_for_review."
        )
        user = json.dumps({"task": "Explain this proposed duplicate match", "evidence": evidence}, ensure_ascii=False)
        for attempt in range(2):
            if attempt:
                user += "\nPrevious output failed validation. Return strictly valid JSON matching the requested schema."
            response = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            try:
                payload = json.loads(response.choices[0].message.content or "{}")
                return _validate(payload, match["score"], match, schema).model_dump()
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
                continue
    except Exception:
        return _fallback(match, df)
    return _fallback(match, df)
