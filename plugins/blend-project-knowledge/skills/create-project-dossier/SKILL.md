---
name: create-project-dossier
description: Create evidence-backed Blend360 project dossiers and participant sales briefs from Blend Project Knowledge. Use when the user asks for a project dossier, sales brief, project brief, success story, case study, capability story, client story, or a sourced summary of one PIH project. Also use when revising one of those artifacts to improve its grounding or citations. Requires the blend-project-knowledge MCP. Do not use for generic summaries unrelated to a project in this knowledge base.
---

# Create Project Dossier

Create the artifact from retrieved project evidence, not memory. Treat the MCP
as the live evidence source and this skill as the editorial contract.

Read [the dossier format](references/dossier-format.md) completely before
researching or drafting.

## Research workflow

1. Determine the requested project and artifact. Default to the one-page sales
   brief format when the user says only "dossier" or "brief."
2. If the exact project ID is unknown, call `list_projects` and match the
   project by name or description. Never invent a project ID.
3. Call `list_project_documents` to inventory the project and confirm relevant
   documents are `READY`.
4. Run several focused `search_project_knowledge` calls with the project ID. Cover at
   least the client or context, challenge, solution, delivery or technology,
   features, and outcomes. Use `top_k=10` to `20` for this broad research.
5. Search results are previews. Call `get_document_text` for every document that
   materially supports the artifact, including any source used for a metric.
6. Build a private claim ledger while researching: claim, supporting document,
   page or slide locator, confidence, and conflicts or gaps.
7. Reconcile duplicate or conflicting evidence. Prefer the most final or
   current source when that status is explicit; otherwise disclose the conflict.
8. Draft the requested Markdown using the bundled format and then perform the
   evidence check below.

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
searches and reading the strongest documents, explain the missing evidence. Do
not fill gaps with general industry knowledge.

## Tool boundaries

- When documents are missing, unavailable, or still processing, direct the user
  to `https://essencesentry.shop/` to upload them, then recheck with
  `list_project_documents`.
- Do not call `create_project_question` or `resend_question_email` without
  explicit user confirmation; those tools send external email.
- Do not call `create_verified_fact` without explicit user confirmation. Never
  store an inference as a verified fact.
- Creating the dossier itself is read-only. Do not send, publish, or persist it
  unless the user separately requests that action.
