The API already supports the agent-side expert workflow you are describing:

* list questions assigned to the current identity;
* read a particular knowledge-gap request;
* submit an answer for asynchronous review;
* inspect review state and feedback.

Those operations simply are not exposed through MCP today. The API has 22 application operations while the MCP has 10 tools, and the audit explicitly identifies project creation, project rename, global search, upload, assigned-question listing, and answer submission as the important missing MCP capabilities.

## The target architecture

I would make Relay formally headless:

```text
Claude / Codex / ChatGPT
          │
          ▼
     Relay MCP adapter
          │
          ▼
  Relay application services
          ▲
          │
     FastAPI HTTP API
          ▲
          │
  upload / answer handoff pages

Email reply ──► same question workflow
```

One important implementation detail: because FastAPI and MCP currently run in the same Fargate task, the MCP should not literally make HTTP requests back into its own API.

Instead:

```python
FastAPI route ─┐
               ├──> RelayApplication / domain services
MCP tool ──────┘
```

The HTTP API is the canonical **external contract**, but both adapters call the same application methods, use the same Pydantic request and response models, and receive the same principal context. That avoids:

* duplicated validation;
* divergent idempotency behavior;
* MCP accidentally bypassing API invariants;
* internal loopback networking;
* subtly different error handling.

Later, if the MCP server is separated from the API service, it can become an authenticated HTTP client without changing the tool contract.

## What “fully capable” should mean

I would not expose a generic `call_relay_api` tool. That is unpleasant for agents and makes confirmation and tool semantics opaque.

Instead, expose all meaningful user operations as well-described domain tools.

### Projects

```text
list_projects
get_project
create_project
rename_project
```

`create_project` should take a stable `request_id` so an agent retry cannot create two projects.

```python
create_project(
    name: str,
    description: str | None,
    request_id: str,
)
```

Project deletion can wait. Archive is safer when you eventually need lifecycle management.

### Search and evidence

```text
search_workspace
search_knowledge
list_project_documents
get_document_text
get_document_download_url
list_verified_facts
```

`search_workspace` maps to the existing `/api/search` operation. It is important for the natural agent workflow:

> “Which prior projects involved customer churn and Snowflake?”

The agent should not first have to guess a project.

### Uploads

The existing presigned S3 upload endpoint remains useful, but its abstraction is too browser-specific for MCP. I would add an upload-session operation:

```text
begin_document_upload
get_upload_status
retry_document_ingestion
```

For example:

```python
begin_document_upload(
    project_id: str,
    expected_file_count: int = 1,
    request_id: str,
)
```

returns:

```json
{
  "upload_session_id": "upload_01...",
  "upload_url": "https://essencesentry.shop/upload#opaque-capability",
  "expires_at": "2026-07-27T15:30:00Z",
  "max_file_size_bytes": 104857600,
  "accepted_extensions": [
    ".pdf",
    ".doc",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".json"
  ]
}
```

The same operation can later return an inline MCP App widget when the host supports one. The portable fallback remains the tiny external file-picker page.

The upload page should know the project and session already. It should not contain project navigation or application chrome:

```text
Upload files to “Acme Customer Analytics”

[ Drop files here ]

[ Upload ]
```

The browser receives a tightly constrained presigned POST from the backend. The agent never handles file bytes or AWS credentials.

`retry_document_ingestion` is worth adding now because the audit identifies failed ingestion as visible but not recoverable through a product surface.

### Knowledge gaps and expert answers

Keep the email workflow exactly as it is, but treat email as one adapter into a shared answer-submission service:

```text
Email reply ────────────────┐
Private answer page ────────┼──> submit_answer()
Authenticated HTTP API ─────┤
MCP tool ───────────────────┘
```

The MCP additions should be:

```text
list_assigned_knowledge_gaps
get_knowledge_gap
submit_knowledge_gap_answer
create_knowledge_gap
resend_knowledge_gap_email
```

The direct-answer tool might look like:

```python
submit_knowledge_gap_answer(
    project_id: str,
    question_id: str,
    answer: str,
    request_id: str,
)
```

and return:

