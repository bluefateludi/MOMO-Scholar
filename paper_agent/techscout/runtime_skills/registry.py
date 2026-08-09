from __future__ import annotations

import json
from collections.abc import Iterable

from pydantic import BaseModel

from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.models import SkillSelection, SkillSpec
from paper_agent.techscout.state import ResearchStage

from .contracts import (
    FailureDiagnosisInput,
    FailureDiagnosisOutput,
    ResearchSkillInput,
    ResearchSkillOutput,
    SkillDefinition,
    SmokeTestSkillInput,
    SmokeTestSkillOutput,
)


TOOL_NAMES = frozenset(
    {
        "web.search",
        "web.fetch",
        "github.inspect_repository",
        "sandbox.run_smoke_test",
    }
)


def fixed_skill_specs() -> tuple[SkillSpec, ...]:
    """Return the immutable V1 capability set.

    Keeping the specifications in code makes registry construction deterministic and
    prevents runtime prompt files from silently changing the security boundary.
    """

    return (
        SkillSpec(
            skill_id="skill:official-doc-research@1",
            name="official-doc-research",
            version="1",
            stage=ResearchStage.RESEARCH_CANDIDATES.value,
            instructions=(
                "Research one candidate at a time. Prefer official, versioned HTTPS "
                "documentation and retain only sources relevant to the hard constraints."
            ),
            completion_criteria=(
                "official source provenance is retained",
                "every retained fact identifies its candidate and applicable version",
            ),
            allowed_tools=("web.search", "web.fetch"),
            source_budget=5,
            tool_call_budget=6,
            step_budget=6,
            token_budget=6_000,
            handled_failure_codes=(
                FailureCode.SEARCH_TIMEOUT,
                FailureCode.SEARCH_RATE_LIMITED,
                FailureCode.SEARCH_UNAVAILABLE,
                FailureCode.PAGE_PARSING_FAILED,
            ),
        ),
        SkillSpec(
            skill_id="skill:github-project-analysis@1",
            name="github-project-analysis",
            version="1",
            stage=ResearchStage.RESEARCH_CANDIDATES.value,
            instructions=(
                "Inspect only the requested public repository. Use bounded README, "
                "release, and issue metadata to answer the current constraints."
            ),
            completion_criteria=(
                "repository identity and snapshot provenance are retained",
                "claims distinguish repository metadata from model inference",
            ),
            allowed_tools=("github.inspect_repository",),
            source_budget=5,
            tool_call_budget=4,
            step_budget=5,
            token_budget=5_000,
            handled_failure_codes=(
                FailureCode.SEARCH_RATE_LIMITED,
                FailureCode.TOOL_TIMEOUT,
                FailureCode.TOOL_UNAVAILABLE,
            ),
        ),
        SkillSpec(
            skill_id="skill:python-package-smoke-test@1",
            name="python-package-smoke-test",
            version="1",
            stage=ResearchStage.EXECUTE_POC.value,
            instructions=(
                "Execute only a trusted recipe identifier and structured checks. Never "
                "invent installation commands or submit raw shell text."
            ),
            completion_criteria=(
                "the trusted recipe and resolved version are recorded",
                "exit status, timeout state, and artifact hashes are recorded",
            ),
            allowed_tools=("sandbox.run_smoke_test",),
            source_budget=0,
            tool_call_budget=2,
            step_budget=3,
            token_budget=3_000,
            handled_failure_codes=(
                FailureCode.DEPENDENCY_CONFLICT,
                FailureCode.VERSION_CONFLICT,
                FailureCode.POC_TIMEOUT,
                FailureCode.POC_NONZERO_EXIT,
            ),
        ),
        SkillSpec(
            skill_id="skill:failure-diagnosis@1",
            name="failure-diagnosis",
            version="1",
            stage=ResearchStage.RECOVER_ONCE.value,
            instructions=(
                "Diagnose the typed failure from the last checkpoint and propose one "
                "bounded action for that failed stage only."
            ),
            completion_criteria=(
                "the diagnosis cites the typed failure and prior evidence",
                "at most one permitted recovery action is proposed",
            ),
            allowed_tools=(
                "web.fetch",
                "github.inspect_repository",
                "sandbox.run_smoke_test",
            ),
            source_budget=2,
            tool_call_budget=3,
            step_budget=4,
            token_budget=4_000,
            handled_failure_codes=(
                FailureCode.PAGE_PARSING_FAILED,
                FailureCode.TOOL_TIMEOUT,
                FailureCode.DEPENDENCY_CONFLICT,
                FailureCode.VERSION_CONFLICT,
                FailureCode.POC_TIMEOUT,
                FailureCode.POC_NONZERO_EXIT,
                FailureCode.REPORT_SCHEMA_INVALID,
                FailureCode.REPORT_EVIDENCE_INVALID,
            ),
        ),
    )


