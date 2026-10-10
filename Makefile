.PHONY: install test leakcheck play-workflow play-agent serve-agent reset

install-workflow: ## environment for the workflow front end
	uv sync --extra workflow

install-agent:    ## environment for the agent front end (conflicts with the above)
	uv sync --extra agent

test:             ## the rules, with no Catalyst and no key. ~1 second.
	uv run python -m tests.test_invariants
	uv run python -m tests.test_rest_refusal

leakcheck:        ## prove nothing readable explains the secret
	uv run python -m dungeon_master.engine.leakcheck

play-workflow:    ## the booth demo: one durable workflow, no tunnel
	uv run dungeon-master-workflow

serve-agent:      ## terminal 1 for the agent front end (opens a tunnel)
	./scripts/serve-agent

play-agent:       ## terminal 2 for the agent front end
	uv run dungeon-master-agent

reset:            ## purge this project's runs (starts a worker first -- purge needs one)
	./scripts/reset
