REPO: diagridio/python-ai
TITLE: LangGraph node names do not appear in workflow run history (all nodes land as execute_node_activity)

## What happens

Every node in a graph run by `DaprWorkflowGraphRunner` is executed by the same
activity, `execute_node_activity`. In the run history each node therefore
appears as:

```
eventType: TaskScheduled
  metadata:
    name: execute_node_activity
```

The node's own name survives only inside that activity's input/output payload,
as `node_name`. Payloads are withheld at the default `metadata` data-sharing
level, so at that level the history shows N indistinguishable
`execute_node_activity` steps and no way to tell which node is which.

## Reproduction

A three-node graph (`quick` -> `slow` -> `finish`) produced, in history:

```
   6     name: execute_node_activity
   3   eventType: TaskScheduled
   3   eventType: TaskCompleted
   2     name: dapr.langgraph.<Agent>.workflow
```

and the node names only here:

```
node_name\": \"finish\"
node_name\": \"quick\"
node_name\": \"slow\"
```

## Why it matters

Two things become hard:

1. **Auditing a named step.** We needed a step named `secret_vault_found` to be
   visible in the run history as proof that a particular thing happened. A node
   of that name does not achieve it. The workaround is to give the moment its
   own one-step child workflow, which does appear under its own function name —
   but that is a whole extra workflow per auditable step.
2. **Reading a run at all.** At the default data-sharing level, a failed run
   shows which *step number* failed but not which node, so the console view of
   a multi-node agent is not diagnostic without raising the org's data-sharing
   level, which only an administrator can do.

## Possible fixes

- Schedule each node under an activity name derived from the node, e.g.
  `execute_node_activity.<node_name>` or register a thin per-node activity.
- Or promote `node_name` into the event metadata, which is not withheld,
  rather than leaving it in the payload.

Either would make a graph run readable at the default data-sharing level.

## Environment

`diagrid` 0.5.3 (`diagrid[langgraph]`), `langgraph` 1.2.14, `dapr` 1.18.3,
Python 3.12.12, Diagrid Catalyst managed workflow store.
