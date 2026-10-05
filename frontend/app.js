/* AI Job-Hunt Copilot — vanilla JS client. No build step, no dependencies. */
"use strict";

/* =====================================================================
 * Utilities
 * ===================================================================== */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

/**
 * Auto-escaping template tag. Every interpolated value is HTML-escaped unless it is itself
 * the result of `html` (or wrapped in `raw`). Generated resume text is untrusted LLM output,
 * so escaping must be the default, not something each call site has to remember.
 */
class Safe {
  constructor(markup) {
    this.markup = markup;
  }
}
const raw = (markup) => new Safe(markup);

function toMarkup(value) {
  if (value instanceof Safe) return value.markup;
  if (Array.isArray(value)) return value.map(toMarkup).join("");
  if (value === null || value === undefined || value === false) return "";
  return esc(value);
}

function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, i) => {
    out += toMarkup(value) + strings[i + 1];
  });
  return new Safe(out);
}

const setHtml = (element, safe) => {
  element.innerHTML = safe.markup;
};

const store = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* storage blocked (private mode): the key just won't persist */
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};
const API_KEY_STORE = "copilot.apiKey";

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const fmtDate = (iso) => (iso ? dateFormat.format(new Date(iso)) : "");

function timeAgo(iso) {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(-Math.round(seconds / size), unit);
  }
  return "just now";
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const seconds = (ms) => `${(ms / 1000).toFixed(1)}s`;
const scoreTone = (score) => (score >= 70 ? "good" : score >= 45 ? "warn" : "bad");
const SKILL_TONE = { strong: "good", partial: "warn", missing: "bad" };
const safeUrl = (url) => (/^https?:\/\//i.test(url || "") ? url : "");
const parseTags = (text) => text.split(",").map((t) => t.trim()).filter(Boolean);

function toast(message, kind = "info") {
  const element = document.createElement("div");
  element.className = kind === "error" ? "toast error" : "toast";
  element.textContent = message;
  const tray = $("#toasts");
  tray.append(element);
  while (tray.children.length > 3) tray.firstElementChild.remove(); // newest wins; never bury the page
  setTimeout(() => element.remove(), kind === "error" ? 7000 : 3500);
}

async function copyText(text, label = "Copied to clipboard") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.className = "sr-only";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  toast(label);
}

function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Two-step destructive action: the first click arms the button, a second within 3s confirms. */
function confirmClick(button, onConfirm) {
  if (button.dataset.armed) {
    clearTimeout(Number(button.dataset.armed));
    disarm(button);
    return onConfirm();
  }
  button.dataset.label = button.textContent;
  button.textContent = "Click again to confirm";
  button.classList.add("armed");
  button.dataset.armed = String(setTimeout(() => disarm(button), 3000));
}

function disarm(button) {
  delete button.dataset.armed;
  button.classList.remove("armed");
  button.textContent = button.dataset.label;
}

/** Disable a button while a task runs; route failures to `onError` (default: toast). */
async function withBusy(button, task, onError = (error) => toast(error.message, "error")) {
  button.disabled = true;
  try {
    return await task();
  } catch (error) {
    if (error.status !== 401) onError(error);
  } finally {
    button.disabled = false;
  }
}

/* =====================================================================
 * API client
 * ===================================================================== */

const API = "/api/v1";

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(response) {
  const body = await response.json().catch(() => null);
  if (body?.error?.message) return body.error.message;
  if (Array.isArray(body?.detail)) {
    // FastAPI's own request-validation shape: [{loc: ["body", "field"], msg}]
    return body.detail.map((d) => `${(d.loc || []).slice(1).join(".") || "request"}: ${d.msg}`).join("; ");
  }
  if (response.status === 429) return "Too many requests. Wait a moment and try again.";
  return `Request failed (${response.status})`;
}

async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  const key = store.get(API_KEY_STORE);
  if (key) headers["X-API-Key"] = key;
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form; // the browser sets the multipart boundary
  }

  let response;
  try {
    response = await fetch(API + path, { method, headers, body });
  } catch {
    throw new ApiError("Cannot reach the server. Check your connection.", 0);
  }
  if (response.status === 401) document.dispatchEvent(new CustomEvent("auth-required"));
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return response.status === 204 ? null : response.json();
}

