from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from paper_agent.generation import GenerationMessage
from paper_agent.generation.dashscope_transport import DashScopeChatTransport
from paper_agent.eval.evidence_package import (
    EvidencePackageBuilder,
    EvidencePackageError,
    REQUIRED_ARTIFACTS,
    verify_evidence_package,
)
from paper_agent.modeling import StrictModel

from .contracts import AtomicAssertion, CitationOccurrence, EvidenceMatch
from .metrics import CitationCaseInput, score_citation_baseline
from .report import render_citation_reports


EVALUATION_METHOD = "llm_as_judge_single_pass"
GENERATION_MODEL = "qwen3.7-plus-2026-05-26"
_SHA256 = r"^[0-9a-f]{64}$"
_SAFE_REASON = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_RUBRIC = {
    "supported": "Gold-grounded cited evidence entails the complete assertion.",
    "unsupported": "Gold-grounded cited evidence does not entail the complete assertion.",
}
_PROMPT_TEMPLATE = (
    "Judge only whether the cited passages, checked against the supplied Gold Evidence, "
    "entail the complete assertion. Return supported or unsupported, a concise rationale, "
    "and only supplied evidence IDs. Do not use outside knowledge."
)
_HUMAN_AUTHORITY_FILES = {
    "review-rubric.json",
    "calibration.jsonl",
    "judgments.jsonl",
    "adjudications.jsonl",
}
AUTOMATED_AUTHORITY_FILES = frozenset(
    {
        "automated-judge-state.json",
        "automated-judge-authority.json",
        "automated-judge-inputs.jsonl",
        "automated-judge-sends.jsonl",
        "automated-judge-passes.jsonl",
        "automated-judge-decisions.jsonl",
        "automated-judge-failures.jsonl",
    }
)
AUTOMATED_PACKAGE_ARTIFACTS = frozenset(
    (REQUIRED_ARTIFACTS - _HUMAN_AUTHORITY_FILES) | AUTOMATED_AUTHORITY_FILES
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


AUTOMATED_JUDGE_RUBRIC_SHA256 = _digest(_RUBRIC)
AUTOMATED_JUDGE_PROMPT_SHA256 = hashlib.sha256(
    _PROMPT_TEMPLATE.encode("utf-8")
).hexdigest()


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class AutomatedJudgeError(ValueError):
    """A sanitized automated-judge integrity or budget failure."""


class FrozenJudgeModel(StrictModel):
    model_config = {"extra": "forbid", "frozen": True}


class AutomatedJudgeAuthority(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    data_kind: Literal["real", "synthetic"]
    provider: str
    judge_model_version: str
    generation_model_version: str
    model_authority: str
    authority_sha256: str = Field(pattern=_SHA256)
    judge_base_url: str
    pricing_authority: str
    pricing_currency: str
    input_cost_per_million_tokens: StrictFloat = Field(gt=0)
    output_cost_per_million_tokens: StrictFloat = Field(gt=0)
    rubric_version: str
    rubric_sha256: str = Field(pattern=_SHA256)
    prompt_version: str
    prompt_sha256: str = Field(pattern=_SHA256)
    gold_evidence_sha256: str = Field(pattern=_SHA256)
    generation_output_sha256: str = Field(pattern=_SHA256)
    temperature: Literal[0.0] = 0.0
    timeout_seconds: StrictFloat = Field(gt=0)
    max_retries_per_pass: StrictInt = Field(ge=0, le=1)
    max_completion_tokens_per_send: StrictInt = Field(gt=0)
    max_prompt_tokens_per_send: StrictInt = Field(gt=0)
    max_total_sends: StrictInt = Field(gt=0)
    max_total_prompt_tokens: StrictInt = Field(gt=0)
    max_total_completion_tokens: StrictInt = Field(gt=0)
    max_total_cost: StrictFloat = Field(gt=0)

    _required = field_validator(
        "provider",
        "judge_model_version",
        "generation_model_version",
        "model_authority",
        "judge_base_url",
        "pricing_authority",
        "pricing_currency",
        "rubric_version",
        "prompt_version",
    )(_nonblank)

    @model_validator(mode="after")
    def _authority_is_safe(self) -> "AutomatedJudgeAuthority":
        if self.judge_model_version == self.generation_model_version:
            raise ValueError("judge model must differ from generation model")
        for value, label in (
            (self.model_authority, "model authority"),
            (self.pricing_authority, "pricing authority"),
            (self.judge_base_url, "judge base URL"),
        ):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"{label} must be a safe HTTPS reference")
        if self.rubric_sha256 != AUTOMATED_JUDGE_RUBRIC_SHA256:
            raise ValueError("automated judge rubric hash is not supported")
        if self.prompt_sha256 != AUTOMATED_JUDGE_PROMPT_SHA256:
            raise ValueError("automated judge prompt hash is not supported")
        for value in (
            self.input_cost_per_million_tokens,
            self.output_cost_per_million_tokens,
            self.timeout_seconds,
            self.max_total_cost,
        ):
            if not math.isfinite(value):
                raise ValueError("automated judge numeric authority must be finite")
        return self

    @property
    def max_cost_per_send(self) -> float:
        return (
            self.max_prompt_tokens_per_send * self.input_cost_per_million_tokens
            + self.max_completion_tokens_per_send
            * self.output_cost_per_million_tokens
        ) / 1_000_000


class JudgePassage(FrozenJudgeModel):
    evidence_id: str
    text: str
    paper_id: str | None = None
    locator: str | None = None

    _required = field_validator("evidence_id", "text")(_nonblank)


class AutomatedJudgeInput(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    case_id: str
    run_id: str
    blinded_case_id: str
    assertion_id: str
    assertion_text: str
    citation_occurrence_ids: tuple[str, ...]
    cited_passages: tuple[JudgePassage, ...]
    gold_passages: tuple[JudgePassage, ...]
    deterministic_support_match_ids: tuple[str, ...] = ()
    output_sha256: str = Field(pattern=_SHA256)
    evidence_sha256: str = Field(pattern=_SHA256)
    gold_evidence_sha256: str = Field(pattern=_SHA256)
    config_sha256: str = Field(pattern=_SHA256)

    _required = field_validator(
        "case_id", "run_id", "blinded_case_id", "assertion_id", "assertion_text"
    )(_nonblank)

    @model_validator(mode="after")
    def _input_is_complete(self) -> "AutomatedJudgeInput":
        for values, label in (
            (self.citation_occurrence_ids, "citation occurrence IDs"),
            (self.deterministic_support_match_ids, "support match IDs"),
        ):
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"{label} must be unique and nonblank")
        if not self.cited_passages or not self.gold_passages:
            raise ValueError("automated judge input requires cited and Gold passages")
        return self


JudgeResult = Literal["supported", "unsupported"]


class JudgeProviderResult(FrozenJudgeModel):
    result: JudgeResult
    rationale: str
    evidence_references: tuple[str, ...]
    prompt_tokens: StrictInt = Field(ge=0)
    completion_tokens: StrictInt = Field(ge=0)
    model_version: str

    _required = field_validator("rationale", "model_version")(_nonblank)


class JudgeSemanticResponse(FrozenJudgeModel):
    result: JudgeResult
    rationale: str
    evidence_references: tuple[str, ...]

    _required = field_validator("rationale")(_nonblank)


class AutomatedJudgeProvider(Protocol):
    def judge(
        self,
        *,
        payload: Mapping[str, object],
        pass_index: int,
        timeout_seconds: float,
    ) -> JudgeProviderResult: ...


class DashScopeAutomatedJudgeProvider:
    """One transport send per call; retries remain visible to the outer ledger."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        authority: AutomatedJudgeAuthority,
        transport: DashScopeChatTransport,
    ) -> None:
        self.api_key = _nonblank(api_key)
        self.base_url = _nonblank(base_url)
        self.authority = authority
        self.transport = transport

    def judge(
        self,
        *,
        payload: Mapping[str, object],
        pass_index: int,
        timeout_seconds: float,
    ) -> JudgeProviderResult:
        del pass_index
        response = self.transport.send(
            messages=(
                GenerationMessage(role="system", content=_PROMPT_TEMPLATE),
                GenerationMessage(role="user", content=_canonical_json(dict(payload))),
            ),
            model=self.authority.judge_model_version,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout_seconds,
            temperature=0.0,
            max_tokens=self.authority.max_completion_tokens_per_send,
        )
        semantic = JudgeSemanticResponse.model_validate(json.loads(response.content))
        if response.usage is None or any(
            value is None
            for value in (response.usage.prompt_tokens, response.usage.completion_tokens)
        ):
            raise AutomatedJudgeError("judge usage metadata is missing")
        return JudgeProviderResult(
            result=semantic.result,
            rationale=semantic.rationale,
            evidence_references=semantic.evidence_references,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model_version=response.model,
        )


class JudgeSendRecord(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    send_index: StrictInt = Field(gt=0)
    assertion_id: str
    pass_index: StrictInt = Field(ge=1, le=3)
    attempt_index: StrictInt = Field(gt=0)
    status: Literal["reserved", "succeeded", "failed"]
    prompt_tokens_accounted: StrictInt = Field(ge=0)
    completion_tokens_accounted: StrictInt = Field(ge=0)
    cost_accounted: StrictFloat = Field(ge=0)
    failure_reason_code: str | None = None


class AutomatedJudgeFailure(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    failure_id: str
    case_id: str
    assertion_id: str
    pass_index: StrictInt = Field(ge=1, le=3)
    judge_model_version: str
    rubric_sha256: str = Field(pattern=_SHA256)
    prompt_sha256: str = Field(pattern=_SHA256)
    gold_evidence_sha256: str = Field(pattern=_SHA256)
    output_sha256: str = Field(pattern=_SHA256)
    send_indices: tuple[int, ...]
    prompt_tokens_accounted: StrictInt = Field(ge=0)
    completion_tokens_accounted: StrictInt = Field(ge=0)
    cost_accounted: StrictFloat = Field(ge=0)
    latency_ms: StrictFloat = Field(ge=0)
    reason_code: str

    _required = field_validator(
        "failure_id", "case_id", "assertion_id", "judge_model_version", "reason_code"
    )(_nonblank)

    @field_validator("reason_code")
    @classmethod
    def _safe_reason_code(cls, value: str) -> str:
        if not _SAFE_REASON.fullmatch(value):
            raise ValueError("failure reason code must be sanitized")
        return value


class AutomatedJudgePass(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    pass_id: str
    case_id: str
    assertion_id: str
    pass_index: StrictInt = Field(ge=1, le=3)
    judge_model_version: str
    rubric_sha256: str = Field(pattern=_SHA256)
    prompt_sha256: str = Field(pattern=_SHA256)
    gold_evidence_sha256: str = Field(pattern=_SHA256)
    output_sha256: str = Field(pattern=_SHA256)
    result: JudgeResult
    rationale: str
    evidence_references: tuple[str, ...]
    prompt_tokens: StrictInt = Field(ge=0)
    completion_tokens: StrictInt = Field(ge=0)
    latency_ms: StrictFloat = Field(ge=0)
    send_indices: tuple[int, ...]

    _required = field_validator(
        "pass_id", "case_id", "assertion_id", "judge_model_version", "rationale"
    )(_nonblank)


class AutomatedAssertionDecision(FrozenJudgeModel):
    schema_version: Literal["1.0"] = "1.0"
    evaluation_method: Literal["llm_as_judge_single_pass"] = EVALUATION_METHOD
    decision_id: str
    case_id: str
    assertion_id: str
    semantic_verdict: JudgeResult
    decision_source: Literal[
        "deterministic_gold_match", "single_pass", "two_pass_agreement", "tie_break"
    ]
    pass_ids: tuple[str, ...]
    judge_model_version: str
    rubric_sha256: str = Field(pattern=_SHA256)
    prompt_sha256: str = Field(pattern=_SHA256)
    gold_evidence_sha256: str = Field(pattern=_SHA256)
    output_sha256: str = Field(pattern=_SHA256)

    @property
    def judgment_id(self) -> str:
        return self.decision_id


def _jsonl(values: Sequence[FrozenJudgeModel]) -> str:
    return "".join(_canonical_json(item.model_dump(mode="json")) + "\n" for item in values)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_models(path: Path, model: type[FrozenJudgeModel]) -> tuple[FrozenJudgeModel, ...]:
    if not path.exists():
        return ()
    values: list[FrozenJudgeModel] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            values.append(model.model_validate(json.loads(line)))
    return tuple(values)


def _provider_payload(item: AutomatedJudgeInput) -> dict[str, object]:
    return {
        "instruction": _PROMPT_TEMPLATE,
        "blinded_case_id": item.blinded_case_id,
        "assertion_id": item.assertion_id,
        "assertion": item.assertion_text,
        "cited_passages": [passage.model_dump(mode="json") for passage in item.cited_passages],
        "gold_passages": [passage.model_dump(mode="json") for passage in item.gold_passages],
    }


def _validate_input_authority(
    authority: AutomatedJudgeAuthority,
    item: AutomatedJudgeInput,
) -> None:
    if item.output_sha256 != authority.generation_output_sha256:
        raise AutomatedJudgeError("generation output hash changed")
    if item.gold_evidence_sha256 != authority.gold_evidence_sha256:
        raise AutomatedJudgeError("Gold Evidence hash changed")


def run_automated_judge(
    *,
    output: Path,
    authority: AutomatedJudgeAuthority,
    inputs: Sequence[AutomatedJudgeInput],
    provider: AutomatedJudgeProvider,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[AutomatedAssertionDecision, ...]:
    """Run or resume the Gold-grounded single-pass MVP judge."""

    if len({item.assertion_id for item in inputs}) != len(inputs):
        raise AutomatedJudgeError("automated judge assertion IDs must be unique")
    for item in inputs:
        _validate_input_authority(authority, item)
    authority_payload = authority.model_dump(mode="json")
    input_payload = [item.model_dump(mode="json") for item in inputs]
    state = {
        "schema_version": "1.0",
        "evaluation_method": EVALUATION_METHOD,
        "authority_sha256": _digest(authority_payload),
        "inputs_sha256": _digest(input_payload),
    }
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "automated-judge-state.json"
    if state_path.exists():
        if json.loads(state_path.read_text(encoding="utf-8")) != state:
            raise AutomatedJudgeError("automated judge resume authorities changed")
    else:
        _atomic_write(state_path, _canonical_json(state) + "\n")
        _atomic_write(output / "automated-judge-authority.json", _canonical_json(authority_payload) + "\n")
        _atomic_write(output / "automated-judge-inputs.jsonl", _jsonl(tuple(inputs)))
        for name in (
            "automated-judge-sends.jsonl",
            "automated-judge-passes.jsonl",
            "automated-judge-decisions.jsonl",
            "automated-judge-failures.jsonl",
        ):
            _atomic_write(output / name, "")

    sends = list(_load_models(output / "automated-judge-sends.jsonl", JudgeSendRecord))
    passes = list(_load_models(output / "automated-judge-passes.jsonl", AutomatedJudgePass))
    decisions = list(
        _load_models(output / "automated-judge-decisions.jsonl", AutomatedAssertionDecision)
    )
    decisions_by_assertion = {item.assertion_id: item for item in decisions}
    pass_by_key = {(item.assertion_id, item.pass_index): item for item in passes}
    failures = list(
        _load_models(output / "automated-judge-failures.jsonl", AutomatedJudgeFailure)
    )

    def persist() -> None:
        _atomic_write(output / "automated-judge-sends.jsonl", _jsonl(tuple(sends)))
        _atomic_write(output / "automated-judge-passes.jsonl", _jsonl(tuple(passes)))
        _atomic_write(output / "automated-judge-decisions.jsonl", _jsonl(tuple(decisions)))
        _atomic_write(output / "automated-judge-failures.jsonl", _jsonl(tuple(failures)))

    def run_pass(item: AutomatedJudgeInput, pass_index: int) -> AutomatedJudgePass:
        cached = pass_by_key.get((item.assertion_id, pass_index))
        if cached is not None:
            return cached
        prior_sends = [
            record
            for record in sends
            if record.assertion_id == item.assertion_id and record.pass_index == pass_index
        ]
        send_indices = [record.send_index for record in prior_sends]
        maximum_attempts = authority.max_retries_per_pass + 1
        if len(prior_sends) >= maximum_attempts:
            raise AutomatedJudgeError("automated judge pass retry budget exhausted")

        def record_failure(reason_code: str, started: float) -> None:
            related = [record for record in sends if record.send_index in send_indices]
            failure_payload = {
                "assertion_id": item.assertion_id,
                "pass_index": pass_index,
                "send_indices": send_indices,
                "reason_code": reason_code,
            }
            failures.append(
                AutomatedJudgeFailure(
                    failure_id=f"automated-failure-{_digest(failure_payload)[:20]}",
                    case_id=item.case_id,
                    assertion_id=item.assertion_id,
                    pass_index=pass_index,
                    judge_model_version=authority.judge_model_version,
                    rubric_sha256=authority.rubric_sha256,
                    prompt_sha256=authority.prompt_sha256,
                    gold_evidence_sha256=item.gold_evidence_sha256,
                    output_sha256=item.output_sha256,
                    send_indices=tuple(send_indices),
                    prompt_tokens_accounted=sum(
                        record.prompt_tokens_accounted for record in related
                    ),
                    completion_tokens_accounted=sum(
                        record.completion_tokens_accounted for record in related
                    ),
                    cost_accounted=sum(record.cost_accounted for record in related),
                    latency_ms=max(0.0, (monotonic() - started) * 1000),
                    reason_code=reason_code,
                )
            )
            persist()

        for attempt_index in range(len(prior_sends) + 1, maximum_attempts + 1):
            accounted_prompt = sum(record.prompt_tokens_accounted for record in sends)
            accounted_completion = sum(record.completion_tokens_accounted for record in sends)
            accounted_cost = sum(record.cost_accounted for record in sends)
            if (
                len(sends) >= authority.max_total_sends
                or accounted_prompt + authority.max_prompt_tokens_per_send
                > authority.max_total_prompt_tokens
                or accounted_completion + authority.max_completion_tokens_per_send
                > authority.max_total_completion_tokens
                or accounted_cost + authority.max_cost_per_send > authority.max_total_cost + 1e-12
            ):
                raise AutomatedJudgeError("automated judge cumulative budget exhausted")
            send_index = len(sends) + 1
            send_indices.append(send_index)
            reserved = JudgeSendRecord(
                send_index=send_index,
                assertion_id=item.assertion_id,
                pass_index=pass_index,
                attempt_index=attempt_index,
                status="reserved",
                prompt_tokens_accounted=authority.max_prompt_tokens_per_send,
                completion_tokens_accounted=authority.max_completion_tokens_per_send,
                cost_accounted=authority.max_cost_per_send,
            )
            sends.append(reserved)
            persist()
            started = monotonic()
            try:
                result = provider.judge(
                    payload=_provider_payload(item),
                    pass_index=pass_index,
                    timeout_seconds=authority.timeout_seconds,
                )
                if result.model_version != authority.judge_model_version:
                    raise AutomatedJudgeError("judge response model changed")
                allowed_refs = {
                    passage.evidence_id for passage in (*item.cited_passages, *item.gold_passages)
                }
                if not set(result.evidence_references) <= allowed_refs:
                    raise AutomatedJudgeError("judge returned unknown evidence reference")
                if (
                    result.prompt_tokens > authority.max_prompt_tokens_per_send
                    or result.completion_tokens > authority.max_completion_tokens_per_send
                ):
                    raise AutomatedJudgeError("judge token ceiling exceeded")
            except AutomatedJudgeError:
                sends[-1] = reserved.model_copy(
                    update={"status": "failed", "failure_reason_code": "judge_contract_error"}
                )
                persist()
                record_failure("judge_contract_error", started)
                raise
            except Exception:
                sends[-1] = reserved.model_copy(
                    update={"status": "failed", "failure_reason_code": "judge_provider_error"}
                )
                persist()
                if attempt_index < maximum_attempts:
                    continue
                record_failure("judge_provider_error", started)
                raise AutomatedJudgeError("automated judge pass failed") from None
            sends[-1] = reserved.model_copy(
                update={
                    "status": "succeeded",
                    "prompt_tokens_accounted": result.prompt_tokens,
                    "completion_tokens_accounted": result.completion_tokens,
                    "cost_accounted": (
                        result.prompt_tokens * authority.input_cost_per_million_tokens
                        + result.completion_tokens * authority.output_cost_per_million_tokens
                    )
                    / 1_000_000,
                }
            )
            payload = {
                "assertion_id": item.assertion_id,
                "pass_index": pass_index,
                "result": result.result,
                "rationale": result.rationale,
                "evidence_references": result.evidence_references,
                "send_indices": send_indices,
            }
            record = AutomatedJudgePass(
                pass_id=f"judge-pass-{_digest(payload)[:20]}",
                case_id=item.case_id,
                assertion_id=item.assertion_id,
                pass_index=pass_index,
                judge_model_version=authority.judge_model_version,
                rubric_sha256=authority.rubric_sha256,
                prompt_sha256=authority.prompt_sha256,
                gold_evidence_sha256=item.gold_evidence_sha256,
                output_sha256=item.output_sha256,
                result=result.result,
                rationale=result.rationale,
                evidence_references=result.evidence_references,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=max(0.0, (monotonic() - started) * 1000),
                send_indices=tuple(send_indices),
            )
            passes.append(record)
            pass_by_key[(item.assertion_id, pass_index)] = record
            persist()
            return record
        raise AssertionError("unreachable")

    for item in inputs:
        if item.assertion_id in decisions_by_assertion:
            continue
        if item.deterministic_support_match_ids:
            verdict: JudgeResult = "supported"
            source = "deterministic_gold_match"
            used_passes: tuple[AutomatedJudgePass, ...] = ()
        else:
            first = run_pass(item, 1)
            verdict = first.result
            source = "single_pass"
            used_passes = (first,)
        decision_payload = {
            "assertion_id": item.assertion_id,
            "verdict": verdict,
            "source": source,
            "pass_ids": [record.pass_id for record in used_passes],
        }
        decision = AutomatedAssertionDecision(
            decision_id=f"automated-decision-{_digest(decision_payload)[:20]}",
            case_id=item.case_id,
            assertion_id=item.assertion_id,
            semantic_verdict=verdict,
            decision_source=source,
            pass_ids=tuple(record.pass_id for record in used_passes),
            judge_model_version=authority.judge_model_version,
            rubric_sha256=authority.rubric_sha256,
            prompt_sha256=authority.prompt_sha256,
            gold_evidence_sha256=item.gold_evidence_sha256,
            output_sha256=item.output_sha256,
        )
        decisions.append(decision)
        decisions_by_assertion[item.assertion_id] = decision
        persist()
    return tuple(decisions)  # type: ignore[return-value]


def validate_automated_judge_authorities(root: Path) -> tuple[AutomatedAssertionDecision, ...]:
    """Validate a complete automated authority without invoking a provider."""

    authority = AutomatedJudgeAuthority.model_validate(
        json.loads((root / "automated-judge-authority.json").read_text(encoding="utf-8"))
    )
    inputs = tuple(
        item
        for item in _load_models(root / "automated-judge-inputs.jsonl", AutomatedJudgeInput)
        if isinstance(item, AutomatedJudgeInput)
    )
    passes = tuple(
        item
        for item in _load_models(root / "automated-judge-passes.jsonl", AutomatedJudgePass)
        if isinstance(item, AutomatedJudgePass)
    )
    decisions = tuple(
        item
        for item in _load_models(
            root / "automated-judge-decisions.jsonl", AutomatedAssertionDecision
        )
        if isinstance(item, AutomatedAssertionDecision)
    )
    sends = tuple(
        item
        for item in _load_models(root / "automated-judge-sends.jsonl", JudgeSendRecord)
        if isinstance(item, JudgeSendRecord)
    )
    if [item.send_index for item in sends] != list(range(1, len(sends) + 1)):
        raise AutomatedJudgeError("automated judge send provenance is not contiguous")
    if len({item.assertion_id for item in inputs}) != len(inputs):
        raise AutomatedJudgeError("automated judge inputs contain duplicates")
    if len({item.assertion_id for item in decisions}) != len(decisions):
        raise AutomatedJudgeError("automated judge decisions contain duplicates")
    if {item.assertion_id for item in decisions} != {item.assertion_id for item in inputs}:
        raise AutomatedJudgeError("automated judge decisions are incomplete")
    pass_by_id = {item.pass_id: item for item in passes}
    if len(pass_by_id) != len(passes):
        raise AutomatedJudgeError("automated judge pass provenance is duplicated")
    input_by_id = {item.assertion_id: item for item in inputs}
    for decision in decisions:
        item = input_by_id[decision.assertion_id]
        _validate_input_authority(authority, item)
        if (
            decision.judge_model_version != authority.judge_model_version
            or decision.rubric_sha256 != authority.rubric_sha256
            or decision.prompt_sha256 != authority.prompt_sha256
            or decision.gold_evidence_sha256 != item.gold_evidence_sha256
            or decision.output_sha256 != item.output_sha256
        ):
            raise AutomatedJudgeError("automated decision provenance changed")
        linked = [pass_by_id.get(pass_id) for pass_id in decision.pass_ids]
        if any(record is None for record in linked):
            raise AutomatedJudgeError("automated decision pass provenance is missing")
        records = [record for record in linked if record is not None]
        if any(
            record.assertion_id != decision.assertion_id
            or record.judge_model_version != authority.judge_model_version
            or record.rubric_sha256 != authority.rubric_sha256
            or record.prompt_sha256 != authority.prompt_sha256
            or record.gold_evidence_sha256 != item.gold_evidence_sha256
            or record.output_sha256 != item.output_sha256
            for record in records
        ):
            raise AutomatedJudgeError("automated judge pass provenance changed")
        for record in records:
            linked_sends = [
                send for send in sends if send.send_index in record.send_indices
            ]
            if (
                not record.send_indices
                or len(linked_sends) != len(record.send_indices)
                or any(
                    send.assertion_id != record.assertion_id
                    or send.pass_index != record.pass_index
                    for send in linked_sends
                )
                or [send.attempt_index for send in linked_sends]
                != list(range(1, len(linked_sends) + 1))
                or linked_sends[-1].status != "succeeded"
                or any(send.status == "succeeded" for send in linked_sends[:-1])
                or linked_sends[-1].prompt_tokens_accounted != record.prompt_tokens
                or linked_sends[-1].completion_tokens_accounted
                != record.completion_tokens
            ):
                raise AutomatedJudgeError("automated judge send provenance changed")
        if decision.decision_source == "deterministic_gold_match":
            if records or not item.deterministic_support_match_ids or decision.semantic_verdict != "supported":
                raise AutomatedJudgeError("deterministic Gold decision is invalid")
        elif decision.decision_source == "single_pass":
            if (
                [record.pass_index for record in records] != [1]
                or records[0].result != decision.semantic_verdict
            ):
                raise AutomatedJudgeError("single-pass provenance is invalid")
        elif decision.decision_source == "two_pass_agreement":
            if (
                [record.pass_index for record in records] != [1, 2]
                or len({record.result for record in records}) != 1
                or records[0].result != decision.semantic_verdict
            ):
                raise AutomatedJudgeError("two-pass agreement provenance is invalid")
        elif (
            [record.pass_index for record in records] != [1, 2, 3]
            or records[0].result == records[1].result
            or records[2].result != decision.semantic_verdict
        ):
            raise AutomatedJudgeError("automated tie-break provenance is incomplete")
    if {index for record in passes for index in record.send_indices} != {
        record.send_index for record in sends
    }:
        raise AutomatedJudgeError("automated judge authority contains orphan sends")
    failures = tuple(
        item
        for item in _load_models(
            root / "automated-judge-failures.jsonl", AutomatedJudgeFailure
        )
        if isinstance(item, AutomatedJudgeFailure)
    )
    if failures:
        raise AutomatedJudgeError("automated judge authority contains unresolved failures")
    return decisions


def _verify_generation_authority(root: Path) -> tuple[Path, str | None]:
    manifest_path = root / "package-manifest.json"
    authority_path = root / "generation-authority.json"
    if not manifest_path.exists() and not authority_path.exists():
        return root, None
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (
        manifest.get("schema_version") != "1.0"
        or manifest.get("package_kind") != "citation_generation_authority"
        or manifest.get("sealed") is not True
        or manifest.get("artifacts")
        != [
            {
                "byte_length": authority_path.stat().st_size,
                "path": "generation-authority.json",
                "sha256": hashlib.sha256(authority_path.read_bytes()).hexdigest(),
            }
        ]
    ):
        raise AutomatedJudgeError("generation authority package manifest is invalid")
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    if authority.get("package_kind") != "citation_generation_authority":
        raise AutomatedJudgeError("generation authority package kind changed")
    source_root = Path(str(authority.get("source_root", "")))
    artifacts = authority.get("source_artifacts")
    if not source_root.is_absolute() or not isinstance(artifacts, list):
        raise AutomatedJudgeError("generation authority source provenance is invalid")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise AutomatedJudgeError("generation authority artifact provenance is invalid")
        path = Path(str(artifact.get("absolute_path", "")))
        try:
            expected_path = (source_root / str(artifact["relative_path"])).resolve(strict=True)
            resolved_path = path.resolve(strict=True)
        except (KeyError, OSError):
            raise AutomatedJudgeError("generation authority source artifact is unavailable") from None
        if resolved_path != expected_path:
            raise AutomatedJudgeError("generation authority source artifact path changed")
        payload = resolved_path.read_bytes()
        if (
            len(payload) != artifact.get("byte_length")
            or hashlib.sha256(payload).hexdigest() != artifact.get("sha256")
        ):
            raise AutomatedJudgeError("generation authority source artifact hash changed")
    return source_root, hashlib.sha256(manifest_bytes).hexdigest()


def inspect_frozen_generation(root: Path) -> dict[str, object]:
    """Read-only compatibility check for raw or sealed real 20-case generation."""

    source_root, authority_manifest_sha = _verify_generation_authority(root)

    manifest = json.loads(
        (source_root / "generation-manifest.json").read_text(encoding="utf-8")
    )
    outputs = (source_root / "pipeline-outputs.jsonl").read_bytes()
    output_sha = hashlib.sha256(outputs).hexdigest()
    rows = {
        name: [
            json.loads(line)
            for line in (source_root / name).read_text(encoding="utf-8").splitlines()
            if line
        ]
        for name in ("case-results.jsonl", "pipeline-outputs.jsonl", "evidence.jsonl", "gold-judgments.jsonl")
    }
    case_ids = manifest.get("selected_case_ids")
    if (
        manifest.get("status") != "completed"
        or manifest.get("request_model") != GENERATION_MODEL
        or manifest.get("resolved_response_models") != [GENERATION_MODEL]
        or manifest.get("output_sha256") != output_sha
        or not isinstance(case_ids, list)
        or len(case_ids) != 20
        or len(case_ids) != len(set(case_ids))
        or manifest.get("failed_case_ids") != []
        or any(len(rows[name]) != 20 for name in rows)
        or [row.get("case_id") for row in rows["case-results.jsonl"]] != case_ids
        or [row.get("case_id") for row in rows["pipeline-outputs.jsonl"]] != case_ids
        or [row.get("case_id") for row in rows["evidence.jsonl"]] != case_ids
        or any(row.get("status") != "completed" for row in rows["case-results.jsonl"])
    ):
        raise AutomatedJudgeError("frozen 20-case generation is incomplete or inconsistent")
    return {
        "case_count": 20,
        "generation_model_version": GENERATION_MODEL,
        "generation_output_sha256": output_sha,
        "gold_evidence_sha256": hashlib.sha256(
            (source_root / "gold-judgments.jsonl").read_bytes()
        ).hexdigest(),
        "generation_authority_manifest_sha256": authority_manifest_sha,
        "provider_send_count": manifest.get("provider_send_count"),
        "failed_case_count": 0,
    }


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AutomatedJudgeError(f"{path.name} is missing or invalid") from error
    if not isinstance(value, dict):
        raise AutomatedJudgeError(f"{path.name} must be an object")
    return value


def _automated_statistics(root: Path) -> tuple[dict[str, object], AutomatedJudgeAuthority]:
    decisions = validate_automated_judge_authorities(root)
    authority = AutomatedJudgeAuthority.model_validate(
        _read_json(root / "automated-judge-authority.json")
    )
    assertions = tuple(
        AtomicAssertion.model_validate(value)
        for value in (
            json.loads(line)
            for line in (root / "assertions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
    occurrences = tuple(
        CitationOccurrence.model_validate(value)
        for value in (
            json.loads(line)
            for line in (root / "citation-occurrences.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
    matches = tuple(
        EvidenceMatch.model_validate(value)
        for value in (
            json.loads(line)
            for line in (root / "evidence-matches.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )
    if {item.assertion_id for item in decisions} != {item.assertion_id for item in assertions}:
        raise AutomatedJudgeError("automated decisions do not cover every assertion")
    match_ids = {item.match_id for item in matches if item.supports_assertion}
    inputs = tuple(
        item
        for item in _load_models(root / "automated-judge-inputs.jsonl", AutomatedJudgeInput)
        if isinstance(item, AutomatedJudgeInput)
    )
    for item in inputs:
        if not set(item.deterministic_support_match_ids) <= match_ids:
            raise AutomatedJudgeError("deterministic support match provenance is invalid")
    passes = tuple(
        item
        for item in _load_models(root / "automated-judge-passes.jsonl", AutomatedJudgePass)
        if isinstance(item, AutomatedJudgePass)
    )
    config = _read_json(root / "resolved-config.json")
    raw_cases = config.get("cases")
    if not isinstance(raw_cases, list):
        raise AutomatedJudgeError("resolved config cases are missing")
    cases: list[CitationCaseInput] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise AutomatedJudgeError("resolved config case is invalid")
        case_id = raw.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise AutomatedJudgeError("resolved config case ID is invalid")
        case_assertions = tuple(item for item in assertions if item.case_id == case_id)
        assertion_ids = {item.assertion_id for item in case_assertions}
        cases.append(
            CitationCaseInput(
                case_id=case_id,
                assertions=case_assertions,
                citation_occurrences=tuple(
                    item for item in occurrences if item.assertion_id in assertion_ids
                ),
                evidence_matches=tuple(
                    item for item in matches if item.assertion_id in assertion_ids
                ),
                judgments=tuple(
                    item for item in decisions if item.assertion_id in assertion_ids
                ),
                unscorable_assertion_ids=tuple(raw.get("unscorable_assertion_ids", ())),
                duration_ms=sum(
                    item.latency_ms for item in passes if item.assertion_id in assertion_ids
                ),
                failure_reason_code=raw.get("failure_reason_code"),
            )
        )
    if {case.case_id for case in cases} != {item.case_id for item in assertions}:
        raise AutomatedJudgeError("resolved cases do not cover automated assertions")
    return score_citation_baseline(cases=tuple(cases)), authority


def _automated_authority_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for name in sorted(AUTOMATED_AUTHORITY_FILES):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _automated_projections(root: Path) -> dict[str, str]:
    statistics, authority = _automated_statistics(root)
    dataset = _read_json(root / "dataset-manifest.json")
    environment = _read_json(root / "environment.json")
    if dataset.get("data_kind") != authority.data_kind:
        raise AutomatedJudgeError("automated judge data kind changed")
    models = environment.get("models")
    if (
        not isinstance(models, dict)
        or models.get("generation") != authority.generation_model_version
        or models.get("judge") != authority.judge_model_version
    ):
        raise AutomatedJudgeError("automated judge model provenance is missing")
    passes = tuple(
        item
        for item in _load_models(root / "automated-judge-passes.jsonl", AutomatedJudgePass)
        if isinstance(item, AutomatedJudgePass)
    )
    decisions = validate_automated_judge_authorities(root)
    tie_breaks = sum(item.decision_source == "tie_break" for item in decisions)
    single_passes = sum(item.decision_source == "single_pass" for item in decisions)
    aggregate = {
        "evaluation_method": EVALUATION_METHOD,
        "aggregate": statistics["aggregate"],
        "assertion_status_counts": statistics["assertion_status_counts"],
        "denominators": statistics["denominators"],
        "operations": statistics["operations"],
        "judge_operations": {
            "pass_count": len(passes),
            "first_two_disagreement_count": tie_breaks,
            "tie_break_pass_count": tie_breaks,
        },
    }
    confidence = {
        "evaluation_method": EVALUATION_METHOD,
        "bootstrap": statistics["bootstrap"],
        "aggregate_ci_95": {
            name: {
                "low": value["ci_95_low"],
                "high": value["ci_95_high"],
                "case_denominator": value["case_denominator"],
            }
            for name, value in statistics["aggregate"].items()
        },
    }
    report, resume = render_citation_reports(
        statistics,
        {
            "evaluation_method": EVALUATION_METHOD,
            "case_count": statistics["denominators"]["attempted_cases"],
            "data_kind": authority.data_kind,
            "git_sha": environment.get("git_sha"),
            "git_dirty": environment.get("git_dirty"),
            "sealed": True,
            "recomputed": True,
            "automated_judge_complete": True,
            "rubric_version": authority.rubric_version,
            "generation_model_version": authority.generation_model_version,
            "judge_model_version": authority.judge_model_version,
            "judge_pass_count": len(passes),
            "single_pass_decision_count": single_passes,
            "judge_disagreement_count": tie_breaks,
            "judge_tie_break_count": tie_breaks,
            "dataset_fingerprint_sha256": dataset.get("dataset_fingerprint_sha256"),
            "output_sha256": authority.generation_output_sha256,
            "artifact_manifest_sha256": _automated_authority_sha256(root),
            "limitations": [
                "Semantic support is estimated by a Gold-grounded model judge.",
                "Repeated passes from one model snapshot measure repeatability, not independent annotator reliability.",
                "Results inherit Gold Evidence coverage and rubric limitations.",
            ],
        },
    )
    case_metrics = "".join(
        _canonical_json({"evaluation_method": EVALUATION_METHOD, **item}) + "\n"
        for item in statistics["case_metrics"]
    )
    return {
        "case-metrics.jsonl": case_metrics,
        "aggregate.json": _canonical_json(aggregate) + "\n",
        "confidence-intervals.json": _canonical_json(confidence) + "\n",
        "report.md": report,
        "resume-evidence.md": resume,
    }


def seal_automated_citation_package(prepared: Path, output: Path) -> dict[str, object]:
    """Score and seal a complete automated authority without provider access."""

    if output.exists():
        raise AutomatedJudgeError("automated citation package output already exists")
    _automated_statistics(prepared)
    builder = EvidencePackageBuilder(output)
    source_names = AUTOMATED_PACKAGE_ARTIFACTS - {
        "raw-rankings.jsonl",
        "case-metrics.jsonl",
        "aggregate.json",
        "confidence-intervals.json",
        "report.md",
        "resume-evidence.md",
    }
    for name in sorted(source_names):
        source = prepared / name
        if not source.is_file():
            raise AutomatedJudgeError(f"automated authority is missing: {name}")
        builder.write_text(name, source.read_text(encoding="utf-8"))
    builder.write_text("raw-rankings.jsonl", "")
    for name, content in _automated_projections(output).items():
        builder.write_text(name, content)
    return builder.seal(
        package_kind="citation_baseline",
        required_artifacts=AUTOMATED_PACKAGE_ARTIFACTS,
        manifest_metadata={"evaluation_method": EVALUATION_METHOD},
    )


def recompute_automated_citation_package(package: Path, output: Path) -> list[str]:
    manifest = verify_evidence_package(package)
    if (
        manifest.get("package_kind") != "citation_baseline"
        or manifest.get("evaluation_method") != EVALUATION_METHOD
        or frozenset(manifest.get("required_artifacts", ()))
        != AUTOMATED_PACKAGE_ARTIFACTS
    ):
        raise AutomatedJudgeError("automated citation package method is invalid")
    validate_automated_judge_authorities(package)
    if output.exists():
        raise AutomatedJudgeError("automated recompute output already exists")
    output.mkdir(parents=True)
    projections = _automated_projections(package)
    for name, content in projections.items():
        _atomic_write(output / name, content)
    return [
        name
        for name, content in projections.items()
        if (package / name).read_bytes() != content.encode("utf-8")
    ]


def verify_automated_citation_package(package: Path) -> dict[str, object]:
    manifest = verify_evidence_package(package)
    with tempfile.TemporaryDirectory(prefix="citation-automated-verify-") as temporary:
        mismatches = recompute_automated_citation_package(
            package, Path(temporary) / "projections"
        )
    if mismatches:
        raise AutomatedJudgeError("automated citation projections changed")
    prose = "\n".join(
        (package / name).read_text(encoding="utf-8").lower()
        for name in ("report.md", "resume-evidence.md")
    )
    if any(
        phrase in prose
        for phrase in (
            "human-reviewed",
            "human reviewed",
            "inter-rater",
            "cohen's kappa",
            "human adjudication",
        )
    ):
        raise AutomatedJudgeError("automated citation prose contains a human-review claim")
    dataset = _read_json(package / "dataset-manifest.json")
    authority = AutomatedJudgeAuthority.model_validate(
        _read_json(package / "automated-judge-authority.json")
    )
    if dataset.get("data_kind") != authority.data_kind:
        raise AutomatedJudgeError("synthetic or real data kind was relabeled")
    return manifest


__all__ = [
    "AUTOMATED_JUDGE_PROMPT_SHA256",
    "AUTOMATED_JUDGE_RUBRIC_SHA256",
    "AUTOMATED_PACKAGE_ARTIFACTS",
    "AutomatedAssertionDecision",
    "AutomatedJudgeAuthority",
    "AutomatedJudgeError",
    "AutomatedJudgeInput",
    "AutomatedJudgePass",
    "AutomatedJudgeProvider",
    "DashScopeAutomatedJudgeProvider",
    "EVALUATION_METHOD",
    "GENERATION_MODEL",
    "JudgePassage",
    "JudgeProviderResult",
    "inspect_frozen_generation",
    "recompute_automated_citation_package",
    "run_automated_judge",
    "seal_automated_citation_package",
    "validate_automated_judge_authorities",
    "verify_automated_citation_package",
]
