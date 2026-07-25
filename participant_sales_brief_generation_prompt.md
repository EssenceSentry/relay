# Participant sales brief generation

Create a polished, evidence-backed Blend360 participant sales brief in
Markdown for this project:

- Project ID: `[PROJECT_ID]`
- Project or case-study name: `[PROJECT_NAME]`
- Additional context: [ADDITIONAL_CONTEXT]

## Research workflow

1. Call `list_project_documents` for the project and confirm that the relevant
   documents are `READY`.
2. Run several focused `search_knowledge` calls covering the client or project
   context, challenge, solution, delivery and technology, key features, and
   outcomes. Use `top_k=10` to `20` for this broad research.
3. Search results are previews. Use `get_document_text` for every document that
   materially supports the brief, including every source used for a metric.
4. Reconcile duplicate or conflicting evidence. Prefer a source explicitly
   identified as more final or current; otherwise disclose the conflict.
5. Build the brief only from the project evidence you opened. Do not add
   general knowledge, guessed details, or unsupported marketing claims.

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

## Output

Return only the finished Markdown brief. Do not include retrieval scores,
research narration, a private claim ledger, or an explanation of how the brief
was produced.

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
layouts, footer text, or other visual noise.
