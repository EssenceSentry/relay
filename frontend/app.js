const state = {
  config: null,
  tokens: null,
  me: null,
  projects: [],
  selectedProject: null,
  documents: [],
  questions: [],
  selectedQuestion: null,
  pollingTimer: null,
  answerToken: null,
  publicQuestion: null,
  searchQuery: "",
  searchResults: [],
};

const $ = (id) => document.getElementById(id);

async function main() {
  try {
    const requestedQuestionId = new URL(window.location.href).searchParams.get("question_id");
    if (requestedQuestionId) sessionStorage.setItem("requested_question_id", requestedQuestionId);
    state.config = await fetchJson("config.json", { auth: false });
    $("mcp-url").value = state.config.mcp_url;
    const answerToken = new URLSearchParams(window.location.hash.slice(1)).get("answer");
    if (answerToken) {
      state.answerToken = answerToken;
      await enterExpertAnswer();
      return;
    }
    if (!state.config.mcp_auth_enabled) {
      $("mcp-connect-help").textContent =
        "Add this as a Streamable HTTP MCP server. No sign-in is required during the hackathon.";
      clearSession();
      await enterApplication();
      return;
    }
    await completeAuthorizationIfPresent();
    state.tokens = readTokens();
    if (state.tokens) {
      await ensureFreshTokens();
      await enterApplication();
    } else {
      showView("login-view");
    }
  } catch (error) {
    console.error(error);
    showView("login-view");
    toast(readableError(error), true);
  }
}

function showView(id) {
  for (const view of ["loading-view", "expert-view", "login-view", "app-view"]) {
    $(view).classList.toggle("hidden", view !== id);
  }
  document.body.dataset.view = id.replace("-view", "");
  $("user-area").classList.toggle("hidden", id !== "app-view");
}

async function beginLogin() {
  const verifier = randomBase64Url(64);
  const challenge = await sha256Base64Url(verifier);
  sessionStorage.setItem("pkce_verifier", verifier);
  const params = new URLSearchParams({
    client_id: state.config.client_id,
    response_type: "code",
    scope: "openid email profile",
    redirect_uri: state.config.redirect_uri,
    code_challenge: challenge,
    code_challenge_method: "S256",
  });
  window.location.assign(`${cognitoBaseUrl()}/oauth2/authorize?${params}`);
}

async function completeAuthorizationIfPresent() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");
  if (error) {
    throw new Error(url.searchParams.get("error_description") || error);
  }
  if (!code) return;

  const verifier = sessionStorage.getItem("pkce_verifier");
  if (!verifier) throw new Error("The PKCE verifier was lost; please sign in again.");
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: state.config.client_id,
    code,
    redirect_uri: state.config.redirect_uri,
    code_verifier: verifier,
  });
  const response = await fetch(`${cognitoBaseUrl()}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) throw new Error(`Cognito token exchange failed (${response.status})`);
  const tokens = await response.json();
  saveTokens(tokens);
  sessionStorage.removeItem("pkce_verifier");
  window.history.replaceState({}, "", state.config.redirect_uri);
}

async function ensureFreshTokens() {
  if (!state.tokens) return;
  const claims = decodeJwt(state.tokens.id_token);
  if ((claims.exp || 0) * 1000 > Date.now() + 60_000) return;
  if (!state.tokens.refresh_token) {
    clearSession();
    throw new Error("Your session expired. Sign in again.");
  }
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: state.config.client_id,
    refresh_token: state.tokens.refresh_token,
  });
  const response = await fetch(`${cognitoBaseUrl()}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    clearSession();
    throw new Error("Your session could not be refreshed. Sign in again.");
  }
  const refreshed = await response.json();
  state.tokens = { ...state.tokens, ...refreshed };
  saveTokens(state.tokens);
}