/** Run a loader; surface failures as toasts (a 401 is handled by the API-key dialog instead). */
async function guarded(task) {
  try {
    return await task();
  } catch (error) {
    if (error.status !== 401) toast(error.message, "error");
    return undefined;
  }
}

/* =====================================================================
 * State and loaders
 * ===================================================================== */

const RUN_PAGE_SIZE = 20;
const STATUSES = [
  ["saved", "Saved"],
  ["applied", "Applied"],
  ["interviewing", "Interviewing"],
  ["offer", "Offer"],
  ["rejected", "Rejected"],
  ["withdrawn", "Withdrawn"],
];

const state = {
  documents: [],
  documentsLoaded: false,
  runs: [],
  runsExhausted: false,
  applications: [],
  current: null, // the TailorResponse currently displayed
  running: false,
};

const setCount = (name, text) => {
  $(`#count-${name}`).textContent = text;
};

const loadDocuments = () =>
  guarded(async () => {
    state.documents = await api("/profile/documents");
    state.documentsLoaded = true;
    renderDocuments();
  });

const loadRuns = ({ more = false } = {}) =>
  guarded(async () => {
    const page = await api(`/runs?limit=${RUN_PAGE_SIZE}&offset=${more ? state.runs.length : 0}`);
    state.runs = more ? state.runs.concat(page) : page;
    state.runsExhausted = page.length < RUN_PAGE_SIZE;
    renderRuns();
  });

const loadApplications = () =>
  guarded(async () => {
    state.applications = await api("/applications");
    renderTracker();
    refreshTrackButton();
  });

async function loadHealth() {
  try {
    const health = await (await fetch("/healthz")).json();
    const pill = $("#provider-pill");
    const demo = health.llm_provider === "fake";
    pill.textContent = demo ? "Demo mode" : `LLM: ${health.llm_provider}`;
    pill.className = demo ? "badge warn" : "badge accent";
    pill.title = demo
      ? "Running on the offline fake LLM — output is synthetic. Set LLM_PROVIDER=gemini for real results."
      : `Generating with ${health.llm_provider}`;
    pill.hidden = false;
  } catch {
    /* the pill is a nicety; ignore failures */
  }
}

const reloadAll = () => Promise.all([loadDocuments(), loadRuns(), loadApplications()]);

/* =====================================================================
 * Corpus
 * ===================================================================== */

const UPLOAD_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

function renderDocuments() {
  const docs = state.documents;
  setCount("corpus", docs.length);
  $("#corpus-banner").hidden = !state.documentsLoaded || docs.length > 0;
  const chunks = docs.reduce((total, doc) => total + doc.chunk_count, 0);
  $("#doc-summary").textContent = docs.length ? `${plural(docs.length, "document")} · ${plural(chunks, "chunk")}` : "";

  if (!docs.length) {
    setHtml(
      $("#doc-list"),
      html`<li class="empty"><div><strong>Nothing indexed yet</strong>Add your resume, projects and
        experience above. The copilot will only ever claim what it finds here.</div></li>`,
    );
    return;
  }
  setHtml(
    $("#doc-list"),
    html`${docs.map(
      (doc) => html`<li>
        <div class="item-main">
          <div class="item-title">${doc.title} <span class="badge accent">${doc.kind}</span></div>
          <div class="small muted">${plural(doc.chunk_count, "chunk")} · ${doc.char_count.toLocaleString()} characters ·
            ${timeAgo(doc.created_at)}</div>
          ${doc.tags.length
            ? html`<span class="tags">${doc.tags.map((tag) => html`<span class="badge">${tag}</span>`)}</span>`
            : ""}
        </div>
        <div class="item-actions">
          <button type="button" class="btn sm" data-action="view-doc" data-id="${doc.id}">View chunks</button>
          <button type="button" class="btn sm danger" data-action="delete-doc" data-id="${doc.id}">Remove</button>
        </div>
      </li>`,
    )}`,
  );
}

