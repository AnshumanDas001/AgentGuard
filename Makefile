.PHONY: setup lint fmt test sandbox check run tasks data-check data-stats label label-sheet import-labels write-sheet import-written injecagent assebench data-split guard-dev train-classifier tune relabel-sheet relabel-compare augment train-classifier-aug eval-dev test-runs report

setup:  ## install dependencies
	uv sync

lint:  ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## auto-fix lint and formatting
	uv run ruff check --fix .
	uv run ruff format .

test:  ## unit tests (no Docker or API key needed)
	uv run pytest -q

sandbox:  ## build the agent sandbox image
	docker build -t agentguard-sandbox:latest sandbox

check:  ## preflight: Docker, sandbox image, API key
	uv run python -m agentguard check

run:  ## run the agent on one task: make run TASK="find the TODOs"
	uv run python -m agentguard run "$(TASK)"

tasks:  ## run the 10 ordinary tasks (Phase 1 gate)
	uv run python -m agentguard tasks

data-check:  ## validate every dataset file
	uv run python -m agentguard.dataset check

data-stats:  ## dataset counts and progress against targets
	uv run python -m agentguard.dataset stats

label:  ## label unlabeled rows, one at a time (blind)
	uv run python -m agentguard.dataset label

label-sheet:  ## export unlabeled rows to a spreadsheet to label
	uv run python -m agentguard.dataset export-sheet

import-labels:  ## save labels from a filled-in sheet: make import-labels SHEET=path.xlsx
	uv run python -m agentguard.dataset import-sheet "$(SHEET)"

write-sheet:  ## blank spreadsheet for writing rows by hand
	uv run python -m agentguard.dataset write-sheet

import-written:  ## add handwritten rows from a filled sheet: make import-written SHEET=path.xlsx
	uv run python -m agentguard.dataset import-written "$(SHEET)"

injecagent:  ## fetch InjecAgent (pinned commit) and add converted rows
	uv run python -m agentguard.dataset import-injecagent

assebench:  ## fetch ASSEBench (pinned commit) and add in-scope converted rows
	uv run python -m agentguard.dataset import-assebench

data-split:  ## stratified 50/20/30 split, then freeze the test set (runs once)
	uv run python -m agentguard.dataset split

guard-dev:  ## run one guard on the dev split: make guard-dev BACKEND=rules (or judge-cheap, judge-strong, classifier, cascade)
	uv run --group ml python -m agentguard.eval run --backend $(BACKEND) --split dev

train-classifier:  ## fine-tune DeBERTa-v3-small on train, keep the best dev epoch (Apple GPU / CUDA / CPU)
	uv run --group ml python -m agentguard.guard.train_classifier

tune:  ## pick thresholds and a cascade from the saved dev runs (no API calls)
	uv run python -m agentguard.eval tune

relabel-sheet:  ## blind spreadsheet of the ambiguous dev rows, to relabel
	uv run python -m agentguard.eval relabel-sheet

relabel-compare:  ## compare a filled relabel sheet: make relabel-compare SHEET=path.xlsx
	uv run python -m agentguard.eval relabel-compare "$(SHEET)"

augment:  ## contrastive twins of the train rows: data/augmented/train-twins.jsonl
	uv run python -m agentguard.dataset augment

train-classifier-aug:  ## fine-tune the classifier on train plus the twins (models/deberta-guard-aug)
	uv run --group ml python -m agentguard.guard.train_classifier --augment

eval-dev:  ## Level 1 metrics with bootstrap CIs on the saved dev runs (no API calls)
	uv run python -m agentguard.eval evaluate --split dev

TEST_BACKENDS ?= rules classifier jev judge-cheap
test-runs:  ## the single Phase 4 test run: each backend 3 times (run 1 is scored; 2-3 for latency)
	for r in 1 2 3; do for b in $(TEST_BACKENDS); do \
		uv run --group ml python -m agentguard.eval run --backend $$b --split test --allow-test --repeat $$r || exit 1; \
	done; done

report:  ## metrics with CIs on the test runs, then the charts in results/charts/ (no API calls)
	uv run python -m agentguard.eval evaluate --split test
	uv run --group report python -m agentguard.eval.charts
