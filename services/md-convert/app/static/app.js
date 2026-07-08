const form = document.querySelector("#convert-form");
const button = document.querySelector("#submit-button");
const jobsEl = document.querySelector("#jobs");
const storageKey = "md-convert-jobs";

function loadJobs() {
  try {
    return JSON.parse(localStorage.getItem(storageKey) || "[]");
  } catch {
    return [];
  }
}

function saveJobs(jobs) {
  localStorage.setItem(storageKey, JSON.stringify(jobs.slice(0, 20)));
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
    button.disabled = false;
    button.textContent = "提交转换任务";
  }
});

renderJobs();
setInterval(() => {
  loadJobs().forEach((job) => {
    pollJob(job).catch(() => {});
  });
}, 2500);
