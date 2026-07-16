# Anonymous Job Session Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every conversion job to an anonymous browser-session cookie and isolate frontend history by that session.

**Architecture:** A focused `sessions.py` module owns token generation, validation, hashing, cookie creation, and public fingerprints. FastAPI stores the owner hash in RQ metadata and enforces it for status and download endpoints; the frontend initializes a session before using a namespaced localStorage key.

**Tech Stack:** Python 3.12, FastAPI/Starlette, Redis RQ, vanilla JavaScript, `unittest`

---

### Task 1: Add session identity primitives

**Files:**
- Create: `services/md-convert/app/sessions.py`
- Create: `services/md-convert/tests/test_sessions.py`
- Modify: `services/md-convert/app/settings.py`

- [ ] **Step 1: Write failing tests for token creation, reuse, and cookie flags**

Create tests that call a wished-for `resolve_session(token)` function and assert
that a new token has 32 decoded bytes, valid tokens are reused, malformed tokens
are replaced, hashes are stable, and `set_session_cookie(response, identity,
secure=True)` produces `HttpOnly`, `SameSite=lax`, `Path=/`, and `Secure`
without `Max-Age` or `Expires`.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_sessions.py -v
```

Expected: import failure because `app.sessions` does not exist.

- [ ] **Step 3: Implement the session module and setting**

Implement these public units:

```python
@dataclass(frozen=True)
class SessionIdentity:
    token: str
    owner_hash: str
    fingerprint: str
    is_new: bool

def resolve_session(token: str | None) -> SessionIdentity: ...
def set_session_cookie(response: Response, identity: SessionIdentity, secure: bool) -> None: ...
```

Use `secrets.token_urlsafe(32)`, strict URL-safe base64 validation, SHA-256 for
`owner_hash`, the first 16 hash characters for `fingerprint`, and cookie name
`md_convert_session`. Add `cookie_secure: bool` to `Settings`, parsed from
`MD_CONVERT_COOKIE_SECURE` values `1`, `true`, `yes`, or `on`.

- [ ] **Step 4: Run session tests and the existing suite**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_sessions.py -v
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all tests pass.

### Task 2: Enforce ownership at the API boundary

**Files:**
- Create: `services/md-convert/tests/test_job_ownership.py`
- Modify: `services/md-convert/app/main.py`

- [ ] **Step 1: Write failing ownership tests**

Use fake queue/job objects and direct helper calls to assert:

```python
job = enqueue_owned_job(fake_queue, owner_hash="owner-a", ...)
self.assertEqual(job.meta["owner_session_hash"], "owner-a")
self.assertIs(fetch_owned_job("id", "owner-a", connection), job)
with self.assertRaises(HTTPException) as error:
    fetch_owned_job("id", "owner-b", connection)
self.assertEqual(error.exception.status_code, 404)
```

Also cover missing metadata and ensure the comparison uses `hmac.compare_digest`.

- [ ] **Step 2: Run ownership tests and verify RED**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_job_ownership.py -v
```

Expected: import failure for the new ownership helpers.

- [ ] **Step 3: Add `/api/session`, owned enqueueing, and owned fetches**

Add request/response session resolution to create, status, and download routes.
Pass owner metadata atomically through `queue.enqueue(..., meta={
"owner_session_hash": identity.owner_hash})`. Replace `_fetch_job_or_404` with
an owned helper that returns 404 for missing, mismatched, or unowned jobs. The
session endpoint returns:

```python
{"session_id": identity.fingerprint}
```

Attach a cookie only when `identity.is_new` is true.

- [ ] **Step 4: Run API ownership tests and the full Python suite**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest services/md-convert/tests/test_job_ownership.py -v
python -m unittest discover -s services/md-convert/tests -v
```

Expected: all tests pass.

### Task 3: Namespace frontend job history

**Files:**
- Modify: `services/md-convert/app/static/app.js`
- Modify: `services/md-convert/app/static/index.html`

- [ ] **Step 1: Make startup session-aware**

Replace the fixed storage key with a key assigned after:

```javascript
const response = await fetch("api/session");
const session = await response.json();
storageKey = `md-convert-jobs:${session.session_id}`;
```

Keep submit disabled until initialization finishes. On initialization failure,
render a concise error in the jobs area and keep submission disabled.

- [ ] **Step 2: Remove inaccessible jobs after HTTP 404**

Add `removeJob(jobId)` and call it when polling receives 404. Other transient
HTTP failures leave the local job entry intact.

- [ ] **Step 3: Run static checks and the Python suite**

```powershell
node --check services/md-convert/app/static/app.js
$env:PYTHONPATH = 'services/md-convert'
python -m unittest discover -s services/md-convert/tests -v
```

Expected: JavaScript syntax is valid and all Python tests pass.

### Task 4: Update deployment defaults and verify browser isolation

**Files:**
- Modify: `deploy/ragflow-mineru/docker-compose.md-convert.yml`
- Modify: `deploy/ragflow-mineru/env/airgap.env.example`
- Modify: `deploy/ragflow-mineru/README.md`

- [ ] **Step 1: Document secure-cookie configuration**

Add `MD_CONVERT_COOKIE_SECURE=${MD_CONVERT_COOKIE_SECURE:-false}` to API and
worker environments, add `MD_CONVERT_COOKIE_SECURE=false` to the example env,
and document setting it to `true` only when clients access the gateway through
HTTPS.

- [ ] **Step 2: Run browser tests in two isolated contexts**

Start the service, open two fresh browser contexts, create one job in context A,
and verify context B cannot query or download it and does not display it in
history. Close/reopen context A and verify it receives a different fingerprint.

- [ ] **Step 3: Run final verification**

```powershell
$env:PYTHONPATH = 'services/md-convert'
python -m unittest discover -s services/md-convert/tests -v
node --check services/md-convert/app/static/app.js
git diff --check
```

Expected: all tests and checks pass with no whitespace errors.