async function openChunks(id) {
  await guarded(async () => {
    const doc = await api(`/profile/documents/${encodeURIComponent(id)}`);
    $("#chunks-title").textContent = doc.title;
    $("#chunks-meta").textContent =
      `${doc.kind} · ${plural(doc.chunks.length, "chunk")} · indexed ${fmtDate(doc.created_at)}`;
    setHtml(
      $("#chunks-body"),
      doc.chunks.length
        ? html`${doc.chunks.map(
            (chunk) => html`<article class="chunk">
              <header><code class="chip static">${chunk.id}</code></header>
              <p>${chunk.text}</p>
            </article>`,
          )}`
        : html`<p class="muted">No chunks are stored for this document.</p>`,
    );
    $("#chunks-dialog").showModal();
  });
}

async function deleteDocument(id) {
  await guarded(async () => {
    await api(`/profile/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Document removed");
    await loadDocuments();
  });
}

function uploadProblem(file) {
  const extension = file.name.includes(".") ? `.${file.name.split(".").pop().toLowerCase()}` : "";
  if (!UPLOAD_EXTENSIONS.includes(extension)) return `Unsupported file type. Use ${UPLOAD_EXTENSIONS.join(", ")}.`;
  if (file.size > MAX_UPLOAD_BYTES) return "That file is over the 5 MB limit.";
  return "";
}

async function uploadFile(file) {
  const problem = uploadProblem(file);
  if (problem) return toast(problem, "error");
  const form = new FormData();
  form.append("file", file);
  form.append("kind", $("#doc-kind").value);
  form.append("tags", $("#doc-tags").value);
  const title = $("#doc-title").value.trim();
  if (title) form.append("title", title);

  await withBusy($("#pick-file"), async () => {
    $("#doc-hint").textContent = `Uploading ${file.name}…`;
    try {
      await api("/profile/documents/upload", { method: "POST", form });
      toast(`Indexed ${file.name}`);
      await loadDocuments();
    } finally {
      $("#doc-hint").textContent = "";
    }
  });
}

function wireCorpus() {
  $("#doc-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = $("#doc-content").value.trim();
    if (content.length < 20) {
      $("#doc-hint").textContent = "Add at least a couple of sentences (20+ characters).";
      return;
    }
    $("#doc-hint").textContent = "";
    await withBusy($("#add-doc"), async () => {
      await api("/profile/documents", {
        method: "POST",
        json: {
          title: $("#doc-title").value.trim() || "Untitled",
          kind: $("#doc-kind").value,
          tags: parseTags($("#doc-tags").value),
          content,
        },
      });
      $("#doc-content").value = "";
      $("#doc-title").value = "";
      $("#doc-tags").value = "";
      toast("Document indexed");
      await loadDocuments();
    });
  });

  $("#pick-file").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) uploadFile(file);
  });

  const zone = $("#dropzone");
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("over");
    }),
  );
  ["dragleave", "drop"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("over");
    }),
  );
  zone.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer.files;
    if (file) uploadFile(file);
  });

  $("#doc-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const { action, id } = button.dataset;
    if (action === "view-doc") openChunks(id);
    if (action === "delete-doc") confirmClick(button, () => deleteDocument(id));
  });
}

/* =====================================================================
 * Tailor + results
 * ===================================================================== */

function updateJdState() {
  const jd = $("#jd");
  $("#jd-count").textContent = `${jd.value.length.toLocaleString()} / 20,000 characters (min 50)`;
  $("#run").disabled = state.running || jd.value.trim().length < 50;
}

function wireTailor() {
  const jd = $("#jd");
  jd.addEventListener("input", updateJdState);
  jd.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      $("#tailor-form").requestSubmit();
    }
  });

  $("#tailor-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = jd.value.trim();
    if (state.running || text.length < 50) return;

    state.running = true;
    state.current = null;
    updateJdState();
    $("#results").replaceChildren();
    const status = $("#run-status");
    const started = performance.now();
    const tick = () =>
      setHtml(
        status,
        html`<span class="spinner"></span> Parsing, retrieving, drafting, verifying…
          ${Math.round((performance.now() - started) / 1000)}s`,
      );
    tick();
    const timer = setInterval(tick, 500);

    try {
      const result = await api("/tailor", {
        method: "POST",
        json: {
          job_description: text,
          tone: $("#tone").value,
          include_cover_letter: $("#opt-cover").checked,
          include_interview_prep: $("#opt-interview").checked,
        },
      });
      renderResult(result);
      history.replaceState(null, "", `#/run/${encodeURIComponent(result.run_id)}`);
      status.textContent = `Done in ${seconds(result.latency_ms)}`;
      loadRuns();
    } catch (error) {
      status.textContent = "";
      if (error.status !== 401) {
        setHtml(
          $("#results"),
          html`<div class="banner error" role="alert">${error.message}
            ${error.status === 409 ? html`<a href="#/corpus">Add documents</a>` : ""}</div>`,
        );
      }
    } finally {
      clearInterval(timer);
      state.running = false;
      updateJdState();
    }
  });

  $("#results").addEventListener("click", (event) => {
    const chip = event.target.closest("button.chip[data-evidence]");
    if (chip) return togglePeek(chip);
    const button = event.target.closest("button[data-action]");
    if (!button || !state.current) return;
    const result = state.current;
    switch (button.dataset.action) {
      case "copy-bullet":
        return copyText(result.resume_bullets[Number(button.dataset.index)].text, "Bullet copied");
      case "copy-bullets":
        return copyText(result.resume_bullets.map((b) => `• ${b.text}`).join("\n"), "Bullets copied");
      case "copy-letter":
        return copyText(result.cover_letter, "Cover letter copied");
      case "download-letter":
        return download(`cover-letter-${slug(result.job.company)}.txt`, result.cover_letter, "text/plain");
      case "export":
        return download(`tailored-${slug(result.job.company)}-${slug(result.job.title)}.md`, toMarkdown(result), "text/markdown");
      case "track-run":
        return trackCurrent(button);
    }
  });
}

