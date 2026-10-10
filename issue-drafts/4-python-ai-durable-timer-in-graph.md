REPO: diagridio/python-ai
TITLE: No way for a graph node to await a durable timer

## What

A LangGraph node runs inside a Dapr workflow *activity*
(`execute_node_activity`), and an activity cannot call
`ctx.create_timer`. So a graph has no way to express "wait two minutes,
durably, then continue" — which is one of the main reasons to put an agent on
durable workflows in the first place.

Sleeping in the node blocks an activity for the duration and is not durable:
the wait restarts if the activity is retried, and it holds a worker slot.

## Workaround we used

Define the wait as its own workflow, register it on the runner's
`_workflow_runtime`, have the node start it with `DaprWorkflowClient` and
return immediately, then let the client poll that run. It works and the timer
is genuinely durable — we killed every process for the whole wait and it still
fired on schedule — but it needs the private `_workflow_runtime` attribute and
puts the waiting logic outside the graph.

## What would help

Any of:

- a supported way to register extra workflows/activities on the runner
  (a public accessor for the runtime, or a `workflows=`/`activities=` argument),
  so the workaround does not reach into a private attribute;
- a built-in durable-timer node or helper, e.g. a node that returns a
  "sleep until T" directive the orchestrator honours with `create_timer`;
- documentation of the recommended pattern, if one already exists.

The first is a one-line change and would be enough.

## Environment

`diagrid` 0.5.3 (`diagrid[langgraph]`), `langgraph` 1.2.14, `dapr` 1.18.3,
`dapr-ext-workflow` 1.18.3, Python 3.12.12.
