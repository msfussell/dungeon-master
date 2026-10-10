REPO: diagridio/catalyst-ai
TITLE: catalyst_terminate_workflow_run returns HTTP 500 "unexpected end of JSON input" when no worker is connected

## What happens

Calling the MCP tool `catalyst_terminate_workflow_run` for a running workflow
while no workflow worker is connected returns:

```
UPSTREAM_ERROR: Catalyst failed to handle this call. (HTTP 500)
Catalyst said: {"message":"unexpected end of JSON input","code":"500"}
```

The underlying condition is benign and well understood — there is no worker to
deliver the termination to. Two other paths report it correctly:

- `diagrid workflow terminate --instance-id <id> --app-id <a> --project <p>`:
  `Unable to terminate workflow: App ID <a> has no connected workflow worker.
  Start the app and retry.`
- `catalyst_purge_workflow_runs`: HTTP 409 with that same message.

So only the terminate MCP tool surfaces it as a 500 JSON-parse error, which
reads as a platform fault and sends you looking in the wrong place. The tool's
own guidance then says "This is a server-side failure, not a problem with the
arguments. Retry once; if it persists, report it" — so the advice is to retry
something that cannot succeed until an unrelated action is taken.

## Reproduction

1. Start a workflow on Catalyst from a local worker.
2. Stop the worker, so the App ID has no workflow workers connected.
3. Call `catalyst_terminate_workflow_run` with projectId / appId / workflowId
   for the still-running instance.

## Expected

The same 409 and message that `catalyst_purge_workflow_runs` returns, so the
caller knows to start a worker rather than to retry.

## Environment

Observed 2026-10-08 ~22:14 UTC. Catalyst API server 1.164.0, `diagrid` CLI
1.55.0, Dapr 1.19.0-20261005-catalyst.1, region diagrid-aws-eu-west.

(Filing here because this is where the MCP tooling is published; the fix is
presumably server-side. Move it if there is a better home.)
