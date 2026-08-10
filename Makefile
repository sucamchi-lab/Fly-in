VENV    = .venv
PYTHON  = $(VENV)/bin/python3
PIP     = $(VENV)/bin/pip
FLAKE8  = $(VENV)/bin/flake8
MYPY    = $(VENV)/bin/mypy
MYPY_FLAGS = --warn-return-any --warn-unused-ignores --ignore-missing-imports \
             --disallow-untyped-defs --check-untyped-defs

# Override on the command line, e.g. `make run MAP=maps/hard/02_capacity_hell.txt`
MAP = maps/easy/01_linear_path.txt

install:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) main.py $(MAP)

run-no-gui:
	$(PYTHON) main.py $(MAP) --no-gui

debug:
	$(PYTHON) main.py $(MAP) --debug --no-gui

lint:
	$(FLAKE8) .
	$(MYPY) . $(MYPY_FLAGS)

lint-strict:
	$(FLAKE8) .
	$(MYPY) . --strict

clean:
	rm -rf __pycache__ .mypy_cache

.PHONY: install run run-no-gui debug lint lint-strict clean