const slug = (text) =>
  String(text || "job").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "job";

function togglePeek(chip) {
  const host = chip.closest("li");
  const peeks = host.querySelector(".peeks");
  const id = chip.dataset.evidence;
  const open = [...peeks.children].find((node) => node.dataset.for === id);
  if (open) {
    open.remove();
    chip.setAttribute("aria-expanded", "false");
    return;
  }
  const evidence = state.current.evidence.find((item) => item.id === id);
  if (!evidence) return;
  const node = document.createElement("div");
  node.className = "peek";
  node.dataset.for = id;
  setHtml(
    node,
    html`<header>${evidence.document_title} · ${evidence.kind} · chunk ${evidence.position + 1} ·
      similarity ${Number(evidence.score).toFixed(2)} · <span class="mono">${id}</span></header>
      <p>${evidence.text}</p>`,
  );
  peeks.append(node);
  chip.setAttribute("aria-expanded", "true");
}

function renderResult(result) {
  state.current = result;
  const evidence = new Map(result.evidence.map((item) => [item.id, item]));
  const report = result.match_report;
  const tone = scoreTone(report.ats_score);

  // Citations from the drafter are verified by the critic; skill-match citations are not,
  // so a chip whose id isn't in the retrieved evidence is shown as unverified, not clickable.
  const chips = (ids) =>
    ids.map((id) => {
      const item = evidence.get(id);
      return item
        ? html`<button type="button" class="chip" data-evidence="${id}" aria-expanded="false"
            title="${id}">${item.document_title} §${item.position + 1}</button>`
        : html`<span class="chip unverified" title="Not found in the retrieved evidence">${id} (unverified)</span>`;
    });

  const skill = (match) => html`<li>
    <span class="skill-name">${match.skill}</span>
    <span class="badge ${SKILL_TONE[match.status] || ""}">${match.status}</span>
    ${match.note ? html`<div class="small muted">${match.note}</div>` : ""}
    ${match.evidence_ids.length ? html`<div class="row small">${chips(match.evidence_ids)}</div>` : ""}
    <div class="peeks"></div>
  </li>`;
  const skillList = (items, empty) =>
    items.length ? html`<ul>${items.map(skill)}</ul>` : html`<p class="small muted">${empty}</p>`;

  const meta = [
    result.job.seniority && result.job.seniority !== "unknown" ? result.job.seniority : "",
    result.job.location,
    seconds(result.latency_ms),
    fmtDate(result.created_at),
  ].filter(Boolean);

  const sections = [];

  sections.push(html`<section class="card">
    <div class="card-head">
      <div>
        <h2>${result.job.title} <span class="muted">at ${result.job.company}</span></h2>
        <p class="small muted">${meta.join(" · ")} · run <span class="mono">${result.run_id}</span></p>
      </div>
      <div class="row">
        <button type="button" class="btn sm" id="track-run" data-action="track-run">Save to tracker</button>
        <button type="button" class="btn sm" data-action="export">Export Markdown</button>
      </div>
    </div>
    <div class="match-top">
      <div class="score ${tone}">${report.ats_score}<small> / 100 ATS</small></div>
      <div class="meter ${tone}" role="meter" aria-label="ATS score" aria-valuemin="0" aria-valuemax="100"
           aria-valuenow="${report.ats_score}"><span data-width="${report.ats_score}"></span></div>
    </div>
    ${report.summary ? html`<p>${report.summary}</p>` : ""}
    <div class="skills mt-16">
      <div><h3 class="muted">Matched</h3>${skillList(report.matched, "Nothing matched.")}</div>
      <div><h3 class="muted">Gaps</h3>${skillList(report.gaps, "No gaps identified.")}</div>
    </div>
  </section>`);

  sections.push(html`<section class="card">
    <div class="card-head">
      <h2>Tailored resume bullets</h2>
      ${result.resume_bullets.length
        ? html`<button type="button" class="btn sm" data-action="copy-bullets">Copy all</button>`
        : ""}
    </div>
    ${result.resume_bullets.length
      ? html`<ul>${result.resume_bullets.map(
          (bullet, index) => html`<li class="bullet">
            <p class="text">${bullet.text}</p>
            <div class="row small muted">
              <span>→ ${bullet.target_requirement}</span>${chips(bullet.evidence_ids)}
              <button type="button" class="btn sm ghost" data-action="copy-bullet" data-index="${index}">Copy</button>
            </div>
            <div class="peeks"></div>
          </li>`,
        )}</ul>`
      : html`<p class="muted">No bullet survived the grounding check, so none are shown.</p>`}
  </section>`);

  if (result.cover_letter) {
    sections.push(html`<section class="card">
      <div class="card-head">
        <h2>Cover letter</h2>
        <div class="row">
          <button type="button" class="btn sm" data-action="copy-letter">Copy</button>
          <button type="button" class="btn sm" data-action="download-letter">Download .txt</button>
        </div>
      </div>
      <div class="letter">${result.cover_letter}</div>
    </section>`);
  }

  if (result.interview_questions.length) {
    sections.push(html`<section class="card">
      <h2>Interview prep</h2>
      ${result.interview_questions.map(
        (q) => html`<details class="qa">
          <summary>${q.question}</summary>
          ${q.why_asked ? html`<p class="small muted mt-6">Why they ask: ${q.why_asked}</p>` : ""}
          <p class="answer">${q.star_answer}</p>
        </details>`,
      )}
    </section>`);
  }

  if (result.grounding_violations.length) {
    sections.push(html`<section class="card">
      <h2>Rejected by the grounding critic</h2>
      <p class="small muted mb-8">These drafts cited no evidence that exists in your
        corpus, so they were dropped rather than shown.</p>
      ${result.grounding_violations.map(
        (v) => html`<div class="violation">${v.bullet}<div class="small muted">${v.reason}</div></div>`,
      )}
    </section>`);
  }

  sections.push(html`<section class="card">
    <details class="evidence-all">
      <summary>Evidence retrieved (${plural(result.evidence.length, "chunk")})</summary>
      <ul class="stack mt-12">${result.evidence.map(
        (item) => html`<li class="chunk">
          <header class="small muted"><span class="mono">${item.id}</span> · ${item.document_title} ·
            similarity ${Number(item.score).toFixed(2)}
            ${item.matched_requirement ? html`· for “${item.matched_requirement}”` : ""}</header>
          <p>${item.text}</p>
        </li>`,
      )}</ul>
    </details>
  </section>`);

  setHtml($("#results"), html`${sections}`);
  applyMeters($("#results"));
  refreshTrackButton();
}

