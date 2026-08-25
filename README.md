# OmniBioAI SDK

> README last reviewed: **2026-08-24**

> **0.2.0: new `omnibioai` package.** This SDK is migrating to a unified,
> ecosystem-wide client under a new import path:
> ```python
> from omnibioai import OmniBioAI
>
> client = OmniBioAI(access_token="jwt-token")
>
> result = client.rag.query("BRCA1 pathway analysis")
> ```
> `OmniBioAI` handles token refresh and error normalization across
> OmniBioAI services. `.rag`, `.models`, `.tes`, and `.workflows` are all
> available now. Note `client.models` is task-scoped
> (`client.models.get(task, ref)`), not a bare-name lookup --
> `omnibioai-model-registry`'s actual API has no cross-task name search,
> so the SDK mirrors its real shape rather than the target example's
> simplified one. `.tes` (low-level tool execution, e.g.
> `client.tes.submit(tool_id, inputs={...})`) and `.workflows` (high-level
> named pipelines, e.g. `client.workflows.run(workflow_name, inputs={})`)
> are deliberately kept as two separate clients -- see each client's own
> module docstring. `.workflows`'s target service
> (`omnibioai-workflow-bundles`) has no confirmed API Gateway route yet;
> pass `workflows_url=` explicitly until it does. **Nothing existing
> breaks**: the object-registry client documented below is unchanged and
> fully supported, importable from
> either `omnibioai_sdk` (as before) or `omnibioai`
> (`from omnibioai import OmniClient`) -- both resolve to the exact same
> class.

**OmniBioAI SDK** is a lightweight Python client for interacting with the
**OmniBioAI platform APIs**. The current client exposes:

* RAG and literature queries (`client.rag`)
* task-scoped model registry access (`client.models`)
* low-level tool execution (`client.tes`)
* named workflow execution (`client.workflows`)

The package also retains the legacy Object Registry client (`OmniClient`) for
backward compatibility. It is documented separately below.

The SDK is intentionally **thin and explicit** — it does not hide API behavior and is designed to evolve alongside the OmniBioAI platform.

---

## Features

* Unified client (`OmniBioAI`) with shared authentication and session state
* Automatic access-token refresh when a refresh token is supplied
* Typed exceptions for authentication, permission, validation, gateway,
  not-found, and service failures
* Fresh `X-Trace-Id` propagation on every service request
* Legacy `OmniClient` compatibility for Object Registry APIs
* Works with local OmniBioAI development servers
* No Docker required
* Designed for notebooks, scripts, pipelines, and service integrations
* Explicit authentication, base URL, auth URL, workflow URL, and timeout control
* Easy to extend with new API endpoints

---

## Installation

```bash
# Canonical installation from GitHub
pip install git+https://github.com/OmniBioAI/omnibioai-sdk.git

# Local development with test and packaging tools
git clone https://github.com/OmniBioAI/omnibioai-sdk.git
cd omnibioai-sdk
pip install -e ".[dev]"
```

> **Note:** `omnibioai-sdk` is not currently published to PyPI.
> GitHub Packages installation is deployment-specific; use the pinned Git
> dependency above unless your organization provides a configured package index.

---

## Quick Start

```python
from omnibioai import OmniBioAI

client = OmniBioAI(
    access_token="your-access-token",
    refresh_token="your-refresh-token",  # optional; enables auto-refresh
    base_url="http://127.0.0.1:8080",    # API Gateway
    auth_url="https://auth.omnibioai.org", # Auth service
)

result = client.rag.query("BRCA1 pathway analysis")
print(result)

model = client.models.get(task="classification", ref="latest")
print(model)

run = client.tes.submit("example-tool", inputs={"query": "BRCA1"})
print(run)
```

> **Note:** All requests go through `api-gateway` (port 8080) which
> enforces JWT authentication and routes to the correct backend service.
> Never point the SDK directly at individual services (auth-service,
> workbench etc.) in production.

### Getting a token

Obtain the access/refresh token pair through the OmniBioAI Auth login or SSO
flow used by your environment. Do not hard-code credentials or commit tokens
to notebooks, scripts, Dockerfiles, or source control. The SDK transports
tokens but does not decode or verify them locally.

For local development, use the Auth service's documented login endpoint and
pass the returned `access_token` and `refresh_token` to `OmniBioAI`. Auth is a
separate service from the API Gateway, so configure `auth_url` independently
when using a local Auth deployment.

### Legacy Object Registry client

Existing callers can continue to use the compatibility client:

```python
from omnibioai_sdk import OmniClient

c = OmniClient(
    base_url="http://127.0.0.1:8080",  # API Gateway
    token="your-jwt-token",
)

objects = c.objects_list()
print(objects["count"])
```

