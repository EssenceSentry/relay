# Relay sharing review — 2026-09-15

Relay is suitable for a technical walkthrough and code review with Blend
colleagues. The live website, recorded story, and Microsoft login work. This
review covers the technical checks below and distinguishes the public synthetic
examples from live project data.

## What was checked

| Surface | Result |
| --- | --- |
| Live landing page and interactive story | Load successfully; chapter navigation and the PDF preview work |
| Browser sign-in | Microsoft SSO returns a verified Blend identity to Relay |
| API health at the configured API origin | HTTP 200 with JSON `{"status":"ok"}` |
| Unauthenticated API and MCP access | HTTP 401; no project data returned |
| OAuth authorization and MCP resource metadata | Valid JSON at the advertised endpoints |
| Deployed frontend and compatibility downloads | Compared with the checkout; all nine checked files match exactly |
| Offline tests | 185 passing tests, including SSO, authorization, API/MCP parity, idempotency, email parsing, and plugin contracts |
| Static checks | Ruff lint/format, strict Pyright, JavaScript syntax |
| Infrastructure | CDK synthesis succeeds without lookups or deployment; existing deprecation warnings remain |

The API origin comes from `config.json`. The public website serves its landing
page for unmatched paths, so `https://essencesentry.shop/healthz` is not an API
health probe. MCP resource metadata is advertised at
`/.well-known/oauth-protected-resource/mcp/`.

No new project, upload, live email, or expert-answer workflow was created during
this review. A fresh authenticated MCP token/refresh round trip and the full
email/ingestion/retrieval workflow were not replayed. The product story is a
recorded demonstration, not a fresh end-to-end test.

## Sharing and operational limits

**The homepage story uses a fictional example.** The project owner confirmed
that the Agentic Knowledge Platform document in the embedded chat is a
self-referential demonstration. Its generated “Confidential — internal sales
use” footer is template text, not evidence of confidential source material.

**Public fixtures now use synthetic content.** Five dossier fixtures and the
client-specific demonstration runbook were replaced at the project owner's
request because their public-use status was uncertain. The new dossiers and
three uploadable demo documents were authored from scratch, with invented
scenarios and figures explicitly labeled. The sample renderer no longer
requires private source documents. See [example provenance](example-provenance.md).

Earlier versions of the replaced examples require history cleanup as well.
Updating branch history does not remove existing clones or every cached GitHub
view and pull-request reference. See GitHub
[history-cleanup guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

Live project access requires Blend Microsoft SSO. The GitHub repository and
static story are public and do not require SSO. Repository visibility was not
changed by this review.

**Session revocation needs further work before broader operational use.** The
MCP broker rotates its own refresh tokens, while retaining the identity and
roles captured at sign-in. Enterprise offboarding and permission changes need
a verified session-revocation policy and an absolute reauthentication deadline.
The Microsoft cutover correctly rejects older non-SSO broker tokens; that is a
separate guarantee from ongoing upstream identity revocation.

**Dependency fixes require a deployment to reach running services.** The
repository raises the PDF parser and cryptography minimums to the patched
versions identified by GitHub alerts. The local lock uses `pypdf==6.16.1` and
`cryptography==50.0.0`; API and ingestion requirements carry matching minimums.
No service image was rebuilt or deployed during this review.

**Deployment defaults are intended for disposable infrastructure.**
`cdk.json` sets `retain_data=false`. That selects destructive removal policies,
bucket cleanup, and disabled DynamoDB point-in-time recovery. A durable rollout
needs an explicit retention/backup configuration and a tested restore procedure
before relying on this stack for organizational records.

These are operational follow-ups, not evidence that the recorded story failed.
No production infrastructure or authentication settings were changed here.

## Code and repository assessment

The implementation has useful architectural boundaries: FastAPI and MCP share
`KnowledgeApplication`, and retrieval, identity, notifications, rendering, and
question processing have separate modules. The tests cover meaningful contracts
and failure paths. The largest application, repository, and CDK modules remain
candidates for gradual decomposition as the product grows; satisfying SOLID does
not require manufacturing wrappers around every call.

The pending SSO changes were reviewed and covered by the tests. Repository
presentation now includes a direct connection quick start, the existing Relay
illustration, this review, and a clear historical label on the old architecture
proposal. `make check` and GitHub Actions use the same locked-environment gates.

The local virtualenv had executable paths left over from the repository's old
name. Reinstalling the locked environment repaired those launchers; tests were
then run with the project's Python interpreter.
