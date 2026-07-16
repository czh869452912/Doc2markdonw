# Anonymous Job Session Isolation Design

## Goal

Prevent anonymous users from viewing or downloading another browser session's
conversion jobs while preserving the service's simple, account-free workflow.

## Scope

This design adds browser-session ownership to job creation, status, and
downloads, and namespaces the frontend's local job history by session. It does
not add user accounts, login screens, shared job libraries, persistent sessions,
or administrative access to users' jobs.

## Session Lifecycle

The API issues a cryptographically random bearer token with at least 256 bits
of entropy. It is stored in a cookie with these properties:

- `HttpOnly`
- `SameSite=Lax`
- `Path=/`
- No `Max-Age` or `Expires`, making it a browser-session cookie
- `Secure` when `MD_CONVERT_COOKIE_SECURE=true`

Only a SHA-256 hash of the token is stored in RQ job metadata. The raw token is
never placed in job arguments, results, logs, or browser storage.

`GET /api/session` creates the cookie when needed and returns a non-sensitive
session fingerprint derived from the hash. The frontend uses that fingerprint
only to namespace local history:

```text
md-convert-jobs:<session-fingerprint>
```

Multiple tabs in the same browser session share the cookie and history. After
the browser session ends, a new token and fingerprint are generated. Old
localStorage entries remain inert and are not displayed or deleted.

## Ownership Enforcement

Job creation stores the current session hash in job metadata. Status and
download endpoints compare the current session hash with the job owner before
returning any job information. A missing job, an owner mismatch, and a legacy
job without ownership metadata all return HTTP 404 so the API does not reveal
whether another user's job exists.

The create endpoint also creates a session when called by a client that did not
first call `/api/session`, preserving direct API use. A new session cookie must
be attached to the create response in that case.

## Frontend Behavior

Page initialization calls `/api/session` before reading or rendering the job
list. It then loads only the localStorage key for the returned fingerprint.

Job cards continue to show job ID, status, errors, and download links. They do
not display the raw token or fingerprint. Polling behavior is unchanged except
that an HTTP 404 removes an inaccessible legacy entry from the rendered session
history on the next local update.

The page adds no login UI, user menu, session badge, or explanatory panel.

## API Data Flow

```text
Browser calls GET /api/session
  -> API creates or reuses the anonymous cookie
  -> browser namespaces local history with the public fingerprint
  -> browser submits a conversion job
  -> API stores the session hash in RQ job metadata
  -> status and download endpoints compare owner and current session hashes
```

## Security

The anonymous cookie is a bearer credential. Its high entropy prevents session
guessing, while storing only its hash limits exposure through Redis or RQ job
inspection. `HttpOnly` prevents frontend JavaScript from reading the token and
`SameSite=Lax` limits cross-site requests. Deployments terminating HTTPS should
set `MD_CONVERT_COOKIE_SECURE=true`.

This mechanism isolates anonymous jobs; it does not protect a user whose
browser session or cookie is deliberately shared. It also does not replace
transport security when the service is exposed beyond a trusted network.

## Compatibility And Migration

- Existing API clients can still create jobs without calling `/api/session`.
- Existing jobs without ownership metadata become inaccessible through the
  API after deployment.
- The old unnamespaced `md-convert-jobs` localStorage value is ignored and not
  deleted.
- Redis requires no schema migration because ownership uses RQ job metadata.
- `MD_CONVERT_COOKIE_SECURE` defaults to `false` for the current HTTP intranet
  deployment and is documented for HTTPS deployments.

## Error Handling

- Missing, foreign-owned, and legacy unowned jobs return HTTP 404.
- Invalid or empty cookie tokens are replaced with a new session.
- Session creation failure prevents job creation rather than creating an
  unowned job.
- The raw bearer token is never included in exception text.

## Validation

Automated tests will cover:

1. Session creation, cookie flags, and fingerprint response.
2. Reuse of a valid cookie without rotating the session.
3. Replacement of an invalid or empty cookie.
4. Owner metadata saved during job creation.
5. Same-session job status and download access.
6. Cross-session status and download rejection.
7. Legacy unowned job rejection.
8. Frontend initialization before local job history is rendered.
9. Session-namespaced localStorage behavior across two browser contexts.
10. Existing task polling and download behavior within one session.