/** Widths are applied via CSSOM so the page needs no inline style attributes. */
function applyMeters(root) {
  $$("[data-width]", root).forEach((bar) => {
    bar.style.width = `${Math.max(0, Math.min(100, Number(bar.dataset.width)))}%`;
  });
}

function refreshTrackButton() {
  const button = $("#track-run");
  if (!button || !state.current) return;
  const tracked = state.applications.some((app) => app.run_id === state.current.run_id);
  button.disabled = tracked;
  button.textContent = tracked ? "✓ In tracker" : "Save to tracker";
}

async function trackCurrent(button) {
  const result = state.current;
  await withBusy(button, async () => {
    const application = await api("/applications", {
      method: "POST",
      json: {
        job_title: (result.job.title || "Untitled role").slice(0, 200),
        company: (result.job.company || "").slice(0, 200),
        run_id: result.run_id,
      },
    });
    state.applications.unshift(application);
    renderTracker();
    toast("Saved to tracker");
  });
  // withBusy re-enables the button when the task ends; re-apply the "already tracked" lock after it.
  refreshTrackButton();
}

function toMarkdown(result) {
  const report = result.match_report;
  const lines = [
    `# ${result.job.title} — ${result.job.company}`,
    "",
    `ATS score: ${report.ats_score}/100`,
    "",
    report.summary,
    "",
    "## Resume bullets",
    "",
    ...result.resume_bullets.map((b) => `- ${b.text}  \n  _Evidence: ${b.evidence_ids.join(", ")}_`),
    "",
  ];
  if (report.gaps.length) {
    lines.push("## Gaps", "", ...report.gaps.map((g) => `- ${g.skill}${g.note ? ` — ${g.note}` : ""}`), "");
  }
  if (result.cover_letter) lines.push("## Cover letter", "", result.cover_letter, "");
  if (result.interview_questions.length) {
    lines.push("## Interview prep", "");
    result.interview_questions.forEach((q) => {
      lines.push(`### ${q.question}`, "");
      if (q.why_asked) lines.push(`_Why they ask:_ ${q.why_asked}`, "");
      lines.push(q.star_answer, "");
    });
  }
  return lines.join("\n");
}

