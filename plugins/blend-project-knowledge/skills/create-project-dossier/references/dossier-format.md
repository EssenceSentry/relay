# Blend360 project dossier format

Use this contract for project dossiers, participant sales briefs, success
stories, capability stories, and case-study summaries created from Blend
Project Knowledge.

## Default artifact

Unless the user requests another form, produce a polished, shareable, one-page
sales brief for one project. It must be useful to Blend360 sales, delivery, and
account teams as a credible capability story, not as a generic marketing
template or a summary written from memory.

Return only the finished Markdown artifact. Do not include research narration,
retrieval scores, or an explanation of how the artifact was made.

## Non-negotiable evidence rules

1. Use only facts supported by project sources opened through the MCP. Never
   invent client names, dates, technologies, metrics, outcomes, team roles,
   owners, or business impact.
2. Cite every material factual claim inline, including project identity,
   challenge, delivered capabilities, technology, dates, metrics, and outcomes.
3. Use `([Document Name], p. N)` or `([Document Name], slide N)` when a page or
   slide locator is available. Otherwise use `([Document Name])`.
4. Put citations immediately after the sentence or bullet they support. A
   source list alone does not satisfy the citation requirement.
5. If one claim combines evidence from multiple documents, cite every
   supporting source. Do not attach a citation to a claim it does not support.
6. Mark synthesis beyond explicit source wording as **Inference** and cite the
   source premises.
7. A quantified outcome must have a direct citation. When no sourced metrics
   exist, write: `Known gap: the available sources do not include quantified
   outcomes.`
8. When a required section lacks evidence, state a concise **Known gap** rather
   than guessing.

## Content

### Title

Use the project name plus a concise, evidence-supported description of the
work.

### Executive Summary

In one or two short paragraphs, explain who Blend360 helped, the problem or
opportunity, what was delivered, and the headline sourced outcome. Do not
describe an outcome if no source supports one.

### The Challenge

Describe the evidence-supported starting situation and why a better approach
was needed: operational pain, fragmented tools, manual work, slow processes,
knowledge gaps, cost, risk, or missed opportunity.

### Our Solution

Explain what Blend360 delivered, the relevant technology stack, and the
delivery model when supported by the sources. Focus on the solution rather than
generic company capabilities.

### Key Features

List three to five specific capabilities:

```text
- **Feature name** — What it does and why it matters. ([Source], p. N)
```

### Quantified Outcomes

List only measurable, directly sourced results such as time or cost reduction,
revenue impact, accuracy, speed, adoption, coverage, volume, processing time,
model count, or feature count. Do not turn goals, projections, or capabilities
into achieved outcomes.

### Business Value

Explain the sourced proof point the project provides, the buyer concern it
addresses, and the reusable Blend360 capability it demonstrates. Mark
reasonable but non-explicit sales synthesis as **Inference**.

### Relevant Visual Evidence

Include this section only when a source contains an informative chart, plot,
table, diagram, architecture, process flow, or infographic that materially
improves understanding. Briefly state what it shows and cite its page or slide.
Do not describe logos, banners, stock photography, decorative layouts, footer
text, or other visual noise.

### Known Gaps / Caveats

For each material gap, state what is missing, who or what type of owner could
answer it if known, and how the answer would strengthen the artifact. Disclose
unresolved source conflicts here.

### Sources Used

Provide one bullet per document actually opened and cited:

```text
- **Document name** — document ID; pages or slides used; specific claims supported.
```

Do not list search-only sources that were not opened, consulted, and cited.

## Required Markdown skeleton

```text
# [Project Name] — [Concise Project Descriptor]

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

Omit **Relevant Visual Evidence** when it adds no substantive information.

## Style

- Executive, business-facing, and concise enough for a one-page brief.
- Short paragraphs and scannable bullets.
- Specific evidence instead of hype.
- Minimal internal implementation jargon unless central to the project.
- No repeated phrases such as "based on the provided materials"; citations
  already establish grounding.
- No unsupported adjectives such as "transformative," "best-in-class," or
  "significant."
