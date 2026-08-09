from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

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


class TaskSuccessChecks(TechScoutModel):
    report_schema_valid: bool
    hard_constraints_addressed: bool
    required_evidence_available: bool
    expected_poc_present: bool
    validation_gate_passed: bool
    artifacts_and_trace_complete: bool

    @property
    def passed(self) -> bool:
        return all(self.model_dump().values())


class TaskRunObservation(TechScoutModel):
    harness_variant: HarnessVariant
    cache_mode: CacheMode
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    task_checks: TaskSuccessChecks
    first_pass_success: bool
    recovery_attempted: bool = False
    recovery_succeeded: bool | None = None
    recovery_stages: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_recovery_observation(self) -> "TaskRunObservation":
        if self.cache_mode is CacheMode.OFFLINE:
            raise ValueError("end-to-end observation requires cold-live or warm-cache mode")
        if self.recovery_succeeded is not None and not self.recovery_attempted:
            raise ValueError("recovery outcome requires a recovery attempt")
        return self


class EvaluationCase(TechScoutModel):
    schema_version: Literal["techscout-eval-case-v1"]
    fixture_kind: Literal["synthetic_frozen_evaluation"]
    case_id: NonEmptyStr
    kind: CaseKind
    runs: tuple[TaskRunObservation, ...] = ()
    retrieved_source_ids: tuple[NonEmptyStr, ...] = ()
    relevant_source_ids: tuple[NonEmptyStr, ...] = ()
    expected_version_match: bool | None = None
    actual_version_match: bool | None = None
    injected_failure_code: NonEmptyStr | None = None
    recovery_attempted: bool = False
    recovery_succeeded: bool | None = None
    recovery_stages: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_kind_contract(self) -> "EvaluationCase":
        if self.kind is CaseKind.END_TO_END:
            if not self.runs:
                raise ValueError("end-to-end case requires objective run observations")
            variants = [run.harness_variant for run in self.runs]
            if len(variants) != len(set(variants)):
                raise ValueError("end-to-end run variants must be unique")
        elif self.kind is CaseKind.RETRIEVAL:
            if self.runs:
                raise ValueError("retrieval case cannot contain Harness runs")
            if not self.relevant_source_ids:
                raise ValueError("retrieval case requires relevant source identifiers")
            if self.expected_version_match is None or self.actual_version_match is None:
                raise ValueError("retrieval case requires version-filter observations")
        else:
            if self.runs:
                raise ValueError("fault case cannot contain Harness runs")
            if (
                self.injected_failure_code is None
                or not self.recovery_attempted
                or self.recovery_succeeded is None
            ):
                raise ValueError("fault case requires an injected recovery observation")
        if self.recovery_succeeded is not None and not self.recovery_attempted:
            raise ValueError("recovery outcome requires a recovery attempt")
        return self


class SuiteDefinition(TechScoutModel):
    schema_version: Literal["techscout-eval-suite-v1"]
    suite_id: NonEmptyStr
    profile: SuiteProfile
    case_files: tuple[NonEmptyStr, ...]
    executor_version: NonEmptyStr
    execution_policy: "ExecutionPolicy"

    @model_validator(mode="after")
    def unique_case_files(self) -> "SuiteDefinition":
        if len(self.case_files) != len(set(self.case_files)):
            raise ValueError("suite case files must be unique")
        return self


class ExecutionPolicy(TechScoutModel):
    model: NonEmptyStr
    temperature: float = Field(ge=0)
    search_snapshot_id: NonEmptyStr
    workers: int = Field(ge=1, le=4)
    timeout_seconds: int = Field(ge=1, le=120)
    max_infrastructure_reruns: int = Field(ge=0, le=1)
    tuning_iterations: Literal[0] = 0


class EvaluationEnvironment(TechScoutModel):
    git_dirty: Literal[False]
    models: dict[NonEmptyStr, NonEmptyStr]
    executor_version: NonEmptyStr


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
    prompt_tokens_per_successful_task: float | None = Field(default=None, ge=0)
    total_tokens_per_successful_task: float | None = Field(default=None, ge=0)
    latency: dict[Literal["cold_live", "warm_cache"], LatencySummary]


class EvaluationSummary(TechScoutModel):
    suite_id: NonEmptyStr
    profile: SuiteProfile
    e2e_case_count: int = Field(ge=0)
    retrieval_case_count: int = Field(ge=0)
    fault_case_count: int = Field(ge=0)
    e2e_run_count: int = Field(ge=0)
    recovery_success_count: int = Field(ge=0)
    recovery_attempt_count: int = Field(ge=0)
    retrieval_recall_at_5: float | None = Field(default=None, ge=0, le=1)
    version_filter_accuracy: float | None = Field(default=None, ge=0, le=1)
    average_recovery_stages: float | None = Field(default=None, ge=0)
    average_retries: float | None = Field(default=None, ge=0)
    task_metrics: dict[HarnessVariant, TaskMetricSummary]


PROFILE_COUNTS = {
    SuiteProfile.SMOKE: (3, 0, 0),
    SuiteProfile.FINAL: (12, 40, 8),
}
