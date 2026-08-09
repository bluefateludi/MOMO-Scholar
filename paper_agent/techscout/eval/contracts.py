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


class ExpectedContract(TechScoutModel):
    contract_kind: CaseKind
    terminal_status: Literal["completed", "completed_with_limitations", "failed"] | None = None
    task_success: bool | None = None
    first_pass_success: bool | None = None
    maximum_recovery_attempts: Literal[0, 1] = 0
    relevant_source_ids: tuple[NonEmptyStr, ...] = ()
    expected_version_match: bool | None = None
    injected_failure_code: NonEmptyStr | None = None
    recovery_succeeded: bool | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "ExpectedContract":
        if self.contract_kind is CaseKind.END_TO_END and None in {
            self.terminal_status,
            self.task_success,
            self.first_pass_success,
        }:
            raise ValueError("end-to-end contract requires terminal and success expectations")
        if self.contract_kind is CaseKind.RETRIEVAL and (
            not self.relevant_source_ids or self.expected_version_match is None
        ):
            raise ValueError("retrieval contract requires relevance and version expectations")
        if self.contract_kind is CaseKind.FAULT and (
            self.injected_failure_code is None or self.recovery_succeeded is None
        ):
            raise ValueError("fault contract requires failure and recovery expectations")
        return self


class EvaluationCase(TechScoutModel):
    schema_version: Literal["techscout-eval-case-v1"]
    fixture_kind: Literal["synthetic_frozen_evaluation"]
    case_id: NonEmptyStr
    kind: CaseKind
    source_fixture: NonEmptyStr
    cache_mode: CacheMode
    supports_poc: bool = False
    fault_plan: FaultPlan | None = None
    expected_contract: ExpectedContract
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
        if self.expected_contract.contract_kind is not self.kind:
            raise ValueError("expected contract kind must match case kind")
        return self


class FrozenRetrievalObservation(TechScoutModel):
    retrieved_source_ids: tuple[NonEmptyStr, ...]
    relevant_source_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expected_version_match: bool
    actual_version_match: bool


class FrozenFaultObservation(TechScoutModel):
    stage: NonEmptyStr


class FrozenOfflineObservationSource(TechScoutModel):
    schema_version: Literal["techscout-final-observations-v1"]
    retrieval_observations: dict[NonEmptyStr, FrozenRetrievalObservation]
    fault_observations: dict[NonEmptyStr, FrozenFaultObservation]


class ExecutionPolicy(TechScoutModel):
    model: NonEmptyStr
    temperature: float = Field(ge=0)
    search_snapshot_id: NonEmptyStr
    workers: int = Field(ge=1, le=4)
    timeout_seconds: int = Field(ge=1, le=120)
    total_timeout_seconds: int = Field(default=3600, ge=1, le=3600)
    max_infrastructure_reruns: int = Field(ge=0, le=1)
    tuning_iterations: Literal[0] = 0


class SuiteDefinition(TechScoutModel):
    schema_version: Literal["techscout-eval-suite-v1"]
    suite_id: NonEmptyStr
    profile: SuiteProfile
    case_files: tuple[NonEmptyStr, ...]
    executor_version: NonEmptyStr
    execution_policy: ExecutionPolicy
    fixture_case_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def unique_case_files(self) -> "SuiteDefinition":
        if len(self.case_files) != len(set(self.case_files)):
            raise ValueError("suite case files must be unique")
        return self


class EvaluationEnvironment(TechScoutModel):
    git_dirty: Literal[False]
    models: dict[NonEmptyStr, NonEmptyStr]
    executor_version: NonEmptyStr
    baseline_git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    execution_git_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    network_policy: Literal["offline", "live"] | None = None


class TaskExecutionResult(TechScoutModel):
    terminal_status: Literal["completed", "completed_with_limitations", "failed"]
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


def validate_expected_contract(
    case: EvaluationCase,
    observation: TaskRunObservation,
) -> None:
    expected = case.expected_contract
    assert expected.terminal_status is not None
    assert expected.task_success is not None
    assert expected.first_pass_success is not None
    actual = (
        observation.result.terminal_status,
        observation.task_success,
        observation.first_pass_success,
        int(observation.result.recovery_attempted),
    )
    declared = (
        expected.terminal_status,
        expected.task_success,
        expected.first_pass_success,
        expected.maximum_recovery_attempts,
    )
    if actual != declared:
        raise ValueError(f"case {case.case_id} did not satisfy its frozen expected contract")


def validate_retrieval_contract(
    case: EvaluationCase,
    result: RetrievalExecutionResult,
) -> None:
    expected = case.expected_contract
    if (
        result.relevant_source_ids != expected.relevant_source_ids
        or result.expected_version_match != expected.expected_version_match
    ):
        raise ValueError(f"case {case.case_id} did not satisfy its retrieval contract")


def validate_fault_contract(case: EvaluationCase, result: FaultExecutionResult) -> None:
    expected = case.expected_contract
    if (
        result.injected_failure_code != expected.injected_failure_code
        or result.recovery_succeeded != expected.recovery_succeeded
    ):
        raise ValueError(f"case {case.case_id} did not satisfy its fault contract")


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
    average_recovery_stages: float | None = Field(default=None, ge=0, le=1)
    average_retries: float = Field(ge=0, le=1)
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
    average_fault_retries: float | None = Field(default=None, ge=0, le=1)
    task_metrics: dict[HarnessVariant, TaskMetricSummary]


PROFILE_COUNTS = {
    SuiteProfile.SMOKE: (3, 0, 0),
    SuiteProfile.FINAL: (12, 40, 8),
}
