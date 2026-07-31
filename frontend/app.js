const state = {
  config: null,
  tokens: null,
  me: null,
  uploadProjectId: null,
  uploads: new Map(),
  pollingTimer: null,
};

const $ = (id) => document.getElementById(id);

async function main() {
  try {
    state.config = await fetchJson("/config.json");
    if ($("mcp-url")) $("mcp-url").value = state.config.mcp_url;
    if (
      $("legacy-answer-notice") &&
      window.location.hash.includes("answer=")
    ) {
      $("legacy-answer-notice").classList.remove("hidden");
      window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}`);
    }
    if (!state.config.mcp_auth_enabled) {
      throw new Error("This deployment must enable Blend authentication.");
    }
    await completeAuthorizationIfPresent();
    state.tokens = readTokens();
    if (state.tokens) {
      await ensureFreshTokens();
      await enterAuthenticatedMode();
    } else {
      enterPublicMode();
    }
  } catch (error) {
    console.error(error);
    enterPublicMode();
    toast(readableError(error), true);
  } finally {
    $("loading-view")?.classList.add("hidden");
    $("connection-view")?.classList.remove("hidden");
    $("upload-view")?.classList.remove("hidden");
  }
}

function enterPublicMode() {
  $("user-area")?.classList.add("hidden");
  $("upload-panel")?.classList.add("hidden");
  $("upload-auth-gate")?.classList.remove("hidden");
  $("login-button")?.classList.remove("hidden");
}

async function enterAuthenticatedMode() {
  state.me = await api("/api/me");
  if ($("user-email")) $("user-email").textContent = state.me.email;
  $("user-area")?.classList.remove("hidden");
  $("login-button")?.classList.add("hidden");
  $("upload-auth-gate")?.classList.add("hidden");
  if ($("upload-panel")) {
    $("upload-panel").classList.remove("hidden");
    const limitMib = Math.floor(
      state.config.max_upload_bytes / (1024 * 1024),
    );
    $("upload-limit").textContent = `${limitMib} MiB per file`;
    await loadUploadProject();
    startPolling();
  }
}

async function beginLogin() {
  if (document.body.dataset.page === "upload") {
    sessionStorage.setItem(
      "post_login_path",
      `${window.location.pathname}${window.location.search}`,
    );
  } else {
    sessionStorage.removeItem("post_login_path");
  }
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
  if (error) throw new Error(url.searchParams.get("error_description") || error);
  if (!code) return;

  const verifier = sessionStorage.getItem("pkce_verifier");
  if (!verifier) throw new Error("The login verifier was lost; sign in again.");
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
  saveTokens(await response.json());
  sessionStorage.removeItem("pkce_verifier");
  const postLoginPath = sessionStorage.getItem("post_login_path");
  sessionStorage.removeItem("post_login_path");
  if (
    postLoginPath &&
    postLoginPath !== `${url.pathname}${url.search}`
  ) {
    window.location.replace(postLoginPath);
    return;
  }
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  window.history.replaceState({}, "", `${url.pathname}${url.search}`);
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
  state.tokens = { ...state.tokens, ...(await response.json()) };
  saveTokens(state.tokens);
}

async function loadUploadProject() {
  const requested = new URL(window.location.href).searchParams.get(
    "upload_project_id",
  );
  if (!requested) {
    showUploadContextError(
      "This upload link has no project context. Reopen the link provided by your agent or project email.",
    );
    return;
  }
  try {
    const project = await api(`/api/projects/${encodeURIComponent(requested)}`);
    if (!project.can_edit) {
      throw new Error(
        "You do not have permission to upload documents to this project.",
      );
    }
    state.uploadProjectId = project.project_id;
    $("upload-project-name").textContent = project.name;
    $("upload-project-role").textContent = project.my_role.toLowerCase();
    $("upload-project-context").classList.remove("hidden");
    $("upload-context-error").classList.add("hidden");
    $("upload-controls").classList.remove("hidden");
  } catch (error) {
    showUploadContextError(readableError(error));
  }
}

function showUploadContextError(message) {
  state.uploadProjectId = null;
  $("upload-context-error").textContent = message;
  $("upload-context-error").classList.remove("hidden");
  $("upload-project-context").classList.add("hidden");
  $("upload-controls").classList.add("hidden");
}

async function uploadFiles(files) {
  const projectId = state.uploadProjectId;
  if (!projectId) {
    return toast("Open a valid project upload link first.", true);
  }
  const requestedId = new URL(window.location.href).searchParams.get("upload_request_id");
  let index = 0;
  for (const file of files) {
    index += 1;
    const requestId = index === 1 && requestedId ? requestedId : crypto.randomUUID();
    await uploadFile(projectId, file, requestId);
  }
}

async function uploadFile(projectId, file, requestId) {
  if (file.size > state.config.max_upload_bytes) {
    return toast(`${file.name} exceeds the upload limit.`, true);
  }
  const rowId = `upload-${requestId.replaceAll(/[^A-Za-z0-9_-]/g, "-")}`;
  const record = {
    rowId,
    filename: file.name,
    status: "Preparing upload",
    percent: 0,
    projectId,
    documentId: null,
  };
  state.uploads.set(rowId, record);
  renderUploads();
  try {
    const session = await api(`/api/projects/${projectId}/uploads/presign`, {
      method: "POST",
      headers: { "Idempotency-Key": requestId },
      body: {
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        request_id: requestId,
      },
    });
    record.documentId = session.document.document_id;
    if (!session.upload_required) {
      record.percent = 100;
      record.status = session.document.status;
      record.failed = session.document.status === "FAILED";
      record.error = session.document.error || null;
      renderUploads();
      return;
    }
    record.status = "Uploading directly to S3";
    renderUploads();
    await uploadToS3(session, file, (percent) => {
      record.percent = percent;
      renderUploads();
    });
    record.percent = 100;
    record.status = "Queued for ingestion";
    renderUploads();
  } catch (error) {
    record.status = `Failed: ${readableError(error)}`;
    record.failed = true;
    renderUploads();
  }
}

function uploadToS3(session, file, onProgress) {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    for (const [key, value] of Object.entries(session.fields)) data.append(key, value);
    data.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", session.upload_url);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`S3 upload failed (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("The S3 upload could not complete.")));
    xhr.send(data);
  });
}

