.PHONY: install dev test lint fmt eval docker run clean

install:
	pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload --port 8000

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

test:
	LLM_PROVIDER=fake pytest -q

lint:
	ruff check app tests eval
	ruff format --check app tests eval

fmt:
	ruff format app tests eval
	ruff check --fix app tests eval

eval:
	LLM_PROVIDER=fake python eval/run_eval.py

eval-live:
	LLM_PROVIDER=gemini python eval/run_eval.py

docker:
	docker build -t ai-jobhunt-copilot .

clean:
	rm -rf data .pytest_cache .ruff_cache __pycache__ eval/results.json
