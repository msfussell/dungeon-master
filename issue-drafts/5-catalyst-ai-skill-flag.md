REPO: diagridio/catalyst-ai
TITLE: app-tunnels skill documents `diagrid dev run --id`, but CLI 1.55.0 requires `--app-id`

## What happens

The `catalyst-app-tunnels` skill gives the tunnel command as:

```
diagrid dev run --project <project> --id <app-id> --app-port <port> --yes -- <command>
```

and says "`-a` is the short form of `--id` in `dev run`, `dev stop` and
`listen`". With CLI 1.55.0 that fails:

```
Unknown flag: --id
```

`diagrid dev run --help` lists `-a, --app-id string`. The working form is
`--app-id`. `dev stop` likewise takes `--app-id`.

Following the skill verbatim therefore fails on the first tunnel command, and
the error dumps the whole help text, which buries the one relevant line.

## Suggested fix

Replace `--id` with `--app-id` throughout the skill (and `-a` remains correct),
or note which CLI versions use which spelling.

## Also worth a line in the same skill

Two things the skill is right about but which cost time anyway, and might
deserve stronger wording:

- Restarting `dev run` too soon after a stop fails with `failed to connect
  tunnel after retries: local app connection not found with the given id`. The
  skill mentions waiting for the tunnel to close; in practice this needed
  ~20-30s *and* killing a leftover process holding the app port. A "wait for
  `catalyst_list_app_tunnels` to return empty, then check `lsof -i :<port>`"
  recipe would be more actionable.
- `terminate` and `purge` both need a connected workflow worker. The skill says
  this for tunnels; it is worth repeating wherever cleanup is described, since
  the natural cleanup order (stop the app, then purge its runs) is exactly
  wrong.

## Related

Same theme as #39 (skill content drifting from the thing it documents), but a
different specific defect: that one is about package coordinates, this is a CLI
flag. Worth fixing together if someone is doing a sweep.

## Environment

`diagrid` CLI 1.55.0 (git 4869aa5, 2026-07-15), API server 1.164.0, macOS.