async function pollUploads() {
  for (const record of state.uploads.values()) {
    if (!record.documentId || record.failed || ["READY", "FAILED"].includes(record.status)) continue;
    try {
      const document = await api(
        `/api/projects/${record.projectId}/documents/${record.documentId}`,
      );
      record.status = document.status;
      record.failed = document.status === "FAILED";
      record.error = document.error || null;
    } catch (error) {
      console.error(error);
    }
  }
  renderUploads();
}

function startPolling() {
  clearInterval(state.pollingTimer);
  state.pollingTimer = setInterval(() => pollUploads().catch(console.error), 5000);
}

function renderUploads() {
  const list = $("upload-list");
  if (!list) return;
  list.replaceChildren();
  for (const record of state.uploads.values()) {
    const row = document.createElement("article");
    row.className = `upload-row${record.failed ? " failed" : ""}`;
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = record.filename;
    const status = document.createElement("span");
    status.textContent = record.error ? `${record.status}: ${record.error}` : record.status;
    copy.append(name, status);
    const progress = document.createElement("div");
    progress.className = "progress";
    const bar = document.createElement("i");
    bar.style.width = `${record.percent}%`;
    progress.append(bar);
    row.append(copy, progress);
    list.append(row);
  }
}

async function api(path, options = {}) {
  await ensureFreshTokens();
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
    Authorization: `Bearer ${state.tokens.id_token}`,
  };
  const response = await fetch(`${state.config.api_base_url}${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
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
  sessionStorage.setItem("blend_tokens", JSON.stringify(tokens));
}

function readTokens() {
  return safeJson(sessionStorage.getItem("blend_tokens") || "");
}

function clearSession() {
  state.tokens = null;
  sessionStorage.removeItem("blend_tokens");
}

function logout() {
  clearSession();
  const params = new URLSearchParams({
    client_id: state.config.client_id,
    logout_uri: state.config.logout_uri,
  });
  window.location.assign(`${cognitoBaseUrl()}/logout?${params}`);
}

function decodeJwt(token) {
  return safeJson(new TextDecoder().decode(base64UrlBytes(token.split(".")[1]))) || {};
}

function randomBase64Url(length) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return bytesBase64Url(bytes);
}

async function sha256Base64Url(value) {
  return bytesBase64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
}

function bytesBase64Url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlBytes(value) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

function readableError(error) {
  return error instanceof Error ? error.message : String(error);
}

async function copyMcpUrl() {
  await navigator.clipboard.writeText(state.config.mcp_url);
  toast("MCP URL copied.");
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("toast");
  if (!node) return;
  node.textContent = message;
  node.className = `toast${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add("hidden"), 4500);
}

$("login-button")?.addEventListener("click", () =>
  beginLogin().catch((error) => toast(readableError(error), true)),
);
$("logout-button")?.addEventListener("click", logout);
$("copy-mcp-url")?.addEventListener("click", () =>
  copyMcpUrl().catch(console.error),
);

const dropZone = $("drop-zone");
if (dropZone) {
  for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  }
  dropZone.addEventListener("drop", (event) => {
    if (event.dataTransfer.files.length) {
      uploadFiles([...event.dataTransfer.files]);
    }
  });
}
$("file-input")?.addEventListener("change", (event) => {
  if (event.target.files.length) {
    uploadFiles([...event.target.files]);
  }
  event.target.value = "";
});

main();
