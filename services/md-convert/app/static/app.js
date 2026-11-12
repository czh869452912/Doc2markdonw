const form = document.querySelector("#convert-form");
const button = document.querySelector("#submit-button");
const jobsEl = document.querySelector("#jobs");
const retrySession = document.querySelector("#retry-session");
const renderMermaid = document.querySelector("#render_mermaid");
const mermaidControls = [
  "#mermaid_format",
  "#mermaid_layout",
  "#mermaid_direction",
  "#mermaid_density",
].map((selector) => document.querySelector(selector));
let storageKey = null;
let memoryJobs = [];
let storageUnavailable = false;

function syncMermaidControls() {
  mermaidControls.forEach((control) => {
    control.disabled = !renderMermaid.checked;
  });
}

function loadJobs() {
  if (!storageKey || storageUnavailable) {
    return memoryJobs;
  }
  try {
    const jobs = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return Array.isArray(jobs) ? jobs.filter((job) => job && typeof job.job_id === "string") : [];
  } catch {
    storageUnavailable = true;
    return memoryJobs;
  }
}

function saveJobs(jobs) {
  if (!storageKey) {
    return;
  }
  memoryJobs = jobs.slice(0, 20);
  try {
    localStorage.setItem(storageKey, JSON.stringify(memoryJobs));
  } catch {
    storageUnavailable = true;
    // Conversion remains available when browser storage is disabled or full.
  }
}

function removeJob(jobId) {
  const jobs = loadJobs().filter((item) => item.job_id !== jobId);
  saveJobs(jobs);
  renderJobs(jobs);
}

function upsertJob(job) {
  const jobs = loadJobs().filter((item) => item.job_id !== job.job_id);
  jobs.unshift(job);
  saveJobs(jobs);
  renderJobs(jobs);
}

function renderJobs(jobs = loadJobs()) {
  if (!jobs.length) {
    jobsEl.innerHTML = "<p>暂无任务。</p>";
    return;
  }
  jobsEl.innerHTML = jobs
    .map((job) => {
      const download = job.download_url
        ? `<a class="download" href="${job.download_url}">下载结果</a>`
        : "";
      const error = job.error ? `<pre class="error">${escapeHtml(job.error)}</pre>` : "";
      return `<article class="job" data-job-id="${job.job_id}">
        <code>${job.job_id}</code>
        <div class="status">状态：${job.status}</div>
        ${download}
        ${error}
      </article>`;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function pollJob(job) {
  if (job.status === "finished" || job.status === "failed") {
    return;
  }
  const response = await fetch(job.status_url || `api/jobs/${job.job_id}`);
  if (response.status === 404) {
    removeJob(job.job_id);
    return;
  }
  if (!response.ok) {
    return;
  }
  upsertJob(await response.json());
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.textContent = "提交中...";

  try {
    const data = new FormData(form);
    if (!document.querySelector("#render_mermaid").checked) {
      data.set("render_mermaid", "false");
    }
    const response = await fetch("api/jobs", {
      method: "POST",
      body: data,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "提交失败");
    }
    upsertJob(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = !storageKey;
    button.textContent = "提交转换任务";
  }
});

renderMermaid.addEventListener("change", syncMermaidControls);

async function initializeSession() {
  button.disabled = true;
  retrySession.hidden = true;
  try {
    const response = await fetch("api/session", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("会话初始化失败");
    }
    const session = await response.json();
    if (typeof session.session_id !== "string" || !session.session_id) {
      throw new Error("会话响应无效，请重新连接。");
    }
    if (storageKey !== `md-convert-jobs:${session.session_id}`) {
      memoryJobs = [];
    }
    storageKey = `md-convert-jobs:${session.session_id}`;
    renderJobs();
    button.disabled = false;
  } catch (error) {
    jobsEl.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
    retrySession.hidden = false;
  }
}

retrySession.addEventListener("click", initializeSession);

setInterval(() => {
  if (!storageKey) {
    return;
  }
  loadJobs().forEach((job) => {
    pollJob(job).catch(() => {});
  });
}, 2500);

initializeSession();
syncMermaidControls();
