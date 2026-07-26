# ASI Conversation Assistant — Governed self-service analytics in Databricks

Generated July 26, 2026 — Sales Brief

ASI proof of concept — A Blend360 Capability Brief

## Executive Summary

Blend360 proposed a ten-week Databricks proof of concept to reduce repetitive ad-hoc analytics work while keeping answers governed, interpretable, and bounded to approved use cases. A supervisor agent routes user requests to specialized analytics and knowledge tools, with Unity Catalog permissions enforced before queries run. ([ASI Conversation assistant.pptx])

## The Challenge

Teams repeatedly handled common sizing and audience-description requests, while business users needed help interpreting results rather than merely receiving numbers. The proof of concept also had to exclude member-level output, forecasting, budget allocation, undefined data, and broad dataset access. ([ASI Conversation assistant.pptx])

## Our Solution

The proposed Databricks application gives business users a lightweight conversational interface. A supervisor agent routes requests to Population Sizing Genie, Campaign Performance Genie, a knowledge assistant, text-to-SQL, or deeper research, while Unity Catalog enforces access before query execution. ([ASI Conversation assistant.pptx])

## Key Features

- **Supervisor routing** — Directs each request to the appropriate domain tool. ([ASI Conversation assistant.pptx])
- **Natural-language analytics** — Lets users ask questions without writing SQL. ([ASI Conversation assistant.pptx])
- **Governed access** — Applies role-based access and Unity Catalog controls before queries run. ([ASI Conversation assistant.pptx])
- **Interpretability** — Helps users understand how to interpret results, not only view values. ([ASI Conversation assistant.pptx])
- **Explicit boundaries** — Flags unsupported requests instead of inferring or fabricating answers. ([ASI Conversation assistant.pptx])

## Quantified Outcomes

- **10-week POC** — Two use cases enter discovery and one mutually agreed use case is built. ([ASI Conversation assistant.pptx])
- **$50,000 scope** — Commercial estimate stated in the proposal. ([ASI Conversation assistant.pptx])
- **Known gap** — The source defines expected efficiency and governance benefits but contains no realized business outcomes because this is a proposed proof of concept. ([ASI Conversation assistant.pptx])

## Business Value

**Inference:** The design offers a controlled path from dashboard-centric BI toward conversational and agentic analytics without exposing underlying data directly to users. The explicit scope boundaries make the proof of concept suitable for testing adoption and answer quality before enterprise scale. ([ASI Conversation assistant.pptx])

## Relevant Visual Evidence

- **Agent architecture** — The diagram shows marketing, campaign operations, and analytics users entering through a Databricks app, a supervisor routing layer, specialized tools, and Unity Catalog tables. ([ASI Conversation assistant.pptx])
- **GenBI maturity roadmap** — The roadmap progresses from recurring-deck automation through conversational BI, causal insight, forecasting, and autonomous actions. ([ASI Conversation assistant.pptx])

## Known Gaps / Caveats

- **Proposal status** — Duration, cost, architecture, and benefits describe a planned proof of concept rather than completed delivery.
- **Use-case selection** — The final POC use case is not identified in the source.
- **Outcome measurement** — No baseline, success metric, or realized time saving is provided.

## Sources Used

- **ASI Conversation assistant.pptx** — consolidated Markdown source; scope, exclusions, architecture, governance, timeline, assumptions, and GenBI roadmap.
