import asyncio
import json
from datetime import datetime, timedelta, timezone

from paper_agent.techscout.harness.stages import StageArtifacts, StageDeadline, StageResult
from paper_agent.techscout.models import (
    CacheStatus,
    Candidate,
    EnvironmentSpec,
    ResearchPlan,
    ResearchRequest,
    ToolCall,
    ToolResult,
    ToolStatus,
)
from paper_agent.techscout.observability.adapters import (
    TracingSkillRouter,
    TracingStageServices,
    TracingToolRuntime,
)
from paper_agent.techscout.observability.recorder import TechScoutTraceRecorder
from paper_agent.techscout.runtime_skills import fixed_skill_registry
from paper_agent.techscout.state import ResearchStage, ResearchState, RunBudget


NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def _state() -> ResearchState:
    request = ResearchRequest(
        run_id="run:trace-adapter",
        question="Choose a vector store.",
        project_context="Local RAG.",
        environment=EnvironmentSpec(
            python_version="3.11",
            operating_system="linux",
            deployment="local",
        ),
        hard_constraints=("metadata filtering",),
        candidates=(Candidate(candidate_id="candidate:qdrant", name="Qdrant"),),
    )
    return ResearchState(
        run_id=request.run_id,
        request=request,
        budget=RunBudget(deadline_at=NOW + timedelta(minutes=1)),
        stage=ResearchStage.PLAN_RESEARCH,
        step_count=0,
        tool_call_count=0,
        token_count=0,
        recovery_count=0,
        candidate_ids=("candidate:qdrant",),
        source_ids=(),
        evidence_ids=(),
        poc_result_ids=(),
        failures=(),
    )


class PlanStage:
    def execute(self, stage, state, artifacts, deadline):
        plan = ResearchPlan(
            plan_id="plan:trace-adapter",
            investigation_dimensions=("compatibility",),
            required_capabilities=("official-doc-research",),
            planned_evidence=("official docs",),
            poc_intent="verify locally",
        )
        return StageResult(
            state=state.model_copy(update={"stage": ResearchStage.RESEARCH_CANDIDATES, "plan": plan})
        )


class SuccessfulTool:
    async def discover_tools(self, skill_id=None):
        return ("web.search",)

    async def invoke(self, call):
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolStatus.SUCCEEDED,
            latency_ms=5,
            cache_status=CacheStatus.HIT,
        )


def test_stage_skill_and_tool_adapters_emit_structured_events(tmp_path):
    path = tmp_path / "traces.jsonl"
    trace = TechScoutTraceRecorder(path, run_id="run:trace-adapter", now=lambda: NOW)
    state = _state()
    TracingStageServices(PlanStage(), trace).execute(
        ResearchStage.PLAN_RESEARCH,
        state,
        StageArtifacts(),
        StageDeadline(deadline_at=NOW + timedelta(seconds=10), timeout_seconds=10),
    )
    TracingSkillRouter(fixed_skill_registry(), trace).route(
        "official-doc-research",
        ResearchStage.RESEARCH_CANDIDATES,
        selection_id="selection:trace-adapter",
        reason="need official evidence",
    )
    asyncio.run(
        TracingToolRuntime(SuccessfulTool(), trace).invoke(
            ToolCall(
                tool_call_id="tool-call:trace-adapter",
                tool_name="web.search",
                skill_id="skill:official-doc-research@1",
                arguments={
                    "query": "secret-free",
                    "limit": 3,
                    "api_key": "must-not-persist",
                    "prompt": "must-not-persist",
                },
            )
        )
    )
    trace.seal()

    names = {
        json.loads(line).get("name")
        for line in path.read_text(encoding="utf-8").splitlines()
    }
    assert {
        "state.transitioned",
        "plan.created",
        "skill.selected",
        "mcp.tool.started",
        "mcp.tool.finished",
        "tool.started",
        "tool.finished",
    } <= names
    content = path.read_text(encoding="utf-8")
    assert "api_key" not in content
    assert "prompt" not in content
    assert "must-not-persist" not in content