```json
{
  "answer_id": "answer_01...",
  "question_id": "question_01...",
  "status": "PENDING_REVIEW",
  "message": "The answer was accepted and is being reviewed."
}
```

The API and MCP submission path should invoke the same review process as inbound email:

1. append the answer to cumulative history;
2. run the sufficiency check;
3. mark `NEEDS_MORE_INFO` or `RESOLVED`;
4. send a clarification email when appropriate;
5. generate the normalized Markdown source;
6. write it to S3;
7. index it in OpenSearch;
8. create the verified fact.

I would store the input channel explicitly:

```python
answer_channel: Literal[
    "EMAIL",
    "PRIVATE_WEB",
    "AUTHENTICATED_API",
    "MCP",
]
```

along with:

```python
submitted_by
request_id
received_at
raw_source_reference
```

The channel should affect provenance, not downstream semantics.

For MCP answer submission, the behavioral rule should be:

> Submit only information explicitly supplied or approved by the user. Do not synthesize an answer from model memory.

That is still advisory until enterprise policy is added, but the server can at least preserve who submitted it and through which channel.

## The user-dependent endpoint should be an inbox, not merely “news”

I like the underlying idea. I would call the API endpoint:

```http
GET /api/me/inbox
```

and the MCP tool:

```text
get_my_briefing
```

“News” sounds passive and chronological. This is primarily an actionable work queue.

A useful response shape is:

```json
{
  "attention_required": [
    {
      "id": "question_01...",
      "kind": "KNOWLEDGE_GAP_NEEDS_MORE_INFO",
      "priority": "HIGH",
      "project": {
        "project_id": "project_01...",
        "name": "Acme Customer Analytics"
      },
      "title": "Clarify production rollout ownership",
      "summary": "The previous answer identified the lead but not the rollout stages.",
      "status": "NEEDS_MORE_INFO",
      "created_at": "2026-07-26T12:00:00Z",
      "updated_at": "2026-07-26T14:10:00Z",
      "actions": [
        {
          "tool": "submit_knowledge_gap_answer",
          "arguments": {
            "project_id": "project_01...",
            "question_id": "question_01..."
          }
        }
      ]
    }
  ],
  "recent_updates": [
    {
      "id": "question_02...",
      "kind": "KNOWLEDGE_GAP_RESOLVED",
      "project": {
        "project_id": "project_02...",
        "name": "Retail Forecasting"
      },
      "title": "Expert response added to project knowledge",
      "summary": "The deployment-region question was answered and indexed.",
      "updated_at": "2026-07-26T13:42:00Z"
    }
  ],
  "next_cursor": null
}
```

The first useful item types are:

```text
KNOWLEDGE_GAP_ASSIGNED
KNOWLEDGE_GAP_NEEDS_MORE_INFO
KNOWLEDGE_GAP_RESOLVED
DOCUMENT_FAILED
DOCUMENT_READY
```

Later:

```text
REPORT_READY
REPORT_FAILED
PROJECT_INVITATION
DOCUMENT_REVIEW_REQUIRED
```

### Keep the first implementation simple

Initially, `GET /api/me/inbox` can be a derived view over existing records:

* unresolved questions assigned to the current principal;
* recently resolved assigned questions;
* questions created by the current principal whose state changed;
* recent document failures associated with that principal.

There is no need to create a generic notification/event platform yet.

When reports, project invitations, approvals, and richer activity appear, introduce a small DynamoDB inbox read model:

```text
PK = USER#<principal-key>
SK = EVENT#<timestamp>#<event-id>
```

Each workflow writes a compact, idempotent event item. But that would be premature while the feed is mostly a view over knowledge gaps.

## Public mode versus future identity

The current deployment maps every unauthenticated call to:

```text
public@hackathon.local
```

Therefore, a genuinely personal inbox is impossible in the public demo. For now, the permissive policy can treat the public principal’s inbox as a workspace inbox.

The API contract should nevertheless always be principal-based:

```python
RequestContext(
    principal_id=...,
    email=...,
    groups=...,
)
```

Do **not** let callers pass an arbitrary `user_email` to `get_my_briefing`. That would create an identity-spoofing pattern that later has to be removed.