async function enterApplication() {
  state.me = await api("/api/me");
  const publicAccess = !state.config.mcp_auth_enabled;
  const limitMib = Math.floor(state.config.max_upload_bytes / (1024 * 1024));
  $("user-email").textContent = publicAccess ? "Hackathon guest" : state.me.email;
  $("logout-button").classList.toggle("hidden", publicAccess);
  $("upload-limit-note").textContent = `or click to choose a file up to ${limitMib} MiB`;
  $("upload-access-note").textContent = publicAccess
    ? `Public upload is enabled for the hackathon with a ${limitMib} MiB safety limit. New files are added to the selected project and ingested automatically.`
    : `Signed-in users can upload files up to ${limitMib} MiB. Ingestion starts automatically.`;
  showView("app-view");
  await Promise.all([loadProjects(), loadQuestions()]);
  startPolling();
}

async function enterExpertAnswer() {
  $("expert-question-content").classList.remove("hidden");
  $("expert-error").classList.add("hidden");
  try {
    state.publicQuestion = await publicQuestionApi("/api/public/question");
    renderExpertQuestion();
  } catch (error) {
    console.error(error);
    $("expert-question-content").classList.add("hidden");
    $("expert-error").classList.remove("hidden");
    $("expert-error-message").textContent = readableError(error);
  }
  showView("expert-view");
}

function renderExpertQuestion() {
  const item = state.publicQuestion;
  const priority = ["low", "normal", "high"].includes(item.priority)
    ? item.priority
    : "normal";
  $("expert-priority").textContent = `${capitalize(priority)} priority`;
  $("expert-priority").className = `expert-priority expert-priority-${priority}`;
  $("expert-project").textContent = item.project_name;
  $("expert-question-text").textContent = item.question;

  $("expert-context-wrap").classList.toggle("hidden", !item.context);
  $("expert-context").textContent = item.context || "";

  const showReview = item.status === "NEEDS_MORE_INFO" && item.review_rationale;
  $("expert-review-wrap").classList.toggle("hidden", !showReview);
  $("expert-review").textContent = showReview ? item.review_rationale : "";
  $("expert-answer").placeholder = showReview
    ? "Add only the missing detail. You do not need to repeat your previous answer."
    : "Give a direct, reusable answer with the concrete detail the project team needs.";

  $("expert-answer-form").classList.toggle("hidden", !item.can_answer);
  $("expert-resolved").classList.toggle("hidden", item.can_answer);
  $("expert-success").classList.add("hidden");
}

