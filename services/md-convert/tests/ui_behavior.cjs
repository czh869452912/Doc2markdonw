// Run with: node --test services/md-convert/tests/ui_behavior.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

async function page(storage, fetchSession = async () => ({ session_id: "session-a" })) {
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, {
        disabled: true, checked: true, hidden: false, innerHTML: "", listeners: {},
        addEventListener(event, callback) { this.listeners[event] = callback; },
      });
    }
    return elements.get(selector);
  };
  const context = vm.createContext({
    document: { querySelector: element }, localStorage: storage,
    fetch: async (url, options) => {
      assert.equal(url, "api/session");
      assert.equal(options.cache, "no-store");
      return { ok: true, json: fetchSession };
    },
    setInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/static/app.js"), "utf8"), context);
  await new Promise(setImmediate);
  return { context, element };
}

for (const stored of ["{broken", "{}", "null", '[null,{},42]']) {
  test(`invalid history ${stored} does not disable submission`, async () => {
    const { element } = await page({ getItem: () => stored });
    assert.equal(element("#submit-button").disabled, false);
    assert.match(element("#jobs").innerHTML, /暂无任务/);
  });
}

test("blocked storage keeps submission and in-memory history working", async () => {
  const { context, element } = await page({ getItem() { throw Error("denied"); }, setItem() { throw Error("denied"); } });
  assert.equal(element("#submit-button").disabled, false);
  context.upsertJob({ job_id: "job-a", status: "queued" });
  context.upsertJob({ job_id: "job-b", status: "queued" });
  assert.deepEqual(Array.from(context.loadJobs(), job => job.job_id), ["job-b", "job-a"]);
});

test("quota exhaustion does not replace new history with stale storage", async () => {
  const { context } = await page({ getItem: () => "[]", setItem() { throw Error("quota"); } });
  context.upsertJob({ job_id: "job-a", status: "queued" });
  assert.equal(context.loadJobs()[0].job_id, "job-a");
});

test("session failure offers a working retry", async () => {
  let attempts = 0;
  const { element } = await page({ getItem: () => "[]" }, async () => {
    if (++attempts === 1) throw Error("network unavailable");
    return { session_id: "session-a" };
  });
  assert.equal(element("#submit-button").disabled, true);
  assert.equal(element("#retry-session").hidden, false);
  await element("#retry-session").listeners.click();
  assert.equal(element("#submit-button").disabled, false);
  assert.equal(element("#retry-session").hidden, true);
});
