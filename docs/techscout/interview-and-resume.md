# Interview story and STAR resume drafts

These drafts separate engineering facts from measured outcomes. Replace only the `PENDING_FINAL_AUTHORITY` fields after the sealed final Eval and Browser authorities pass the checks in [final-delivery.md](final-delivery.md). Until then, use the qualitative version in conversation and do not invent percentages, latencies, costs, pass counts, or user-study impact.

## Ninety-second project story

MOMO Scholar had reusable retrieval, Evidence, trace, evaluation, API, and Web infrastructure, but its fixed paper-survey workflow did not demonstrate a general bounded agent making tool and recovery decisions. I reframed the product around a concrete developer problem: choosing open-source Python AI components under environment and compatibility constraints.

I kept the proven infrastructure and introduced strict TechScout domain/state contracts, a bounded LangGraph Harness, stage-specific runtime Skills, a real local MCP client/server boundary, a closed Docker recipe registry, deterministic publication gates, checkpoint-linked failed-stage recovery, and sanitized sealed traces. The key design choice was to separate model judgment from safety and authority: models can plan and review, but code controls tool permissions, command compilation, budgets, terminalization, and whether a recommendation is publishable.

I also made incomplete integration visible. The current Fast Demo exercises real orchestration seams over frozen synthetic inputs; the Verified/Live request is explicitly limited until provider and Docker modules are connected end to end. Unsupported candidates such as pgvector remain research-only. The final result is evaluated against a fixed V0/V1 TechScout comparison, with resume claims projected only from a verified sealed package. Final measured outcome: `PENDING_FINAL_AUTHORITY`.

## Deep-dive prompts

- **Why not a free-form ReAct agent?** Bounded state transitions, strict schemas, checkpoint recovery, and deterministic gates make failure behavior inspectable and prevent an LLM from expanding its own authority.
- **Why MCP if the server is local?** It proves a real typed client/server tool boundary and keeps Skill selection separate from local permission policy; the intersection must allow a call.
- **Why research-only instead of “failed”?** Missing a trusted recipe is missing verification authority, not evidence that the component is incompatible.
- **Why two SQLite databases?** Product queue/events and LangGraph checkpoint tables have different ownership and lifecycle; separation prevents orchestration internals from becoming product authority.
- **What is the hardest honesty constraint?** A successful synthetic Fast terminal state is acceptance evidence for the vertical slice, not a live component recommendation or final evaluation result.

## Four STAR resume drafts

### STAR 1 — Product and agent architecture

- **Situation:** A citation-grounded Scholar pipeline had strong infrastructure but a fixed workflow and a weaker component-selection product story.
- **Task:** Reframe it into an auditable agent for Python AI dependency decisions without discarding provenance or creating an unbounded autonomous shell.
- **Action:** Designed strict request/state/report contracts and a bounded LangGraph Harness with stage Skills, local MCP tool routing, separate SQLite checkpoints, deterministic terminal gates, and immutable artifacts.
- **Result:** Delivered an end-to-end local vertical slice with measured V1 Task Success `PENDING_FINAL_AUTHORITY` versus V0 `PENDING_FINAL_AUTHORITY`; authority: `PENDING_FINAL_AUTHORITY`.

Resume-line draft: “Refactored a fixed RAG literature pipeline into a bounded LangGraph/MCP component-research agent, combining typed state, stage Skills, checkpointing, deterministic publication gates, and sealed artifacts; improved TechScout Task Success from `PENDING_FINAL_AUTHORITY` to `PENDING_FINAL_AUTHORITY` on a fixed sealed evaluation.”

### STAR 2 — Safety and reproducible verification

- **Situation:** Model-generated install commands and host execution would make open-source component comparisons unsafe and irreproducible.
- **Task:** Allow useful local verification while preventing arbitrary shell, network, mount, and secret access.
- **Action:** Built a closed Chroma/Qdrant Local recipe registry, structured PoC compiler, explicit Docker argv runner, resource/no-network controls, output bounds, and research-only downgrade for pgvector/unknown recipes.
- **Result:** Achieved tool schema/execution success `PENDING_FINAL_AUTHORITY` and supported-PoC acceptance `PENDING_FINAL_AUTHORITY`; authority: `PENDING_FINAL_AUTHORITY`.

Resume-line draft: “Implemented a fail-closed Docker PoC boundary with reviewed vector-store recipes, explicit argv compilation, resource/egress limits, and research-only downgrade for unknown candidates, reaching `PENDING_FINAL_AUTHORITY` verified tool execution on the sealed suite.”

### STAR 3 — Reliability, recovery, and observability

- **Situation:** Search, tool, dependency, PoC, and report failures could otherwise restart whole runs, duplicate work, or hide why a result degraded.
- **Task:** Make failures bounded, locally recoverable, and reviewable without corrupting the original execution record.
- **Action:** Added typed failure classification, checkpoint-linked failed-stage recovery, budget/deadline terminalization, append-only event projections, sanitized sealed Trace events, and partial-result preservation.
- **Result:** Measured Recovery Success `PENDING_FINAL_AUTHORITY`, First-pass Success `PENDING_FINAL_AUTHORITY`, and recovery-stage overhead `PENDING_FINAL_AUTHORITY`; authority: `PENDING_FINAL_AUTHORITY`.

Resume-line draft: “Added typed, checkpoint-linked recovery that reruns only the failed agent stage and preserves the original sealed Trace, producing `PENDING_FINAL_AUTHORITY` recovery success with `PENDING_FINAL_AUTHORITY` average recovery-stage overhead.”

### STAR 4 — Evaluation, latency, and delivery evidence

- **Situation:** Planning targets, synthetic demos, and historical Scholar metrics could be mistaken for TechScout product results.
- **Task:** Build a claim pipeline that separates smoke acceptance, live behavior, and final resume evidence.
- **Action:** Defined fixed V0/V1 contracts, cold-live versus warm-cache metrics, offline retrieval/fault evaluation, sealed package generation, automatically projected resume evidence, and browser acceptance tied to an exact build.
- **Result:** Recorded Retrieval Recall@5 `PENDING_FINAL_AUTHORITY`, cold-live p50/p95 `PENDING_FINAL_AUTHORITY`, warm-cache p50/p95 `PENDING_FINAL_AUTHORITY`, tokens/cost per successful task `PENDING_FINAL_AUTHORITY`, and Browser acceptance `PENDING_FINAL_AUTHORITY`; authority: `PENDING_FINAL_AUTHORITY`.

Resume-line draft: “Built a sealed evaluation and delivery-evidence pipeline separating synthetic acceptance from live results, measuring Recall@5 `PENDING_FINAL_AUTHORITY`, cold/warm latency `PENDING_FINAL_AUTHORITY`, and per-success token/cost `PENDING_FINAL_AUTHORITY` without relabeling historical metrics.”

## Claims to avoid

- Do not say Fast is live, provider-backed, or Docker-backed at the current baseline.
- Do not say existing live/Docker modules are end-to-end product integration.
- Do not call research-only a failed compatibility benchmark.
- Do not quote roadmap targets as achievements.
- Do not reuse MOMO Scholar retrieval/citation/browser results as TechScout outcomes.
- Do not replace a pending value with an estimate or an unsealed local observation.