async function submitExpertAnswer(event) {
  event.preventDefault();
  const answer = $("expert-answer").value.trim();
  if (!answer) return;
  const submit = $("expert-submit");
  submit.disabled = true;
  submit.textContent = "Submitting…";
  try {
    await publicQuestionApi("/api/public/question/answers", {
      method: "POST",
      body: { answer },
    });
    $("expert-answer-form").classList.add("hidden");
    $("expert-success").classList.remove("hidden");
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${window.location.search}`,
    );
    state.answerToken = null;
    $("expert-success").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (error) {
    toast(readableError(error), true);
  } finally {
    submit.disabled = false;
    submit.textContent = "Submit for review";
  }
}

function logout() {
  clearSession();
  const params = new URLSearchParams({
    client_id: state.config.client_id,
    logout_uri: state.config.logout_uri,
  });
  window.location.assign(`${cognitoBaseUrl()}/logout?${params}`);
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  renderProjects();
  const remembered = sessionStorage.getItem("selected_project_id");
  const selected = state.projects.find((item) => item.project_id === remembered)
    || state.projects[0]
    || null;
  if (selected) await selectProject(selected.project_id);
  else renderSelectedProject();
}

function renderProjects() {
  const list = $("project-list");
  list.replaceChildren();
  if (!state.projects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Create the first project to begin.";
    list.append(empty);
    return;
  }
  for (const project of state.projects) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `project-button${state.selectedProject?.project_id === project.project_id ? " active" : ""}`;
    const name = document.createElement("strong");
    name.textContent = project.name;
    const description = document.createElement("span");
    description.textContent = project.description || project.project_id;
    button.append(name, description);
    button.addEventListener("click", () => selectProject(project.project_id));
    list.append(button);
  }
}

async function createProject(event) {
  event.preventDefault();
  const name = $("project-name").value.trim();
  if (!name) return;
  const project = await api("/api/projects", {
    method: "POST",
    body: {
      name,
      description: $("project-description").value.trim() || null,
    },
  });
  state.projects.unshift(project);
  $("project-form").reset();
  $("project-form").classList.add("hidden");
  renderProjects();
  await selectProject(project.project_id);
  toast("Project created.");
}

async function selectProject(projectId) {
  state.selectedProject = state.projects.find((item) => item.project_id === projectId) || null;
  if (!state.selectedProject) {
    toast("That project is no longer available.", true);
    return;
  }
  showWorkspace();
  sessionStorage.setItem("selected_project_id", projectId);
  renderProjects();
  renderSelectedProject();
  await loadDocuments();
}

function showWorkspace() {
  $("workspace-sidebar").classList.remove("hidden");
  $("workspace-main").classList.remove("hidden");
  $("search-results-page").classList.add("hidden");
}

function showSearchPage() {
  $("workspace-sidebar").classList.add("hidden");
  $("workspace-main").classList.add("hidden");
  $("search-results-page").classList.remove("hidden");
}

async function searchAllProjects(event) {
  event.preventDefault();
  const query = $("global-search-input").value.trim();
  if (query.length < 2) return;
  const submit = $("global-search-submit");
  submit.disabled = true;
  submit.textContent = "Searching…";
  state.searchQuery = query;
  showSearchPage();
  $("search-results-title").textContent = `Searching for “${query}”`;
  $("search-results-summary").textContent =
    "Running hybrid semantic and keyword retrieval across every project.";
  $("search-results-list").className = "search-results-list empty-state";
  $("search-results-list").textContent = "Searching the knowledge index…";
  try {
    const response = await api("/api/search", {
      method: "POST",
      body: { query, top_k: 20 },
    });
    state.searchResults = response.hits;
    renderSearchResults(response);
  } finally {
    submit.disabled = false;
    submit.textContent = "Search all projects";
  }
}

function renderSearchResults(response) {
  const list = $("search-results-list");
  list.replaceChildren();
  $("search-results-title").textContent = `Results for “${response.query}”`;
  const count = response.hits.length;
  const noun = count === 1 ? "document" : "documents";
  const warning = response.warnings.length
    ? " One retrieval channel was temporarily unavailable."
    : "";
  $("search-results-summary").textContent =
    `${count} relevant ${noun} across the workspace.${warning}`;
  if (!count) {
    list.className = "search-results-list empty-state";
    list.textContent =
      "No matching project documents were found. Try a broader phrase or different terminology.";
    return;
  }
  list.className = "search-results-list";
  for (const hit of response.hits) list.append(searchResultCard(hit));
}

function searchResultCard(hit) {
  const card = document.createElement("article");
  card.className = "search-result-card";
  const open = document.createElement("button");
  open.type = "button";
  open.className = "search-result-open";
  open.title = `Open ${hit.project_name}`;
  const context = document.createElement("div");
  context.className = "search-result-context";
  const project = document.createElement("span");
  project.className = "search-project-pill";
  project.textContent = hit.project_name;
  const locator = document.createElement("span");
  locator.className = "search-result-locator";
  locator.textContent = searchResultLocator(hit);
  context.append(project, locator);
  const title = document.createElement("h2");
  title.textContent = hit.document_name;
  const preview = document.createElement("p");
  preview.textContent = hit.text_preview;
  open.append(context, title, preview);
  open.addEventListener("click", () => openSearchResult(hit).catch(handleError));

  const actions = document.createElement("div");
  actions.className = "search-result-actions";
  const openProject = document.createElement("button");
  openProject.type = "button";
  openProject.className = "button button-quiet button-small";
  openProject.textContent = "Open project";
  openProject.addEventListener("click", () => {
    openSearchResult(hit).catch(handleError);
  });
  const downloads = document.createElement("div");
  downloads.className = "document-downloads";
  downloads.append(
    documentDownloadButton(hit, "original", "Original"),
    documentDownloadButton(hit, "markdown", "Markdown"),
  );
  actions.append(openProject, downloads);
  card.append(open, actions);
  return card;
}

function searchResultLocator(hit) {
  if (hit.locator) return hit.locator;
  if (hit.page_number && hit.page_count) {
    return `Page ${hit.page_number} of ${hit.page_count}`;
  }
  if (hit.page_number) return `Page ${hit.page_number}`;
  return hit.source_type || "Project document";
}

async function openSearchResult(hit) {
  activateTab("documents");
  await selectProject(hit.project_id);
  const row = [...document.querySelectorAll("[data-document-id]")].find(
    (item) => item.dataset.documentId === hit.document_id,
  );
  if (!row) return;
  row.classList.add("document-focus");
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(() => row.classList.remove("document-focus"), 2600);
}

function renderSelectedProject() {
  const project = state.selectedProject;
  $("selected-project-name").textContent = project?.name || "Choose a project";
  $("selected-project-description").textContent = project?.description || (project ? project.project_id : "Create a project before uploading documents.");
  $("drop-zone").style.pointerEvents = project ? "auto" : "none";
  $("drop-zone").style.opacity = project ? "1" : ".48";
}

async function loadDocuments() {
  if (!state.selectedProject) {
    state.documents = [];
    renderDocuments();
    return;
  }
  state.documents = await api(`/api/projects/${state.selectedProject.project_id}/documents`);
  renderDocuments();
}

function renderDocuments() {
  const list = $("document-list");
  list.replaceChildren();
  if (!state.selectedProject) {
    list.className = "document-list empty-state";
    list.textContent = "Select a project to view its documents.";
    return;
  }
  if (!state.documents.length) {
    list.className = "document-list empty-state";
    list.textContent = "No documents yet. Upload the first source file above.";
    return;
  }
  list.className = "document-list";
  for (const item of state.documents) {
    list.append(documentRow(item));
  }
}

function documentRow(item) {
  const row = document.createElement("article");
  row.className = "document-row";
  row.dataset.documentId = item.document_id;
  const main = document.createElement("div");
  main.className = "document-main";
  const icon = document.createElement("span");
  icon.className = "file-icon";
  icon.textContent = fileExtension(item.document_name) || "doc";
  const copy = document.createElement("div");
  copy.className = "document-copy";
  const name = document.createElement("strong");
  name.textContent = item.document_name;
  const meta = document.createElement("span");
  meta.textContent = `${item.source_type || "UPLOADED"} · ${formatDate(item.updated_at)}`;
  copy.append(name, meta);
  main.append(icon, copy);
  const status = document.createElement("span");
  status.className = `status-pill ${statusClass(item.status)}`;
  status.textContent = item.status;
  status.title = item.error || "";
  const controls = document.createElement("div");
  controls.className = "document-controls";
  const downloads = document.createElement("div");
  downloads.className = "document-downloads";
  downloads.append(
    documentDownloadButton(item, "original", "Original"),
    documentDownloadButton(item, "markdown", "Markdown"),
  );
  controls.append(status, downloads);
  row.append(main, controls);
  return row;
}

function documentDownloadButton(item, downloadFormat, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "document-download-button";
  button.textContent = label;
  const markdownUnavailable =
    downloadFormat === "markdown" && !markdownAvailable(item);
  button.disabled = markdownUnavailable;
  button.title = markdownUnavailable
    ? "Consolidated Markdown will be available when ingestion finishes."
    : `Download ${label.toLowerCase()}`;
  button.addEventListener("click", () => {
    downloadDocument(item, downloadFormat, button).catch(handleError);
  });
  return button;
}

async function downloadDocument(item, downloadFormat, button) {
  const previousLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Preparing…";
  try {
    const download = await api(
      `/api/projects/${item.project_id}/documents/${item.document_id}/download-url?download_format=${downloadFormat}`,
    );
    const link = document.createElement("a");
    link.href = download.url;
    link.download = download.filename;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
    toast(`${download.filename} download started.`);
  } finally {
    button.disabled =
      downloadFormat === "markdown" && !markdownAvailable(item);
    button.textContent = previousLabel;
  }
}

function markdownAvailable(item) {
  return Boolean(item.enhanced_s3_key || item.markdown_available);
}

async function handleFile(file) {
  if (!state.selectedProject) return toast("Choose a project first.", true);
  const maxUploadBytes = state.config.max_upload_bytes;
  if (file.size > maxUploadBytes) {
    const limitMib = Math.floor(maxUploadBytes / (1024 * 1024));
    return toast(`The file is larger than the ${limitMib} MiB limit.`, true);
  }
  showProgress(file.name, 0);
  try {
    const presigned = await api(`/api/projects/${state.selectedProject.project_id}/uploads/presign`, {
      method: "POST",
      body: {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      },
    });
    await uploadToS3(presigned, file);
    showProgress(file.name, 100);
    toast("Upload complete. Ingestion has started.");
    await loadDocuments();
    setTimeout(() => $("upload-progress").classList.add("hidden"), 1800);
  } catch (error) {
    toast(readableError(error), true);
    $("upload-progress").classList.add("hidden");
  } finally {
    $("file-input").value = "";
  }
}

function uploadToS3(presigned, file) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(presigned.fields)) form.append(key, value);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", presigned.upload_url);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) showProgress(file.name, Math.round((event.loaded / event.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`S3 upload failed (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("The S3 upload could not be completed.")));
    xhr.send(form);
  });
}