def _fixed_contract_models() -> dict[
    str, tuple[type[BaseModel], type[BaseModel]]
]:
    return {
        "official-doc-research": (ResearchSkillInput, ResearchSkillOutput),
        "github-project-analysis": (ResearchSkillInput, ResearchSkillOutput),
        "python-package-smoke-test": (SmokeTestSkillInput, SmokeTestSkillOutput),
        "failure-diagnosis": (FailureDiagnosisInput, FailureDiagnosisOutput),
    }


def fixed_skill_definitions() -> tuple[SkillDefinition, ...]:
    models = _fixed_contract_models()
    return tuple(
        SkillDefinition(
            spec=spec,
            input_model=models[spec.name][0],
            output_model=models[spec.name][1],
        )
        for spec in fixed_skill_specs()
    )


class SkillRegistry:
    def __init__(
        self, definitions: Iterable[SkillDefinition | SkillSpec]
    ) -> None:
        by_id: dict[str, SkillSpec] = {}
        by_capability: dict[str, SkillSpec] = {}
        contracts: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {}
        for item in definitions:
            if isinstance(item, SkillDefinition):
                definition = item
            else:
                models = _fixed_contract_models().get(item.name)
                if models is None:
                    raise ValueError(
                        f"skill {item.name} requires explicit typed contracts"
                    )
                definition = SkillDefinition(item, models[0], models[1])
            spec = definition.spec
            try:
                ResearchStage(spec.stage)
            except ValueError as exc:
                raise ValueError(
                    f"skill {spec.name} has unknown stage: {spec.stage}"
                ) from exc
            if spec.skill_id in by_id:
                raise ValueError(f"duplicate skill_id: {spec.skill_id}")
            if spec.name in by_capability:
                raise ValueError(f"duplicate skill capability: {spec.name}")
            unknown = set(spec.allowed_tools) - TOOL_NAMES
            if unknown:
                raise ValueError(f"skill {spec.name} allows unknown tools: {sorted(unknown)}")
            if len(spec.allowed_tools) != len(set(spec.allowed_tools)):
                raise ValueError(f"skill {spec.name} contains duplicate tools")
            by_id[spec.skill_id] = spec
            by_capability[spec.name] = spec
            contracts[spec.skill_id] = (
                definition.input_model,
                definition.output_model,
            )
        if not by_id:
            raise ValueError("skill registry must not be empty")
        self._by_id = by_id
        self._by_capability = by_capability
        self._contracts = contracts

    def all(self) -> tuple[SkillSpec, ...]:
        return tuple(self._by_id.values())

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._by_id[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {skill_id}") from exc

    def input_model(self, skill_id: str) -> type[BaseModel]:
        self.get(skill_id)
        return self._contracts[skill_id][0]

    def output_model(self, skill_id: str) -> type[BaseModel]:
        self.get(skill_id)
        return self._contracts[skill_id][1]

    def validate_input(self, skill_id: str, value: object) -> BaseModel:
        return self.input_model(skill_id).model_validate_json(_json_value(value))

    def validate_output(self, skill_id: str, value: object) -> BaseModel:
        return self.output_model(skill_id).model_validate_json(_json_value(value))

    def route(
        self,
        capability: str,
        stage: ResearchStage | str,
        *,
        selection_id: str,
        reason: str,
    ) -> SkillSelection:
        try:
            spec = self._by_capability[capability]
        except KeyError as exc:
            raise ValueError(f"unsupported capability: {capability}") from exc
        stage_value = stage.value if isinstance(stage, ResearchStage) else stage
        if spec.stage != stage_value:
            raise ValueError(
                f"capability {capability} is not valid for stage {stage_value}"
            )
        return SkillSelection(
            selection_id=selection_id,
            skill_id=spec.skill_id,
            stage=stage_value,
            reason=reason,
        )


def fixed_skill_registry() -> SkillRegistry:
    registry = SkillRegistry(fixed_skill_definitions())
    expected = {
        "official-doc-research",
        "github-project-analysis",
        "python-package-smoke-test",
        "failure-diagnosis",
    }
    actual = {skill.name for skill in registry.all()}
    if actual != expected:  # pragma: no cover - guards future accidental edits
        raise RuntimeError("fixed skill registry is incomplete")
    return registry


def _json_value(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, separators=(",", ":"))
