from paper_agent.techscout.observability.recorder import TechScoutTraceRecorder
from paper_agent.techscout.observability.schema import TraceEvent, TraceEventName

# Adapters are intentionally imported lazily by callers to avoid loading the Harness
# and MCP runtime for schema-only consumers.

__all__ = ["TechScoutTraceRecorder", "TraceEvent", "TraceEventName"]
