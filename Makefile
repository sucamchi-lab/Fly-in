VENV    = .venv
PYTHON  = $(VENV)/bin/python3
PIP     = $(VENV)/bin/pip
FLAKE8  = $(VENV)/bin/flake8
MYPY    = $(VENV)/bin/mypy

# MAP = maps/easy/01_linear_path.txt
# MAP = maps/easy/02_simple_fork.txt
# MAP = maps/easy/03_basic_capacity.txt
# MAP = maps/medium/01_dead_end_trap.txt
# MAP = maps/medium/02_circular_loop.txt
# MAP = maps/medium/03_priority_puzzle.txt
# MAP = maps/hard/01_maze_nightmare.txt
# MAP = maps/hard/02_capacity_hell.txt
MAP = maps/hard/03_ultimate_challenge.txt
# MAP = maps/challenger/01_the_impossible_dream.txt

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
	$(MYPY) . --warn-return-any --warn-unused-ignores --ignore-missing-imports \
             --disallow-untyped-defs --check-untyped-defs

lint-strict:
	$(FLAKE8) .
	$(MYPY) . --strict

clean:
	rm -rf __pycache__ .mypy_cache

.PHONY: install run run-no-gui debug lint lint-strict clean