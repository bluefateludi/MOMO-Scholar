# V1 support matrix and security boundary

## Support matrix

| Family/candidate | Research | Reviewed PoC recipe | Recommendation eligibility | Status |
|---|---|---|---|---|
| Python vector stores for local RAG | Frozen evidence today; bounded live adapters exist but are not Web-wired | Only the closed registry | Yes, when every hard constraint and deterministic gate passes under a non-synthetic authority | V1 family |
| Chroma | Yes | `recipe:chroma-local@1` | Yes | Supported |
| Qdrant Local | Yes | `recipe:qdrant-local@1` | Yes | Supported |
| pgvector without a trusted PostgreSQL fixture | Yes | None | No | Research-only |
| Unknown candidates or other component families | Safe evidence may be collected | None unless added by reviewed decision | No | Research-only or out of scope |

“Supported” means TechScout has a reviewed small compatibility recipe and gate contract. It does not mean production throughput, scale, durability, operations, security, or total-cost certification. Promoting pgvector or another family requires a reviewed fixture and an explicit decision update.

## What the reviewed recipes check

The closed recipes pin package identities and versions and cover installation/import plus local persistence, upsert, query, and metadata filtering behavior. Test execution is networkless. Unknown installation commands are never generated from model text.

## Sandbox boundary

The Docker CLI runner constructs explicit argv; it does not use a shell. The configured boundary includes:

- a reviewed image and recipe ID;
- CPU, memory, PID, disk, temporary-filesystem, output-size, and wall-time limits;
- read-only root filesystem, dropped capabilities, and `no-new-privileges`;
- a resolved run workspace constrained beneath the configured workspace root;
- no test-stage network;
- installation network only when a dedicated externally enforced destination allowlist is supplied;
- bounded stdout/stderr and forced container cleanup on timeout;
- no forwarded provider secrets.

An absent Docker daemon, missing enforced install network, unsupported recipe, timeout, or non-zero exit becomes a typed unavailable/failed/research-only result. It is not silently converted into a compatibility claim.

## Tool and network boundary

MCP calls must pass both the active Skill allowlist and the local policy allowlist, and inputs/outputs are schema-validated. The planned live boundary is limited to search, safe HTTPS fetch, read-only GitHub inspection, and reviewed smoke execution. URL policy rejects unsafe schemes, credentials, non-approved domains where constrained, and private/loopback/link-local destinations after resolution. Response sizes and timeouts are bounded, and cache fallback remains visible in provenance.

The local MCP server is the tool boundary; MCP annotations are not treated as authorization. Arbitrary remote MCP servers, unrestricted browser/shell access, and dynamically generated Skills are outside V1.

## Human approval and Web boundary

Normal read-only research and reviewed sandbox checks do not interrupt. Writes outside the run workspace, deletion, untrusted commands, non-approved network destinations, host mounts/secrets, destructive operations, or external mutation require a policy approval; unavailable approval defaults to denial.

The Web server is intended for a single local user. It enforces same-origin requests, bounded JSON request bodies, no-store API responses, content-type checks, CSP, frame denial, artifact allowlists, and sanitized cursor-bounded Trace projections. It has no authentication or multi-tenant isolation, so loopback is the safe default.

## Explicit limitations and future work

- The current Web Fast Demo is synthetic even though it uses real orchestration seams.
- Live provider and real Docker execution are not connected to the Web executor.
- The `verified` mode is deliberately limited rather than falsely green.
- pgvector has no trusted PostgreSQL fixture.
- No general arbitrary-component installer, remote MCP marketplace, cloud deployment, login, multi-user authorization, or production-scale benchmark exists.
- Final quality, latency, recovery, retrieval, token, cost, and browser measurements are `PENDING_FINAL_AUTHORITY`.
