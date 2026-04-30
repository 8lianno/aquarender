# Security Policy

## Supported versions

AquaRender is pre-1.0 — only `main` is supported. There are no LTS branches.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems. Email
[ali.naaserifar@gmail.com](mailto:ali.naaserifar@gmail.com) with:

- A description of the issue and its impact.
- Steps to reproduce, or a minimal proof-of-concept.
- Affected version / commit SHA.

You should get an acknowledgement within **3 business days**. Coordinated
disclosure is appreciated; we'll work with you on a fix and credit you in the
release notes if you'd like.

If you believe an issue affects an upstream dependency (ComfyUI, SDXL, a
LoRA, Cloudflare Tunnel), please report it to that project as well.

## Threat model in scope

The local AquaRender app is a thin Streamlit UI plus an SQLite database. It
accepts user-supplied images and proxies generation to a remote ComfyUI
engine. We care about:

- **Path traversal / zip-slip** on user-supplied paths or zip uploads.
- **Decompression bombs** — `PIL.MAX_IMAGE_PIXELS` and zip caps (1 GB
  uncompressed, 1000 files) are enforced in `aquarender/core/preprocessor.py`.
- **Pydantic validation** at every input boundary (presets, sidecar JSON,
  ComfyUI responses).
- **No `eval` / `exec` / `pickle.loads`** on user data — please flag any
  regression here.
- **Secrets** are read from environment variables only; nothing is checked
  into the repo.

## Out of scope

- The remote ComfyUI engine is the user's own Kaggle/Colab/HF/local session.
  AquaRender does not, and will not, filter prompts or output images.
  Misuse of the user's own GPU on their own account is between them and the
  platform they're running on.
- The default Cloudflare Tunnel URL (`*.trycloudflare.com`) is **public** for
  the duration of the session. Users who paste the URL into a public channel
  are sharing their free GPU; this is documented in the README and in
  `docs/ARCHITECTURE.md` § "Security Considerations". An optional
  shared-secret header (`X-AquaRender-Auth`) is available; non-default in v1.
- ComfyUI itself is not maintained by AquaRender. CVEs in ComfyUI should be
  reported upstream.

## What we will not do

- We will **not** ship telemetry, analytics, or phone-home features.
- We will **not** add server-side prompt or output filtering. AquaRender is a
  transport, not a moderator.