function showProgress(filename, percent) {
  $("upload-progress").classList.remove("hidden");
  $("upload-filename").textContent = filename;
  $("upload-percent").textContent = `${percent}%`;
  $("progress-bar").style.width = `${percent}%`;
}

async function loadQuestions() {
  state.questions = await api("/api/questions/assigned");
  $("question-count").textContent = state.questions.length;
  if (state.selectedQuestion) {
    state.selectedQuestion = state.questions.find((item) => item.question_id === state.selectedQuestion.question_id) || null;
  }
  const requestedQuestionId = sessionStorage.getItem("requested_question_id");
  if (requestedQuestionId) {
    const requested = state.questions.find((item) => item.question_id === requestedQuestionId);
    if (requested) {
      state.selectedQuestion = requested;
      sessionStorage.removeItem("requested_question_id");
      activateTab("questions");
    }
  }
  renderQuestions();
  renderAnswerPane();
}

function renderQuestions() {
  const list = $("question-list");
  list.replaceChildren();
  if (!state.questions.length) {
    list.className = "question-list empty-state";
    list.textContent = "No open questions are assigned to you.";
    return;
  }
  list.className = "question-list";
  for (const item of state.questions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `question-button${state.selectedQuestion?.question_id === item.question_id ? " active" : ""}`;
    const question = document.createElement("strong");
    question.textContent = item.question;
    const meta = document.createElement("div");
    meta.className = "question-meta";
    const project = document.createElement("span");
    project.textContent = item.project_name;
    const status = document.createElement("span");
    status.textContent = item.status.replaceAll("_", " ");
    meta.append(project, status);
    button.append(question, meta);
    button.addEventListener("click", () => {
      state.selectedQuestion = item;
      renderQuestions();
      renderAnswerPane();
    });
    list.append(button);
  }
}

