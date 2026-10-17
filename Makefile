.PHONY: install run test evals demo-scope crawl sync typecheck
install:
	pip install -e task1_brain -e task3_scope
	cd task2_inbox && npm install
run:            ## all three services (mock mode if no ANTHROPIC_API_KEY)
	./scripts/run_all.sh
test:
	cd task1_brain && python3 -m unittest discover -s tests
	cd task3_scope && python3 -m unittest discover -s tests
	cd task2_inbox && node --test src/agent.test.ts
typecheck:
	cd task2_inbox && npx tsc --noEmit
evals:          ## writes nothing to EVALS.md for you: paste the numbers in by hand
	python3 evals/run_task1.py
	cd task2_inbox && node evals/run.ts
	python3 evals/run_task3.py
demo-scope:
	cd task3_scope && python3 -m scope.cli demo
crawl:          ## first full, polite crawl of the real help center (needs ANTHROPIC_API_KEY)
	cd task1_brain && python3 -m brain.cli crawl
sync:           ## the daily job (the server also runs it on a timer)
	cd task1_brain && python3 -m brain.cli sync
