VENV = venv
PYTHON = $(VENV)/bin/python3
MYPY = $(VENV)/bin/mypy
FLAKE8 = $(VENV)/bin/flake8
PIP = $(VENV)/bin/pip

install:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) main.py

debug:
	$(PYTHON) -m pdb main.py

clean:
	rm -rf __pycache__ .mypy_cache .pytest_cache

lint:
	$(FLAKE8) .
	$(MYPY) . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	$(FLAKE8) .
	$(MYPY) --strict .

.PHONY: install run debug clean lint lint-strict build