function renderAnswerPane() {
  const pane = $("answer-pane");
  pane.replaceChildren();
  const item = state.selectedQuestion;
  if (!item) {
    pane.className = "answer-pane empty-answer";
    const wrap = document.createElement("div");
    const glyph = document.createElement("span");
    glyph.className = "answer-glyph";
    glyph.textContent = "?";
    const title = document.createElement("h3");
    title.textContent = "Select a question";
    const text = document.createElement("p");
    text.textContent = "The server will review your answer and index it when it is sufficient.";
    wrap.append(glyph, title, text);
    pane.append(wrap);
    return;
  }

  pane.className = "answer-pane";
  const form = document.createElement("form");
  form.className = "answer-form";
  const heading = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = item.project_name;
  const title = document.createElement("h3");
  title.textContent = item.question;
  heading.append(eyebrow, title);
  form.append(heading);

  if (item.reply_address) {
    const emailNote = document.createElement("p");
    emailNote.className = "review-note";
    const notification = (item.notification_status || "UNKNOWN").replaceAll("_", " ").toLowerCase();
    emailNote.textContent = `Email notification: ${notification}. You can normally answer by replying directly to the request email; this form is the fallback.`;
    form.append(emailNote);
  }

  if (item.context) {
    const context = document.createElement("div");
    context.className = "question-context";
    const contextTitle = document.createElement("h4");
    contextTitle.textContent = "Agent context";
    const contextText = document.createElement("p");
    contextText.textContent = item.context;
    context.append(contextTitle, contextText);
    form.append(context);
  }

  if (item.status === "NEEDS_MORE_INFO" && item.review_rationale) {
    const feedback = document.createElement("div");
    feedback.className = "review-feedback";
    const feedbackTitle = document.createElement("h4");
    feedbackTitle.textContent = "Review feedback";
    const feedbackText = document.createElement("p");
    feedbackText.textContent = item.review_rationale;
    feedback.append(feedbackTitle, feedbackText);
    form.append(feedback);
  }

  const label = document.createElement("label");
  label.textContent = "Your answer";
  const textarea = document.createElement("textarea");
  textarea.required = true;
  textarea.maxLength = 20000;
  textarea.placeholder = "Give a direct, reusable answer. Include the concrete detail the agent was missing.";
  label.append(textarea);
  const note = document.createElement("p");
  note.className = "review-note";
  note.textContent = "After submission, a server-side OpenAI call checks sufficiency. Accepted answers become a small Markdown source document and a verified DynamoDB fact.";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "button button-primary";
  submit.textContent = "Submit for review";
  form.append(label, note, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "Submitting…";
    try {
      await api(`/api/projects/${item.project_id}/questions/${item.question_id}/answers`, {
        method: "POST",
        body: { answer: textarea.value.trim() },
      });
      toast("Answer submitted. The review Lambda is processing it.");
      state.selectedQuestion = null;
      await loadQuestions();
    } catch (error) {
      toast(readableError(error), true);
    } finally {
      submit.disabled = false;
      submit.textContent = "Submit for review";
    }
  });
  pane.append(form);
}