When Microsoft authentication is enabled:

* assigned gaps are matched to the verified principal email;
* stable Entra subject or object ID becomes the durable identity;
* email remains an assignment/delivery attribute;
* policy determines which project activity the principal may see.

For now, policy can simply be:

```python
AllowAllDemoPolicy()
```

Later:

```python
EnterpriseRelayPolicy()
```

The application services and MCP contracts do not need to change.

## Recommended MCP capability set

After this pass, I would expect approximately the following tools.

### Read operations

```text
get_my_briefing
list_projects
get_project
search_workspace
search_knowledge
list_project_documents
get_document_text
get_document_download_url
get_upload_status
list_verified_facts
list_assigned_knowledge_gaps
get_knowledge_gap
```

### Write operations

```text
create_project
rename_project
begin_document_upload
retry_document_ingestion
create_knowledge_gap
submit_knowledge_gap_answer
resend_knowledge_gap_email
record_verified_fact
```

Later:

```text
list_report_templates
render_report
get_report_status
get_report
```

This is still a manageable tool set. The server instructions can tell the agent when to use each family rather than exposing one giant procedural API.

## Idempotency changes I would make at the same time

Every agent write that can be retried should take a stable request identifier:

```text
create_project
begin_document_upload
create_knowledge_gap
submit_knowledge_gap_answer
record_verified_fact
render_report
```

Rename is naturally idempotent when setting an explicit name.

Resending email is intentionally not idempotent semantically, because each request means “send again.” It should remain clearly annotated as an external side effect.

For API-submitted answers, idempotency is especially important. Agent hosts can retry after a timeout even when Relay accepted the first request. The DynamoDB answer identity should therefore derive from:

```text
principal + question_id + request_id
```

A duplicate should return the existing answer rather than triggering another review.

## MCP parity should be contract-tested

I would create a simple table in code describing each user-facing operation:

```python
OperationSpec(
    name="submit_knowledge_gap_answer",
    api_route="POST /api/projects/{project_id}/questions/{question_id}/answers",
    mcp_tool="submit_knowledge_gap_answer",
    mutating=True,
    idempotent=True,
    external_side_effect=False,
)
```

Then tests should verify:

1. the API and MCP use the same request model;
2. they call the same application method;
3. equivalent inputs produce equivalent domain results;
4. errors map consistently;
5. the current principal is propagated;
6. write tools expose correct MCP annotations.

I would not generate the MCP automatically from OpenAPI. The agent-facing names, descriptions, examples, confirmation rules, and output compaction need deliberate design. But the shared models and application operations should make drift difficult.

## What remains of the frontend

The intended product frontend becomes:

```text
/
    Relay explanation
    Connect MCP
    Install plugin
    Usage examples

/upload#TOKEN
    one-purpose file upload handoff

/answer#TOKEN
    one-purpose expert answer fallback

/internal or /ops
    optional debugging and operations console
```

The current frontend does not need to be deleted immediately. It is useful as a development and operational console while you harden the agent workflow. It simply stops being the advertised product experience.

The resulting product contract becomes very clean:

> **Your agent is the workspace. Relay supplies project knowledge, actions, and publishing. Email supplies the expert feedback channel. The browser appears only when raw files or exceptional interactions require it.**

## The immediate implementation sequence

I would make the next repository pass in this order:

1. Introduce a small shared `RelayApplication` facade used by FastAPI and MCP.
2. Add `request_id` idempotency to API answer submission.
3. Expose assigned-gap listing and answer submission through MCP.
4. Expose project creation, rename, and workspace search through MCP.
5. Add `/api/me/inbox` and `get_my_briefing`.
6. Add upload-session and ingestion-retry API operations.
7. Expose upload-session creation and retry through MCP.
8. Reduce the promoted frontend to landing, upload handoff, and answer fallback.
9. Add API/MCP parity tests.
10. Add report rendering as the next independent capability family.

That preserves everything strong in the current implementation while finally making the product match its thesis: **Relay is not another application in which users do their work; it is the knowledge and workflow layer available inside the agent where the work is already happening.**
