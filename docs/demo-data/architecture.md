# Demo Harbor architecture

SYNTHETIC EXAMPLE — all design details are invented for this demonstration.

## Before and after

| Step | Before | After |
| --- | --- | --- |
| Import | Volunteer copies a mock daily list | Scheduled task reads a generated CSV |
| Validation | Missing fields go unnoticed | Schema check sends invalid rows to a review queue |
| Planning | Volunteer sorts a worksheet | Three toy planning tools propose an order |
| Review | Decisions are overwritten | Reviewer accepts or changes each proposal with a note |
| Monitoring | No run record | Import ID, row counts, and failure reason are stored |

## Data flow

Generated CSV -> schema validation -> review queue -> planning proposal ->
human decision -> append-only decision log.

## Boundaries

Only synthetic records enter this demonstration. Retrying an import with the
same ID reuses its result. Missing required fields stop a proposal. The tools
cannot execute external actions.