async function openRun(id) {
  if (state.current?.run_id === id) return; // already on screen
  await guarded(async () => {
    try {
      renderResult(await api(`/runs/${encodeURIComponent(id)}`));
      $("#run-status").textContent = "";
    } catch (error) {
      if (error.status !== 404) throw error;
      toast("That run no longer exists.", "error");
      location.hash = "#/history";
    }
  });
}

/* =====================================================================
 * History
 * ===================================================================== */

function renderRuns() {
  setCount("history", `${state.runs.length}${state.runsExhausted ? "" : "+"}`);
  $("#more-runs").parentElement.hidden = state.runsExhausted; // hide the row so it leaves no gap
  if (!state.runs.length) {
    setHtml(
      $("#run-list"),
      html`<li class="empty"><div><strong>No runs yet</strong>Tailor your first application and it will
        show up here.</div></li>`,
    );
    return;
  }
  setHtml(
    $("#run-list"),
    html`${state.runs.map(
      (run) => html`<li>
        <div class="item-main">
          <div class="item-title">${run.job_title || "Untitled role"}
            <span class="muted">· ${run.company || "Unknown company"}</span></div>
          <div class="small muted"><span title="${fmtDate(run.created_at)}">${timeAgo(run.created_at)}</span> ·
            ${seconds(run.latency_ms)} · <span class="mono">${run.run_id}</span></div>
        </div>
        <div class="item-actions">
          <span class="badge ${scoreTone(run.ats_score)}">ATS ${run.ats_score}</span>
          <a class="btn sm" href="#/run/${encodeURIComponent(run.run_id)}">Open</a>
          <button type="button" class="btn sm danger" data-action="delete-run" data-id="${run.run_id}">Delete</button>
        </div>
      </li>`,
    )}`,
  );
}

