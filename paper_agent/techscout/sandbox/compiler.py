"""Compile structured PoC plans into immutable allowlisted argv."""

from paper_agent.techscout.models import Candidate, PocPlan
from paper_agent.techscout.errors import FailureCode
from paper_agent.techscout.sandbox.recipes import RecipeRegistry, UnsupportedRecipeError
from paper_agent.techscout.sandbox.types import (
    CompilationDisposition,
    CompilationResult,
    CompiledCommand,
    PocStage,
)


class PocCompiler:
    def __init__(self, registry: RecipeRegistry | None = None) -> None:
        self._registry = registry or RecipeRegistry()

    def compile(
        self,
        plan: PocPlan,
        candidate: Candidate,
        stage: PocStage,
    ) -> CompiledCommand:
        if not plan.trusted:
            raise UnsupportedRecipeError(
                "untrusted PoC plan must remain research-only"
            )
        if candidate.candidate_id != plan.candidate_id:
            raise UnsupportedRecipeError("PoC plan candidate does not match candidate")

        recipe = self._registry.get(plan.recipe_id)
        if candidate.package_name != recipe.package_name:
            raise UnsupportedRecipeError("candidate package does not match reviewed recipe")
        if candidate.name.casefold() not in recipe.candidate_names:
            raise UnsupportedRecipeError("candidate name does not match reviewed recipe")
        unknown_checks = set(plan.checks) - recipe.checks
        if unknown_checks:
            raise UnsupportedRecipeError(
                f"recipe does not review checks: {', '.join(sorted(unknown_checks))}"
            )
        command = recipe.commands[stage]
        return CompiledCommand(
            poc_plan_id=plan.poc_plan_id,
            candidate_id=plan.candidate_id,
            recipe_id=recipe.recipe_id,
            stage=stage,
            argv=command.argv,
            image=recipe.image,
            network_access=command.network_access,
        )

    def compile_or_research_only(
        self,
        plan: PocPlan,
        candidate: Candidate,
        stage: PocStage,
    ) -> CompilationResult:
        """Return an explicit research-only disposition for every unsafe plan."""
        try:
            command = self.compile(plan, candidate, stage)
        except UnsupportedRecipeError as exc:
            return CompilationResult(
                disposition=CompilationDisposition.RESEARCH_ONLY,
                failure_code=FailureCode.POC_RECIPE_UNSUPPORTED,
                reason=str(exc),
            )
        return CompilationResult(
            disposition=CompilationDisposition.EXECUTABLE,
            command=command,
            reason="PoC plan matched a reviewed allowlisted recipe.",
        )
