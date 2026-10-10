REPO: diagridio/python-ai
TITLE: Runner's FastAPI app has no health route, so Catalyst health checks 404 and the first invoke fails

## What happens

`DaprWorkflowGraphRunner.serve()` builds a FastAPI app exposing `/agent/run`
and `/agent/run/{workflow_id}`, and nothing at `/`. Catalyst health-checks an
app through its app tunnel with `GET /`, which therefore 404s:

```
INFO:     10.0.x.x:0 - "GET / HTTP/1.1" 404 Not Found
INFO:     10.0.x.x:0 - "GET /dapr/config HTTP/1.1" 404 Not Found
```

Until the health state settles, every service invocation to the agent fails:

```
{"errorCode":"ERR_DIRECT_INVOKE",
 "message":"failed to invoke, id: <agent>, err: rpc error: code = Internal
 desc = error invoking app channel: rpc error: code = Internal
 desc = app is not in a healthy state"}
```

The agent's own log shows a clean startup — nodes registered, workflow runtime
connected, `Uvicorn running` — so the failure looks like a platform problem
rather than a missing route.

## Reproduction

1. Create a Catalyst `Agent` resource and wait for its App ID to be `ready`.
2. `diagrid dev run --project <p> --app-id <agent> --app-port 5001 --yes -- <runner>`
3. Immediately `POST $DAPR_HTTP_ENDPOINT/v1.0/invoke/<agent>/method/agent/run`.

It fails with the above for roughly a minute, then starts working with no
change on either side.

## Expected

The runner should serve a health route — `GET /` returning 200, and/or
`GET /healthz`, and/or `GET /dapr/config` — so that an agent which has finished
starting is immediately reported healthy.

As a user I cannot add the route myself: the FastAPI app is constructed inside
`serve()` and is not exposed for a caller to attach routes to. A `routes=` or
`app=` parameter on `serve()` would also solve it.

## Environment

`diagrid` 0.5.3, `fastapi` 0.143.0, `diagrid` CLI 1.55.0, Catalyst API server
1.164.0, Python 3.12.12.
