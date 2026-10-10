REPO: dapr/python-sdk
TITLE: DAPR_* environment variables are snapshotted at import time, so loading config after import silently dials localhost

## What happens

`dapr.conf.settings` reads the `DAPR_*` environment variables when the module is
first imported. Setting them afterwards has no effect, and the SDK silently
falls back to `dns:localhost:50001` instead of the configured endpoint. There is
no warning and no error — the first symptom is a connection failure that looks
like a network or platform problem.

This is easy to hit with any of the common config patterns: `python-dotenv` in a
`config.py`, a settings module, a CLI that parses args before wiring the client,
or a framework that imports your package before your `.env` loader runs.

## Reproduction

```python
import os
assert "DAPR_GRPC_ENDPOINT" not in os.environ

import dapr.conf as conf
print(conf.settings.DAPR_GRPC_ENDPOINT)    # None

os.environ["DAPR_GRPC_ENDPOINT"] = "https://grpc-example.example.com:443"
print(os.environ["DAPR_GRPC_ENDPOINT"])    # the value we just set
print(conf.settings.DAPR_GRPC_ENDPOINT)    # None  <-- still

from dapr.conf.helpers import GrpcEndpoint
ep = GrpcEndpoint(conf.settings.DAPR_GRPC_ENDPOINT
                  or f"localhost:{conf.settings.DAPR_GRPC_PORT}")
print(ep.endpoint)                         # dns:localhost:50001
```

Observed output:

```
1. imported dapr.conf with no DAPR_GRPC_ENDPOINT set
   settings.DAPR_GRPC_ENDPOINT = None
   settings.DAPR_GRPC_PORT     = 50001

2. set DAPR_GRPC_ENDPOINT AFTER import
   os.environ value            = https://grpc-example.example.com:443
   settings.DAPR_GRPC_ENDPOINT = None

3. endpoint the SDK would dial: dns:localhost:50001
```

## Expected

Any of the following would have saved the debugging time:

1. Read the setting lazily, at client construction, rather than at import.
2. Keep the import-time read, but re-check `os.environ` when a client is built
   and raise or warn on a mismatch between `os.environ["DAPR_GRPC_ENDPOINT"]`
   and `settings.DAPR_GRPC_ENDPOINT`.
3. Document it prominently in the client docs — "set `DAPR_*` before importing
   `dapr`" — since the current failure mode is silent.

(1) seems best; (2) is the cheapest thing that makes the failure loud.

## Environment

- `dapr` 1.18.3, `dapr-ext-workflow` 1.18.3
- Python 3.12.12, macOS 15 (darwin 24.3.0)
- Talking to a managed Dapr control plane over a remote gRPC endpoint, so the
  localhost fallback can never succeed

## Why it matters

Against a local sidecar the fallback is often correct, which is why this is
rarely noticed. Against any remote or managed endpoint it is always wrong, and
the error surfaces far from its cause — the one I chased presented as "every
connection fails", with correct-looking values in `.env` and in `os.environ`.
