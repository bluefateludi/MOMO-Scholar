"""Fail-closed policy for destructive or host-level operations."""

from enum import Enum

from paper_agent.techscout.models import NonEmptyStr, TechScoutModel


class OperationKind(str, Enum):
    READ_RESEARCH = "read_research"
    RUN_REVIEWED_POC = "run_reviewed_poc"
    WRITE_RUN_WORKSPACE = "write_run_workspace"
    WRITE_OUTSIDE_WORKSPACE = "write_outside_workspace"
    DELETE_FILES = "delete_files"
    RUN_UNTRUSTED_COMMAND = "run_untrusted_command"
    ACCESS_UNAPPROVED_NETWORK = "access_unapproved_network"
    MOUNT_HOST_PATH = "mount_host_path"
    EXPOSE_HOST_SECRET = "expose_host_secret"
    EXTERNAL_MUTATION = "external_mutation"


class ApprovalOutcome(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class OperationRequest(TechScoutModel):
    kind: OperationKind
    description: NonEmptyStr
    allowlisted: bool = False
    approval_available: bool = False
    approval_granted: bool = False


class ApprovalDecision(TechScoutModel):
    outcome: ApprovalOutcome
    reason: NonEmptyStr


class ApprovalPolicy:
    _NORMAL = {
        OperationKind.READ_RESEARCH,
        OperationKind.WRITE_RUN_WORKSPACE,
    }
    _HIGH_RISK = set(OperationKind) - _NORMAL - {OperationKind.RUN_REVIEWED_POC}

    def evaluate(self, request: OperationRequest) -> ApprovalDecision:
        if request.kind in self._NORMAL:
            return ApprovalDecision(outcome=ApprovalOutcome.ALLOW, reason="Operation is within the run boundary.")
        if request.kind is OperationKind.RUN_REVIEWED_POC and request.allowlisted:
            return ApprovalDecision(outcome=ApprovalOutcome.ALLOW, reason="Reviewed sandbox PoC is pre-approved.")
        if request.kind is OperationKind.RUN_REVIEWED_POC:
            return ApprovalDecision(outcome=ApprovalOutcome.DENY, reason="Unreviewed PoC commands cannot execute.")
        if request.kind in self._HIGH_RISK and request.approval_granted:
            return ApprovalDecision(outcome=ApprovalOutcome.ALLOW, reason="Explicit approval was granted.")
        if request.kind in self._HIGH_RISK and request.approval_available:
            return ApprovalDecision(outcome=ApprovalOutcome.REQUIRE_APPROVAL, reason="High-risk operation requires explicit approval.")
        return ApprovalDecision(outcome=ApprovalOutcome.DENY, reason="Approval is unavailable; policy defaults to denial.")