function activateTab(name) {
  for (const button of document.querySelectorAll(".segment")) button.classList.toggle("active", button.dataset.tab === name);
  $("documents-tab").classList.toggle("hidden", name !== "documents");
  $("questions-tab").classList.toggle("hidden", name !== "questions");
}

function switchTab(name) {
  activateTab(name);
  if (name === "questions") loadQuestions().catch(handleError);
}

function startPolling() {
  clearInterval(state.pollingTimer);
  state.pollingTimer = setInterval(() => {
    if (!document.hidden) {
      loadQuestions().catch(console.error);
      if (state.selectedProject) loadDocuments().catch(console.error);
    }
  }, 6000);
}

async function api(path, options = {}) {
  const authEnabled = state.config.mcp_auth_enabled;
  if (authEnabled) await ensureFreshTokens();
  const response = await fetch(`${state.config.api_base_url}${path}`, {
    method: options.method || "GET",
    headers: {
      ...(authEnabled ? { Authorization: `Bearer ${state.tokens.id_token}` } : {}),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401 && authEnabled) {
    clearSession();
    throw new Error("Your session expired. Reload and sign in again.");
  }
  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
  return payload;
}

async function publicQuestionApi(path, options = {}) {
  const response = await fetch(`${state.config.api_base_url}${path}`, {
    method: options.method || "GET",
    cache: "no-store",
    headers: {
      "X-Answer-Token": state.answerToken,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  return payload;
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${url}`);
  return response.json();
}

function cognitoBaseUrl() {
  return state.config.cognito_domain.replace(/\/$/, "");
}

function saveTokens(tokens) {
  state.tokens = tokens;
  sessionStorage.setItem("cognito_tokens", JSON.stringify(tokens));
}
function readTokens() {
  const raw = sessionStorage.getItem("cognito_tokens");
  return raw ? safeJson(raw) : null;
}
function clearSession() {
  state.tokens = null;
  sessionStorage.removeItem("cognito_tokens");
  sessionStorage.removeItem("pkce_verifier");
}
function decodeJwt(token) {
  const payload = token.split(".")[1];
  return JSON.parse(new TextDecoder().decode(base64UrlBytes(payload)));
}
function randomBase64Url(length) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return bytesBase64Url(bytes);
}
async function sha256Base64Url(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return bytesBase64Url(new Uint8Array(digest));
}
function bytesBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}
function base64UrlBytes(value) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((value.length + 3) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}
function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}
function fileExtension(name) {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1, index + 5) : "doc";
}
function formatDate(value) {
  if (!value) return "unknown time";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
function statusClass(status) {
  if (status === "READY") return "status-ready";
  if (status === "FAILED") return "status-failed";
  return "status-working";
}
function readableError(error) {
  return error instanceof Error ? error.message : String(error);
}
function capitalize(value) {
  return value ? value[0].toUpperCase() + value.slice(1) : "";
}
function handleError(error) {
  console.error(error);
  toast(readableError(error), true);
}

async function copyMcpUrl() {
  await navigator.clipboard.writeText(
    state.config?.mcp_url || "https://essencesentry.shop/mcp/",
  );
  toast("MCP URL copied.");
}

function openPluginModal() {
  $("plugin-modal").classList.remove("hidden");
  document.body.classList.add("modal-open");
  $("close-plugin-modal").focus();
}

function closePluginModal() {
  $("plugin-modal").classList.add("hidden");
  document.body.classList.remove("modal-open");
}

async function copyInstallCommand(button) {
  const target = $(button.dataset.copyTarget);
  if (!target) return;
  await navigator.clipboard.writeText(target.textContent.trim());
  toast("Install commands copied.");
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.className = `toast${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 4500);
}

$("login-button").addEventListener("click", () => beginLogin().catch(handleError));
$("copy-mcp-url").addEventListener("click", () => copyMcpUrl().catch(handleError));
$("copy-mcp-url-modal").addEventListener("click", () => copyMcpUrl().catch(handleError));
$("logout-button").addEventListener("click", logout);
$("close-plugin-modal").addEventListener("click", closePluginModal);
$("plugin-modal").addEventListener("click", (event) => {
  if (event.target === $("plugin-modal")) closePluginModal();
});
$("download-plugin").addEventListener("click", () => {
  toast("Plugin download started.");
});
for (const button of document.querySelectorAll(".open-plugin")) {
  button.addEventListener("click", openPluginModal);
}
for (const button of document.querySelectorAll(".copy-install-command")) {
  button.addEventListener("click", () => copyInstallCommand(button).catch(handleError));
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("plugin-modal").classList.contains("hidden")) {
    closePluginModal();
  }
});
$("show-project-form").addEventListener("click", () => $("project-form").classList.remove("hidden"));
$("cancel-project").addEventListener("click", () => $("project-form").classList.add("hidden"));
$("project-form").addEventListener("submit", (event) => createProject(event).catch(handleError));
$("global-search-form").addEventListener("submit", (event) => searchAllProjects(event).catch(handleError));
$("close-search-results").addEventListener("click", showWorkspace);
$("refresh-documents").addEventListener("click", () => loadDocuments().catch(handleError));
$("refresh-questions").addEventListener("click", () => loadQuestions().catch(handleError));
$("expert-answer-form").addEventListener("submit", (event) => submitExpertAnswer(event));
for (const button of document.querySelectorAll(".segment")) button.addEventListener("click", () => switchTab(button.dataset.tab));

const dropZone = $("drop-zone");
for (const eventName of ["dragenter", "dragover"]) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const eventName of ["dragleave", "drop"]) dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", (event) => { const file = event.dataTransfer.files[0]; if (file) handleFile(file); });
$("file-input").addEventListener("change", (event) => { const file = event.target.files[0]; if (file) handleFile(file); });

main();