async function deleteRun(id) {
  await guarded(async () => {
    await api(`/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.current?.run_id === id) {
      state.current = null;
      $("#results").replaceChildren();
      $("#run-status").textContent = "";
    }
    toast("Run deleted");
    await Promise.all([loadRuns(), loadApplications()]); // applications keep their data, lose the link
  });
}

function wireHistory() {
  $("#more-runs").addEventListener("click", (event) =>
    withBusy(event.currentTarget, () => loadRuns({ more: true })),
  );
  $("#run-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='delete-run']");
    if (button) confirmClick(button, () => deleteRun(button.dataset.id));
  });
}

/* =====================================================================
 * Tracker
 * ===================================================================== */

function renderTracker() {
  const apps = state.applications;
  setCount("tracker", apps.length);
  const count = (status) => apps.filter((app) => app.status === status).length;
  $("#tracker-summary").textContent = apps.length
    ? `${apps.length} tracked · ${count("applied")} applied · ${count("interviewing")} interviewing · ${plural(count("offer"), "offer")}`
    : "Follow each job from saved to offer.";

  if (!apps.length) {
    setHtml(
      $("#board"),
      html`<div class="card empty"><strong>No applications yet</strong>Use “Save to tracker” on a tailoring
        result, or add one manually.</div>`,
    );
    return;
  }
  setHtml(
    $("#board"),
    html`${STATUSES.map(([key, label]) => {
      const jobs = apps.filter((app) => app.status === key);
      return html`<section class="column" aria-label="${label}">
        <h3><span>${label}</span><span>${jobs.length}</span></h3>
        <div class="cards">${jobs.length ? jobs.map(jobCard) : html`<p class="col-empty">Nothing here</p>`}</div>
      </section>`;
    })}`,
  );
}

function jobCard(app) {
  const url = safeUrl(app.url);
  return html`<article class="job" data-id="${app.id}">
    <div class="job-top">
      <h4>${app.job_title}</h4>
      ${app.ats_score !== null ? html`<span class="badge ${scoreTone(app.ats_score)}" title="ATS score when tailored">${app.ats_score}</span>` : ""}
    </div>
    ${app.company ? html`<p class="small muted">${app.company}</p>` : ""}
    <p class="meta">
      ${app.applied_at ? html`Applied ${timeAgo(app.applied_at)}` : html`Added ${timeAgo(app.created_at)}`}
      ${url ? html`· <a href="${url}" target="_blank" rel="noopener noreferrer">Posting ↗</a>` : ""}
      ${app.run_id ? html`· <a href="#/run/${encodeURIComponent(app.run_id)}">Tailored result</a>` : ""}
    </p>
    ${app.notes ? html`<p class="notes">${app.notes}</p>` : ""}
    <div class="job-actions">
      <label class="sr-only" for="status-${app.id}">Status for ${app.job_title}</label>
      <select id="status-${app.id}" data-action="move" data-id="${app.id}">
        ${STATUSES.map(([key, label]) => html`<option value="${key}" ${key === app.status ? raw("selected") : ""}>${label}</option>`)}
      </select>
      <button type="button" class="btn sm" data-action="edit-app" data-id="${app.id}">Edit</button>
    </div>
  </article>`;
}

function replaceApplication(updated) {
  const index = state.applications.findIndex((app) => app.id === updated.id);
  if (index >= 0) state.applications[index] = updated;
  else state.applications.unshift(updated);
  state.applications.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

let editingId = null;

function showAppError(message) {
  const box = $("#app-error");
  box.textContent = message;
  box.hidden = !message;
}

function openAppDialog(application) {
  editingId = application?.id ?? null;
  $("#app-dialog-title").textContent = application ? "Edit application" : "Add application";
  $("#app-title").value = application?.job_title ?? "";
  $("#app-company").value = application?.company ?? "";
  $("#app-url").value = application?.url ?? "";
  $("#app-status").value = application?.status ?? "saved";
  $("#app-notes").value = application?.notes ?? "";
  $("#app-delete").hidden = !application;
  showAppError("");
  $("#app-dialog").showModal();
}

function wireTracker() {
  setHtml($("#app-status"), html`${STATUSES.map(([key, label]) => html`<option value="${key}">${label}</option>`)}`);

  $("#add-application").addEventListener("click", () => openAppDialog(null));

  $("#board").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action='edit-app']");
    if (!button) return;
    const application = state.applications.find((app) => app.id === button.dataset.id);
    if (application) openAppDialog(application);
  });

  $("#board").addEventListener("change", async (event) => {
    const select = event.target.closest("select[data-action='move']");
    if (!select) return;
    const label = STATUSES.find(([key]) => key === select.value)?.[1];
    await withBusy(select, async () => {
      replaceApplication(
        await api(`/applications/${encodeURIComponent(select.dataset.id)}`, {
          method: "PATCH",
          json: { status: select.value },
        }),
      );
      toast(`Moved to ${label}`);
    });
    renderTracker(); // also resets the select if the update failed
  });

  $("#app-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = $("#app-title").value.trim();
    const url = $("#app-url").value.trim();
    if (!title) return showAppError("Job title is required.");
    if (url && !/^https?:\/\//i.test(url)) return showAppError("The URL must start with http:// or https://");
    showAppError("");

    const payload = {
      job_title: title,
      company: $("#app-company").value.trim(),
      url,
      status: $("#app-status").value,
      notes: $("#app-notes").value,
    };
    await withBusy(
      $("#app-save"),
      async () => {
        replaceApplication(
          editingId
            ? await api(`/applications/${encodeURIComponent(editingId)}`, { method: "PATCH", json: payload })
            : await api("/applications", { method: "POST", json: payload }),
        );
        renderTracker();
        refreshTrackButton();
        $("#app-dialog").close();
        toast("Application saved");
      },
      (error) => showAppError(error.message), // toasts sit behind a modal dialog
    );
  });

  $("#app-delete").addEventListener("click", (event) =>
    confirmClick(event.currentTarget, () =>
      withBusy(
        event.currentTarget,
        async () => {
          await api(`/applications/${encodeURIComponent(editingId)}`, { method: "DELETE" });
          state.applications = state.applications.filter((app) => app.id !== editingId);
          renderTracker();
          refreshTrackButton();
          $("#app-dialog").close();
          toast("Application deleted");
        },
        (error) => showAppError(error.message),
      ),
    ),
  );
}

/* =====================================================================
 * Settings (API key)
 * ===================================================================== */

function openSettings(message = "") {
  const dialog = $("#settings-dialog");
  const box = $("#settings-message");
  box.textContent = message;
  box.hidden = !message;
  $("#api-key").value = store.get(API_KEY_STORE) ?? "";
  if (!dialog.open) dialog.showModal();
}

function wireSettings() {
  $("#open-settings").addEventListener("click", () => openSettings());
  $("#cancel-settings").addEventListener("click", () => $("#settings-dialog").close());

  $("#clear-key").addEventListener("click", () => {
    store.remove(API_KEY_STORE);
    $("#api-key").value = "";
    toast("API key cleared");
  });

  $("#settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const key = $("#api-key").value.trim();
    if (key) store.set(API_KEY_STORE, key);
    else store.remove(API_KEY_STORE);
    $("#settings-dialog").close();
    reloadAll();
  });

  // Any 401 anywhere lands here, so a missing/rejected key is always recoverable in place.
  document.addEventListener("auth-required", () =>
    openSettings(
      store.get(API_KEY_STORE)
        ? "The server rejected the saved API key."
        : "This server requires an API key.",
    ),
  );
}

/* =====================================================================
 * Routing + boot
 * ===================================================================== */

const VIEWS = { tailor: "Tailor", corpus: "Corpus", history: "History", tracker: "Tracker" };
let firstRoute = true;

function route() {
  const [name, argument] = location.hash.replace(/^#\/?/, "").split("/");
  const view = name === "run" || !(name in VIEWS) ? "tailor" : name;

  $$("[data-view]").forEach((section) => {
    section.hidden = section.dataset.view !== view;
  });
  $$("[data-nav]").forEach((link) => {
    if (link.dataset.nav === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = `${VIEWS[view]} · AI Job-Hunt Copilot`;

  if (!firstRoute) {
    // Move focus to the new view's heading so keyboard and screen-reader users land in context.
    const heading = $(`[data-view="${view}"] h1`);
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  firstRoute = false;

  if (name === "run" && argument) openRun(decodeURIComponent(argument));
}

function wireDialogs() {
  document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-close]");
    if (closer) closer.closest("dialog").close();
  });
}

function boot() {
  wireDialogs();
  wireSettings();
  wireCorpus();
  wireTailor();
  wireHistory();
  wireTracker();
  window.addEventListener("hashchange", route);
  route();
  updateJdState();
  loadHealth();
  reloadAll();
}

boot();
