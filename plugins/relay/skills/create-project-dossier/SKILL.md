---
name: create-project-dossier
description: Create evidence-backed Blend360 project dossiers and participant sales briefs from Relay. Use when the user asks for a project dossier, sales brief, project brief, success story, case study, capability story, client story, or a sourced summary of one PIH project. Also use when revising one of those artifacts to improve its grounding or citations. Requires the Relay MCP. Do not use for generic summaries unrelated to a project in this knowledge base.
---

# Create Project Dossier

Create the artifact from retrieved project evidence, not memory. Treat the MCP
as the live evidence source and this skill as the editorial contract.

Read [the dossier format](references/dossier-format.md) completely before
researching or drafting.

## Research workflow

1. Determine the requested project and artifact. Default to the compact
   three-page executive dossier when the user says only "dossier" or "brief."
2. Start with several focused `search_all_projects` calls, even when the user
   supplies a project name. Cover project identity or client, challenge,
   solution, delivery or technology, features, and outcomes. Prefer multiple
   precise queries with `top_k=5` to `8` over one broad query.
3. Use the project and document IDs in the strongest global hits to identify
   the project. Never invent a project ID. Use `search_project_knowledge` to
   deepen or disambiguate the candidate project.
4. Search results are previews. Call `get_document_text` for the strongest
   documents that materially support the artifact, including every source used
   for a metric. Do not read every document merely because it belongs to the
   project.
5. Use `list_projects` or `list_project_documents` for discovery only as a last
   resort after several focused global and project searches fail. Use
   `list_project_documents` normally only to check ingestion status or confirm
   whether a known expected source is missing.
6. Build a private claim ledger while researching: claim, supporting document,
   page or slide locator, confidence, and conflicts or gaps.
7. Reconcile duplicate or conflicting evidence. Prefer the most final or
   current source when that status is explicit; otherwise disclose the conflict.
8. Draft the requested Markdown using the bundled format and then perform the
   evidence check below.
9. Unless the user explicitly asks for Markdown only, call
   `render_project_dossier` with the complete final Markdown and a stable
   `request_id`. Return both the DOCX and PDF links. Reuse that request ID if
   either expiring link needs to be refreshed.

## Evidence check

Before returning the artifact:

- Cite every material factual claim immediately after the claim.
- Confirm that each citation supports the exact adjacent claim.
- Give every quantified outcome a direct citation.
- Label non-explicit synthesis as **Inference** and cite its premises.
- Replace unsupported claims with a concise **Known gap**.
- Include only documents actually opened and cited in **Sources Used**.
- Do not expose retrieval scores, the private claim ledger, or process narration
  in the finished artifact.

If the sources cannot support a credible artifact after multiple focused
global and project searches and reading the strongest documents, explain the
missing evidence. Do not fill gaps with general industry knowledge or fall
back immediately to enumerating and reading the entire project.

## Tool boundaries

- When documents are missing, unavailable, or still processing, direct the user
  to `https://essencesentry.shop/` to upload them, then recheck with
  `list_project_documents`.
- Do not call `create_project_question` or `resend_question_email` without
  explicit user confirmation; those tools send external email.
- Do not call `create_verified_fact` without explicit user confirmation. Never
  store an inference as a verified fact.
- Rendering stores private, project-scoped deliverables and does not publish or
  email them. The dossier request itself authorizes this render; ask separately
  before sending or publishing either file.
