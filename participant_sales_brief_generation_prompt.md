# Participant sales brief generation

Create a polished, evidence-backed Blend360 participant sales brief for this
project:

- Project ID: `[PROJECT_ID]`
- Project or case-study name: `[PROJECT_NAME]`
- Additional context: [ADDITIONAL_CONTEXT]

## Research workflow

1. Start with several focused `search_all_projects` calls, even though the
   project ID and name are supplied. Cover project identity, challenge,
   solution, delivery or technology, features, and outcomes. Prefer precise
   queries with `top_k=5` to `8`.
2. Use `search_project_knowledge` to deepen or disambiguate evidence within the
   supplied project.
3. Search hits are previews. Use `get_document_text` for the strongest
   documents that materially support the brief, including every source used
   for a metric.
4. Do not enumerate and read all project documents. Use
   `list_project_documents` only as a last resort after multiple focused
   searches fail, or to check whether a known source is missing or still
   processing.
5. Reconcile duplicate or conflicting evidence. Prefer a source explicitly
   identified as more final or current; otherwise disclose the conflict.
6. Build the brief only from project evidence you opened. Do not add general
   knowledge, guessed details, or unsupported marketing claims.

## Evidence requirements

- Cite every material factual claim inline, including project identity,
  challenge, delivered capabilities, technology, dates, metrics, and outcomes.
- Use `([Document Name], p. N)` or `([Document Name], slide N)` when a locator
  is available; otherwise use `([Document Name])`.
- Put each citation immediately after the sentence or bullet it supports. A
  Sources Used section alone does not satisfy the citation requirement.
- Give every quantified outcome a direct citation. Do not present goals,
  projections, or capabilities as achieved outcomes.
- If a claim combines evidence from multiple documents, cite every supporting
  source.
- Label synthesis beyond explicit source wording as **Inference** and cite the
  source premises.
- Replace unsupported claims with a concise **Known gap** rather than guessing.
- List only documents actually opened and cited in **Sources Used**.

## Output and rendering

Draft the complete brief as Markdown using the exact section names below. Then
call `render_project_dossier` with the complete Markdown and a stable
`request_id`. Return both the editable DOCX and polished PDF links. Reuse the
same request ID to refresh expired links.

Do not include retrieval scores, research narration, a private claim ledger,
or an explanation of how the brief was produced.

Use this structure:

```text
# [Project Name] — [Concise, evidence-supported descriptor]

Generated [DATE] — Sales Brief

[Client / Project] — A Blend360 Case Study

## Executive Summary

## The Challenge

## Our Solution

## Key Features

## Quantified Outcomes

## Business Value

## Relevant Visual Evidence

## Known Gaps / Caveats

## Sources Used
```

Keep the result concise, executive, specific, and scannable. Include
**Relevant Visual Evidence** only when an informative chart, plot, table,
diagram, architecture, process flow, or infographic materially improves
understanding. Do not describe logos, banners, stock photography, decorative
layouts, footer text, or other visual noise. Omit the section when no relevant
visual evidence exists.
