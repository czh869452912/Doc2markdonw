# MinerU Gradio Offline Routing Design

## Goal

Expose the optional MinerU Gradio UI at `/mineru-ui/` through the existing
single public gateway port and make its core UI, PDF preview, upload,
conversion, and download workflows usable without internet access. Keep port
7860 private and do not modify MinerU source code.

## Scope

This design covers the Gradio service, its reverse-proxy contract, offline
runtime settings, third-party browser assets, package contents, and deployment
verification. Office conversion is delegated to the separate MinerU-compatible
Office gateway defined in
`2026-07-16-mineru-office-gateway-design.md`.

The design does not provide an offline replacement for MinerU's Microsoft
Office Online iframe. Office files remain convertible through the Office
gateway, but the unmodified MinerU Gradio upload preview will show its existing
offline notice instead of a rendered Office document. External navigation
links to GitHub, Hugging Face, ModelScope, arXiv, and mineru.net are not expected
to work in an air-gapped browser.

## Current Constraints

- `mineru-gradio` is behind the optional `mineru-ui` Compose profile.
- The runtime Compose rewrite removes all non-gateway host ports.
- Nginx has no route to `mineru-gradio:7860`.
- Gradio 6 supports a proxy subpath through `GRADIO_ROOT_PATH`.
- The installed `gradio-pdf` 0.0.24 bundle loads its worker from jsDelivr and
  CMaps from Hugging Face.
- The generated Gradio page contains optional remote fonts, icons, badges,
  social metadata, and iframe support scripts.
- The MinerU image already contains the parsing models and sets
  `MINERU_MODEL_SOURCE=local`.

## Architecture

The public route is `http://<server>:<PUBLIC_PORT>/mineru-ui/`. Nginx removes
the `/mineru-ui/` prefix when proxying to `mineru-gradio:7860`. Gradio receives
`GRADIO_ROOT_PATH=/mineru-ui`, so generated asset, API, file, and event URLs
retain the public prefix.

The Gradio process does not start its own MinerU API worker. It receives:

```text
--api-url http://mineru-office-gateway:8081
```

This keeps one conversion path for API clients and the UI and avoids loading a
second model stack in the Gradio container.

The service uses a UI-specific image variable, `MINERU_GRADIO_IMAGE`, defaulting
to `mineru-gradio-offline:latest`. That image is a thin derivative of the pinned
MinerU image. It may replace third-party Gradio or `gradio-pdf` package assets,
but it must not patch any file under the `mineru` Python package. The Router
continues to use `MINERU_IMAGE` unchanged.

## Proxy Contract

Nginx adds a redirect from `/mineru-ui` to `/mineru-ui/` and proxies the latter
to `http://mineru-gradio:7860/`. The location must:

- use HTTP/1.1;
- forward `Host`, `X-Forwarded-Host`, `X-Forwarded-Proto`,
  `X-Forwarded-For`, and `X-Forwarded-Prefix`;
- preserve the host port by using `$http_host` for forwarded host values;
- support connection upgrades;
- disable proxy response buffering for Gradio event streams;
- inherit the gateway upload limit and long read/send timeouts.

The route must not expose a second host port. `/mineru/` remains the public
MinerU-compatible API route and points to the Office gateway, not directly to
the Router.

## Offline Runtime Settings

The Gradio service sets the following environment contract:

```text
GRADIO_ROOT_PATH=/mineru-ui
GRADIO_ANALYTICS_ENABLED=False
GRADIO_SHARE=False
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
DO_NOT_TRACK=1
MINERU_MODEL_SOURCE=local
```

The gateway applies a Content Security Policy to the Gradio location that
allows same-origin data, blob, worker, inline style, and Gradio inline script
requirements while blocking automatic cross-origin fetches and frames. The
policy is scoped to `/mineru-ui/` so it does not affect RAGFlow or Markdown
Convert.

Remote-only header links may remain visible, but no core workflow may depend on
them. Automatically loaded remote badges, fonts, icons, iframe helpers, and
social images must either be removed from the derived UI image, replaced with
local assets, or blocked with a tested local fallback. System sans-serif fonts
are an acceptable fallback.

## PDF Preview Assets

The derived UI image pins a PDF.js version compatible with the `gradio-pdf`
frontend bundle and stores the worker, CMaps, and required standard font data
inside the image. The component bundle references same-origin paths beneath
`/mineru-ui/`; it must not reference a branch such as `main` or a remote CDN.

The build records the MinerU, Gradio, `gradio-pdf`, and PDF.js versions in image
labels and the offline package manifest. A build fails if the expected bundle
strings are absent, preventing an upstream package update from silently
leaving the remote URLs unpatched.

## Profiles And Packaging

`mineru-ui` is included in the recommended production `COMPOSE_PROFILES` value
when the Gradio image is packaged. Packaging saves the UI-specific image and
all local PDF assets in the air-gap bundle. Deploying without the `mineru-ui`
profile remains supported for API-only installations.

The Linux deployment summary and README list the endpoint:

```text
http://<server>:<PUBLIC_PORT>/mineru-ui/
```

## Failure Behavior

- If `mineru-gradio` is disabled, `/mineru-ui/` returns a gateway 503 rather
  than falling through to RAGFlow.
- If the Office gateway is unhealthy, the UI still loads but conversion shows
  the upstream failure returned by Gradio.
- If a PDF preview asset is missing, image build or verification fails; this is
  not treated as an optional runtime warning.
- Office Online iframe access is blocked in air-gap mode. Conversion remains
  available, and the current MinerU notice communicates that preview is
  unavailable.

## Verification

Automated static tests assert the Compose profile, private port, environment,
Gradio `--api-url`, Nginx route, proxy headers, package image list, README
endpoint, and verification script checks.

Image tests assert that:

- no `mineru` package source file differs from the pinned base image;
- analytics and sharing are disabled;
- the `gradio-pdf` bundle has no remote worker or CMap URL;
- all required local PDF assets exist and have pinned checksums.

Runtime verification starts the stack on an internal Docker network and checks:

1. `/mineru-ui/` returns HTML through `PUBLIC_PORT`.
2. Gradio JS, CSS, component bundles, worker, CMaps, upload, and event endpoints
   return through the prefixed route.
3. Browser network logs contain no required internet request.
4. A local PDF previews successfully.
5. A PDF conversion and download complete through the Office gateway.
6. An Office upload converts successfully even though its Office Online
   preview is unavailable.

## Risks

The offline asset overlay is coupled to pinned Gradio and `gradio-pdf` versions.
Version pinning, string guards, checksums, and browser tests make this coupling
explicit. Replacing the MinerU Gradio application or implementing an offline
Office editor is outside this design.