`OmniClient` wraps the legacy Object Registry endpoints and does not share the
new client's automatic refresh, trace propagation, or typed error handling.

Its historical default base URL is `http://127.0.0.1:8001`; set `base_url`
explicitly for the API Gateway or deployment-specific route.

Legacy environment variables:

```bash
export OMNIBIOAI_BASE_URL=http://127.0.0.1:8080
export OMNIBIOAI_TOKEN=your-jwt-token
```

Then simply:

```python
from omnibioai_sdk import OmniClient
c = OmniClient()
```

---

## Authentication

### `OmniBioAI` authentication model

`OmniBioAI` (`.rag`/`.models`/`.tes`/`.workflows`) takes an explicit
access/refresh token pair and manages them automatically:

```python
from omnibioai import OmniBioAI

client = OmniBioAI(
    access_token="jwt-token",
    refresh_token="refresh-token",   # optional but required for auto-refresh
)
```

- **One shared session, one token pair.** All four sub-clients are
  constructed against the same `AuthenticatedSession`/`TokenPair`.
- **Refresh-on-401, once.** A `401` triggers exactly one refresh call against
  `auth_url + /auth/refresh`; a second `401` or failed refresh raises
  `AuthenticationError`.
- **Rotated tokens are exposed.** `client.access_token` and
  `client.refresh_token` reflect the current values after refresh. Auth refresh
  tokens are single-use and rotate on every successful refresh.
- **Trace propagation.** `X-Trace-Id` is generated fresh per call and recorded
  on `client.session.last_trace_id`.
- **No local JWT verification.** The SDK transports tokens but leaves token
  verification to the API Gateway and target services.

### Legacy `OmniClient` authentication

The legacy `OmniClient` (Object Registry API, below) uses simple
**header-based authentication** — a single static token, no refresh:

```text
Authorization: Bearer dev
```

You can pass credentials explicitly or via environment variables.

#### Legacy environment variables

```bash
export OMNIBIOAI_BASE_URL=http://127.0.0.1:8080   # api-gateway
export OMNIBIOAI_TOKEN=dev
```

Then simply:

```python
c = OmniClient()
```

### Handling SDK errors

```python
from omnibioai.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    ServiceUnavailableError,
)

try:
    result = client.rag.query("BRCA1 pathway analysis")
except AuthenticationError:
    raise  # access or refresh token is invalid, expired, or revoked
except PermissionDeniedError:
    raise  # valid token, missing service permission
except ServiceUnavailableError as exc:
    print(f"service unavailable; trace={exc.trace_id}")
    raise

---

## URLs by environment

| Environment | Base URL | Notes |
|-------------|----------|-------|
| Local development (`OmniBioAI`) | `http://127.0.0.1:8080` | API Gateway direct |
| Via nginx (Studio) | `http://localhost/_svc/gateway` | JWT required |
| Production | `https://api.omnibioai.org` | TLS + JWT required |

Always use the api-gateway URL for `base_url` — never point directly at
individual services (workbench :8000, etc.).

**Two deliberate exceptions for the new `OmniBioAI` client:**

- `OmniBioAI`'s login/refresh/logout calls go to a *separate* `auth_url`
  (default `https://auth.omnibioai.org`), not `base_url` — the API
  Gateway's `SERVICE_MAP` has no `auth` entry, so those routes aren't
  reachable through it today. Override with `OmniBioAI(..., auth_url=...)`
  for non-default deployments.
- `.workflows` defaults to `{base_url}/workflow-bundles`, but
  `omnibioai-workflow-bundles` has no *confirmed* route in the Gateway's
  `SERVICE_MAP` yet — pass `OmniBioAI(..., workflows_url=...)` explicitly
  until it does.

---

## Object Registry API

### List objects

```python
lst = c.objects_list()
lst["count"]
lst["items"][0]
```

### Get a single object

```python
obj = c.object_get("56d3fc3a-709b-4ed0-bf17-8cb73c6746b0")
print(obj["object_type"])
print(obj["metadata"])
```

---

## Notebook-Based Analysis

OmniBioAI supports launching **object-aware Jupyter notebooks**.

Typical flow:

1. User clicks **“Analyze in Notebook”** in the OmniBioAI UI
2. Django endpoint generates a notebook
3. JupyterLab opens with the object context preloaded

Inside the notebook:

```python
import os
from omnibioai_sdk import OmniClient

OBJECT_ID = os.environ["OMNIBIOAI_OBJECT_ID"]

c = OmniClient()
obj = c.object_get(OBJECT_ID)

obj["object_type"], obj["metadata"]
```

---

