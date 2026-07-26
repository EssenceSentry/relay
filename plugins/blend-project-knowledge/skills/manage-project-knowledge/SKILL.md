---
name: manage-project-knowledge
description: Manage authenticated Blend Project Knowledge projects through the remote MCP. Use when a user wants to create, inspect, rename, archive, or restore projects; manage collaborators or invitations; upload or download source documents; search project evidence; review notifications; create or answer project questions; review an external answer; or record a verified fact. Also use when deciding which MCP operation safely completes a project-knowledge task.
---

# Manage Project Knowledge

Use the authenticated MCP as the sole application interface. Begin with
`get_current_user` when identity or permissions matter. Resolve unknown project
IDs with `list_projects`; never guess an ID.

## Safety contract

Obtain explicit confirmation immediately before any of these actions:

- invite or remove a collaborator;
- archive a project;
- decline a collaboration invitation;
- create or resend a question that sends email;
- reject an answer;
- create a verified fact.

State the exact project and affected person or record in the confirmation.
Reuse the same `request_id` when retrying a write. Never store an inference as a
verified fact. Do not reinterpret a permission failure as permission to use a
different project or identity.

## Projects and collaboration

- Use `create_project` with a stable `request_id`; the caller becomes author.
- Read `my_role`, capability fields, warnings, and `next_action` in project
  results before proposing a write.
- Use `rename_project` for title changes. Only admins may call
  `archive_project` or `restore_project`.
- Inspect `list_project_collaborators` before inviting or removing someone.
- Use `list_my_collaboration_invitations` before
  `decide_collaboration_invitation`.
- Use `list_my_notifications` for inbox work and
  `mark_notification_read` only after the notification has been handled or the
  user asks to clear it.

## Search and documents

Use `search_all_projects` to discover the relevant project. Use several focused
`search_project_knowledge` queries for evidence. Results are previews: open
material sources with `get_document_text` before making claims. Cite the
document name and page, slide, or locator where available. Retrieval scores
rank evidence; they do not prove a claim.

Use `list_project_documents` to inspect inventory and status, `get_document`
for one status or failure, and `get_document_download_url` for a time-limited
original or Markdown download.

## Uploads

1. Confirm that the user may edit the project and that the file meets the
   returned format and size constraints.
2. Call `prepare_document_upload` with file metadata and a stable `request_id`.
3. If the client supports a native local-file upload to a presigned S3 POST,
   send the file using the returned URL and fields. Binary data must not pass
   through the MCP server.
4. Otherwise give the user the returned authenticated `fallback_url`. Do not
   claim that the agent uploaded the file.
5. Poll `get_document` until `READY` or `FAILED`. Report the failure detail and
   next action when processing fails.

## Questions and answers

- Use `list_my_assigned_questions` for the current user's work queue.
- Inspect `get_project_question` and `list_question_answers` before answering
  or reviewing.
- Call `create_project_question` only after confirming the email-producing
  action. An optional assigned address must be an exact verified Blend address;
  never infer one from a name.
- Call `submit_question_answer` with text, up to ten same-project `READY`
  document IDs, or both. Use `prepare_document_upload` first for new evidence
  and wait for `READY`.
- A non-collaborator answer may wait for human review. A member or admin may use
  `review_question_answer`; confirm before rejection.
- Use `resend_question_email` only after confirming the additional email.

If project evidence is insufficient, explain the gap before suggesting a new
question. Asking or answering a question never changes collaboration access.

## Verified facts

Use `list_verified_facts` to inspect existing records. Create a fact only when
the user explicitly confirms both its truth and provenance. Preserve material
caveats in the value or provenance.
