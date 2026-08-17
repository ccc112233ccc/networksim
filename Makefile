PYTHON ?= python3
SUITE ?= reverse-taack
PROFILE ?= compact
CASE ?= reverse-shared-fanin08

.PHONY: setup generate run suite analyze verify

setup:
	./scripts/setup.sh

generate:
	$(PYTHON) ./scripts/generate_cases.py --suite $(SUITE) --profile $(PROFILE)

run:
	./scripts/run_case.sh $(SUITE) $(CASE) $(PROFILE)

suite:
	./scripts/run_suite.sh $(SUITE) $(PROFILE)

analyze:
	$(PYTHON) ./scripts/analyze_results.py --suite $(SUITE) --profile $(PROFILE)

verify:
	$(PYTHON) ./scripts/verify_repository.py
