# Security policy

## Supported versions

MOMO TechScout is pre-1.0 software. Security fixes are made on the current `master` line and, after a v0.1.x release exists, on the latest 0.1.x patch only. Older commits, forks, unpublished artifacts, and the historical Scholar workflow do not receive security backports.

| Version | Supported |
|---|---|
| Current `master` / latest 0.1.x | Yes |
| Older 0.1.x patches | No guaranteed backports |
| Earlier development snapshots | No |

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/bluefateludi/MOMO-TechScout/security/advisories/new) when it is available. Include:

- affected commit or version and operating environment;
- the boundary involved (Web/API, provider/cache, MCP, artifact/Trace, Docker sandbox, package, or dependency);
- minimal reproduction steps and impact;
- whether secrets or user data may have been exposed;
- a safe way to contact you for follow-up.

Do not open a public issue, pull request, or discussion containing exploit details, credentials, private provider responses, or sensitive run artifacts. If private reporting is unavailable, open a public issue containing only “Security contact requested” and no vulnerability details; a maintainer can establish a private channel.

You should receive an acknowledgement within 7 days and a status update within 14 days. Resolution time depends on severity and reproducibility. Maintainers will coordinate disclosure and credit with the reporter; please avoid public disclosure until a fix or mitigation is available.

## Security boundary

The local Web service has no authentication or multi-tenant isolation and should remain loopback-only. Fast Demo is synthetic. Verified is limited to the bounded Hero Case and requires external provider/cache, Docker, and enforced install-network capacity. The Compose Web container intentionally has no Docker socket.

Reviewed sandbox recipes do not make arbitrary model-generated commands safe. Reports involving recipe escapes, path traversal, unsafe network access, secret leakage, artifact/Trace disclosure, origin bypass, denial-of-service outside documented limits, or dependency compromise are in scope. General model-quality disagreements and unsupported-candidate results are not security vulnerabilities unless they cross a deterministic safety boundary.

See [V1 support matrix and security boundary](docs/techscout/support-and-safety.md) for the complete operational contract.
