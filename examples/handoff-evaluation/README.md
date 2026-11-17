# Can this handoff be answered from the project record?

A volunteer asks how many arrival records the harbor expects tomorrow. The brief supports **36 records per day as a target**. A second volunteer asks who owns Arrival Forecast. The steering notes list the owner as **Unknown**. An answer that guesses a person would make the handoff worse.

This runnable evaluation uses three invented Demo Harbor documents, six questions, and the same rank-fusion and question-creation functions that Relay uses in production.

| Question | Observed action | Evidence or next step |
| --- | --- | --- |
| How many arrival records per day does the plan target? | Cite | [Brief](../../docs/demo-data/project-brief.md) · 36 |
| Where do rows with missing fields go? | Cite | [Architecture](../../docs/demo-data/architecture.md) · a review queue |
| Can the tools order supplies? | Cite | [Brief](../../docs/demo-data/project-brief.md) · they cannot |
| Who owns Arrival Forecast? | Ask a person | [Steering notes](../../docs/demo-data/steering-notes.md) · owner unknown |
| Who is the Supply Alert expert? | Ask a person | [Steering notes](../../docs/demo-data/steering-notes.md) · expert unknown |
| What cycle time was measured after deployment? | Ask a person | The [brief](../../docs/demo-data/project-brief.md) describes a target. The [notes](../../docs/demo-data/steering-notes.md) record no realized outcome. |

## Reproduce and inspect

From the repository root, run `PYTHONPATH=src uv run --locked python examples/handoff-evaluation/evaluate.py`. The process exits successfully when the expected routes, cited documents, and extracted answers match. [Recorded results, including retrieved sources and follow-up questions](results.json).

The local client searches headings and passages using SQLite full-text search. Relay fuses two lexical rankings. The evaluation client extracts a specific field from the top three results and hands missing values to Relay’s question workflow. Persistence is mocked and email is disabled. [Field definitions](fields.json) · [Question set and expected decisions](questions.json).

Six of six fixtures matched. This checks grounding and escalation in a constrained extractive client. Measuring general-purpose agent behavior or hosted retrieval quality would require running that client against new questions and the live retrieval backend.