## Running Jupyter for OmniBioAI

Recommended dev command:

```bash
jupyter lab \
  --port 8890 \
  --port-retries=0 \
  --no-browser \
  --notebook-dir . \
  --IdentityProvider.token=devtoken
```

And set:

```bash
export OMNIBIOAI_JUPYTER_BASE=http://127.0.0.1:8890
export OMNIBIOAI_JUPYTER_TOKEN=devtoken
```

---

## Testing

Install the development extras and run the complete suite:

```bash
python -m pip install -e ".[dev]"
pytest
```

The test configuration enforces at least 95% coverage across both the new
`omnibioai` package and the legacy `omnibioai_sdk` compatibility package.
The suite mocks HTTP responses; it does not require a live API Gateway or
service deployment.

## Project Structure

```text
omnibioai-sdk/
├── omnibioai/                  # new, ecosystem-wide package (0.2.0)
│   ├── __init__.py             # exports OmniBioAI, OmniClient, RAGClient,
│   │                            # ModelsClient, TESClient, WorkflowsClient
│   ├── client.py                # OmniBioAI — top-level client, owns one
│   │                            # shared AuthenticatedSession
│   ├── legacy.py                # OmniClient, relocated unchanged from
│   │                            # omnibioai_sdk/client.py — see below
│   ├── exceptions.py
│   ├── _base.py
│   ├── auth/
│   │   ├── session.py           # AuthenticatedSession — auth header
│   │   │                        # injection, refresh-on-401, X-Trace-Id
│   │   └── tokens.py            # TokenPair — mutated in place on refresh
│   ├── rag/client.py            # RAGClient — .query(...)
│   ├── models/client.py         # ModelsClient — .get(task, ref), task-scoped
│   ├── tes/client.py            # TESClient — .submit(tool_id, inputs=...)
│   └── workflows/client.py      # WorkflowsClient — .run(workflow_name, inputs=...)
├── omnibioai_sdk/                # pre-existing package, kept for compatibility
│   ├── __init__.py               # re-exports OmniClient from omnibioai/legacy.py
│   └── client.py                 # re-exports OmniClient from omnibioai/legacy.py
├── tests/
├── pyproject.toml
└── README.md
```

`omnibioai_sdk/` is not a separate, unmaintained package — both of its
modules now just re-export `OmniClient` from `omnibioai/legacy.py`, so
`from omnibioai_sdk import OmniClient` (every existing caller's import)
keeps working unchanged and indefinitely, alongside the new
`from omnibioai import OmniClient` path.

---

## Design Philosophy

* **No magic**: SDK mirrors REST APIs closely
* **Dev-first**: optimized for local servers and notebooks
* **Composable**: meant to be imported into pipelines, workflows, and notebooks
* **Extensible**: new APIs = new methods, not rewrites

---

## Extending the SDK

Add a new service surface by following the existing `BaseServiceClient`
pattern, then expose it from `OmniBioAI` and add focused tests. For a legacy
Object Registry endpoint, extend `OmniClient`:

```python
def workflow_list(self):
    r = requests.get(
        f"{self.base_url}/api/dev/workflows/",
        headers=self.headers,
        timeout=self.timeout
    )
    r.raise_for_status()
    return r.json()
```

No regeneration or codegen required.

---

## Versioning

The SDK follows **semantic versioning**:

* `0.x` → fast iteration
* `1.0+` → stable API surface

---

## Related packages

| Package | Purpose |
|---------|---------|
| `omnibioai-launcher` | Browser UI — alternative to SDK for interactive use |
| `omnibioai-model-registry` | Backs `.models` — ML model versioning (`omr` CLI + its own Python client) |
| `omnibioai-rag` | Backs `.rag` — PubMed/literature query API |
| `omnibioai-tes` | Backs `.tes` — low-level, tool_id-addressed execution |
| `omnibioai-workflow-bundles` | Backs `.workflows` — named/versioned pipeline execution; no confirmed API Gateway route yet, see [URLs by environment](#urls-by-environment) |
| `omnibioai-studio` | Desktop app — manages the full stack the SDK connects to |
| `omnibioai-iam-client` | Internal service auth SDK (for service-to-service calls) — not used by this SDK itself; see [Authentication](#authentication) |

---

## License

Apache License 2.0

---

## Status

**Active development**
Used internally by the OmniBioAI workbench and services.

---

## Opening objects in analysis environments

For opening objects in JupyterLab, VS Code, or RStudio, see the
[omnibioai-launcher](https://github.com/OmniBioAI/omnibioai-launcher)
repository. The launcher is a standalone React UI that accepts an
`object_id` via URL parameter and handles environment dispatch.
