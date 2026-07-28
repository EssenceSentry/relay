---
name: manage-project-knowledge
description: Manage authenticated Relay projects through the remote MCP. Use when a user wants to create, inspect, rename, archive, or restore projects; manage collaborators or invitations; upload or download source documents; search project evidence; review notifications; create or answer project questions; review an external answer; resolve a verified user by name; or record a verified fact. Also use when deciding which Relay MCP operation safely completes a project-knowledge task.
---

# Manage Project Knowledge

Use the authenticated MCP as the sole application interface. Begin with
`get_current_user` when identity or permissions matter. Treat
`search_all_projects` as the primary way to locate project knowledge and
answers. Never guess an ID.

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

For questions and evidence research, use this retrieval order:

1. Run several focused `search_all_projects` queries. Use the returned project
   and document IDs to route the rest of the research.
2. Open the strongest material hits with `get_document_text`. Search results
   are previews and are not sufficient evidence by themselves.
3. Use `search_project_knowledge` only to deepen or disambiguate research after
   global search identifies a likely project.
4. Use `list_projects`, `list_project_documents`, and broad document reading
   only as a last-resort discovery path after focused global and project
   searches fail to locate the answer.

Do not answer a knowledge question by listing projects, selecting one,
enumerating all its documents, and reading them all unless retrieval has
already failed. `list_projects` remains appropriate when the user explicitly
asks for a project list or an administrative write needs project selection.
`list_project_documents` is primarily for inventory and ingestion status.
Use `get_document` for one document's status or failure and
`get_document_download_url` for a time-limited original or Markdown download.

Cite the document name and page, slide, or locator where available. Retrieval
scores rank evidence; they do not prove a claim.

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
- Every authenticated reader may call `create_project_question`, including a
  user whose project role is `READER` and whose `can_edit` capability is false.
  `can_edit` governs project content changes, not questions.
- When the user names an answerer but does not provide an exact email, call
  `search_user_directory` with the person's name. Use a unique result's exact
  verified email; if several people match, ask the user which person they mean.
  Never construct an email from a name.
- When project-specific evidence remains insufficient after retrieval, do not
  stop after reporting the gap. Before responding, you **must** call
  `get_project` and `list_project_collaborators` for the relevant project.
  State what is missing, suggest the verified project author first using
  `author_display_name` and `author_email`, suggest other project members only
  when `email_verified` is true, and offer to draft a question for the user's
  approval. If no unique project is known, ask the user to identify it.
  Treat these people as suggestions, not authorization to send.
- Call `create_project_question` only after confirming the email-producing
  action. An optional assigned address must come from the verified directory or
  be an exact address the user supplied.
- Every authenticated reader may submit an answer. Answers from
  non-collaborators wait for member review; lack of edit access is not a reason
  to refuse the submission.
- Call `submit_question_answer` with text, up to ten same-project `READY`
  document IDs, or both. Use `prepare_document_upload` first for new evidence
  and wait for `READY`.
- A non-collaborator answer may wait for human review. A member or admin may use
  `review_question_answer`; confirm before rejection.
- Use `resend_question_email` only after confirming the additional email.

If project evidence is insufficient, always complete the read-only
author/collaborator lookup and make the proactive handoff above. Never call
`create_project_question` until the user confirms the exact recipient and
question. Asking or answering a question never changes collaboration access.

## Verified facts

Use `list_verified_facts` to inspect existing records. Create a fact only when
the user explicitly confirms both its truth and provenance. Preserve material
caveats in the value or provenance.
