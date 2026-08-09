from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from paper_agent.techscout.eval.faults import FaultPlan
from paper_agent.techscout.models import NonEmptyStr, TechScoutModel


class SuiteProfile(str, Enum):
    SMOKE = "smoke"
    FINAL = "final"


class CaseKind(str, Enum):
    END_TO_END = "end_to_end"
    RETRIEVAL = "retrieval"
    FAULT = "fault"


class CacheMode(str, Enum):
    COLD_LIVE = "cold_live"
    WARM_CACHE = "warm_cache"
    OFFLINE = "offline"


class HarnessVariant(str, Enum):
    V0 = "v0"
    V1 = "v1"


class EvaluationCase(TechScoutModel):
    schema_version: Literal["techscout-eval-case-v1"]
    fixture_kind: Literal["synthetic_frozen_evaluation"]
    case_id: NonEmptyStr
    kind: CaseKind
    source_fixture: NonEmptyStr
    cache_mode: CacheMode
    supports_poc: bool = False
    fault_plan: FaultPlan | None = None
    expected_contract: dict[NonEmptyStr, bool | str | int]
    observed_metrics: dict[NonEmptyStr, object] = Field(default_factory=dict, max_length=0)

    @model_validator(mode="after")
    def validate_kind(self) -> "EvaluationCase":
        if self.kind is CaseKind.END_TO_END and self.cache_mode is CacheMode.OFFLINE:
            raise ValueError("end-to-end case requires cold-live or warm-cache mode")
        if self.kind is not CaseKind.END_TO_END and self.cache_mode is not CacheMode.OFFLINE:
            raise ValueError("retrieval and fault cases are offline")
        if self.kind is CaseKind.FAULT and self.fault_plan is None:
            raise ValueError("fault case requires a deterministic fault plan")
        if self.kind is not CaseKind.FAULT and self.fault_plan is not None:
            raise ValueError("only fault cases accept a fault plan")
        return self


class ExecutionPolicy(TechScoutModel):
    model: NonEmptyStr
    temperature: float = Field(ge=0)
    search_snapshot_id: NonEmptyStr
    workers: int = Field(ge=1, le=4)
    timeout_seconds: int = Field(ge=1, le=120)
    max_infrastructure_reruns: int = Field(ge=0, le=1)
    tuning_iterations: Literal[0] = 0


class SuiteDefinition(TechScoutModel):
    schema_version: Literal["techscout-eval-suite-v1"]
    suite_id: NonEmptyStr
    profile: SuiteProfile
    case_files: tuple[NonEmptyStr, ...]
    executor_version: NonEmptyStr
    execution_policy: ExecutionPolicy

    @model_validator(mode="after")
    def unique_case_files(self) -> "SuiteDefinition":
        if len(self.case_files) != len(set(self.case_files)):
            raise ValueError("suite case files must be unique")
        return self


class EvaluationEnvironment(TechScoutModel):
    git_dirty: Literal[False]
    models: dict[NonEmptyStr, NonEmptyStr]
    executor_version: NonEmptyStr


class TaskExecutionResult(TechScoutModel):
    report_schema_valid: bool
    hard_constraints_addressed: bool
    required_evidence_available: bool
    poc_result_present: bool
    validation_gate_passed: bool
    artifacts_and_trace_complete: bool
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    tool_call_schema_valid_count: int = Field(ge=0)
    tool_call_execution_success_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    recovery_attempted: bool = False
    recovery_succeeded: bool | None = None
    recovery_stages: int = Field(default=0, ge=0, le=1)
    retry_count: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "TaskExecutionResult":
        if not (
            self.tool_call_schema_valid_count <= self.tool_call_count
            and self.tool_call_execution_success_count <= self.tool_call_count
        ):
            raise ValueError("tool-call successes cannot exceed tool-call count")
        if self.recovery_succeeded is not None and not self.recovery_attempted:
            raise ValueError("recovery outcome requires one recovery attempt")
        return self


class RetrievalExecutionResult(TechScoutModel):
    retrieved_source_ids: tuple[NonEmptyStr, ...]
    relevant_source_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expected_version_match: bool
    actual_version_match: bool


class FaultExecutionResult(TechScoutModel):
    injected_failure_code: NonEmptyStr
    recovery_succeeded: bool
    recovery_stages: int = Field(ge=1, le=1)
    retry_count: int = Field(ge=0, le=1)


class TaskRunObservation(TechScoutModel):
    case_id: NonEmptyStr
    harness_variant: HarnessVariant
    cache_mode: CacheMode
    latency_ms: int = Field(ge=0)
    supports_poc: bool
    result: TaskExecutionResult

    @property
    def task_success(self) -> bool:
        return all(
            (
                self.result.report_schema_valid,
                self.result.hard_constraints_addressed,
                self.result.required_evidence_available,
                not self.supports_poc or self.result.poc_result_present,
                self.result.validation_gate_passed,
                self.result.artifacts_and_trace_complete,
            )
        )

    @property
    def first_pass_success(self) -> bool:
        return self.task_success and not self.result.recovery_attempted


class LatencySummary(TechScoutModel):
    count: int = Field(ge=0)
    p50_ms: int | None = Field(default=None, ge=0)
    p95_ms: int | None = Field(default=None, ge=0)


class TaskMetricSummary(TechScoutModel):
    task_count: int = Field(ge=0)
    task_success_count: int = Field(ge=0)
    first_pass_success_count: int = Field(ge=0)
    recovery_success_count: int = Field(ge=0)
    recovery_attempt_count: int = Field(ge=0)
    tool_call_schema_success_count: int = Field(ge=0)
    tool_call_execution_success_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    prompt_tokens_per_successful_task: float | None = Field(default=None, ge=0)
    total_tokens_per_successful_task: float | None = Field(default=None, ge=0)
    estimated_cost_per_successful_task: float | None = Field(default=None, ge=0)
    latency: dict[Literal["cold_live", "warm_cache"], LatencySummary]


class EvaluationSummary(TechScoutModel):
    suite_id: NonEmptyStr
    profile: SuiteProfile
    e2e_case_count: int = Field(ge=0)
    e2e_run_count: int = Field(ge=0)
    retrieval_case_count: int = Field(ge=0)
    fault_case_count: int = Field(ge=0)
    fault_recovery_success_count: int = Field(ge=0)
    fault_recovery_attempt_count: int = Field(ge=0)
    retrieval_recall_at_5: float | None = Field(default=None, ge=0, le=1)
    version_filter_accuracy: float | None = Field(default=None, ge=0, le=1)
    average_fault_recovery_stages: float | None = Field(default=None, ge=0, le=1)
    task_metrics: dict[HarnessVariant, TaskMetricSummary]


PROFILE_COUNTS = {
    SuiteProfile.SMOKE: (3, 0, 0),
    SuiteProfile.FINAL: (12, 40, 8),
}
