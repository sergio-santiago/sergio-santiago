.DEFAULT_GOAL := help
.PHONY: help install badges gif assets clean

# Virtual environment directory
VENV := .venv

# Binaries inside the virtual environment
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help: ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

install: $(PYTHON) ## Create the virtualenv and install the build dependencies

# Rule to set up the venv if it does not exist yet
$(PYTHON):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r tools/requirements.txt

badges: $(PYTHON) ## Rebuild every badge under assets/badges/
	$(PYTHON) tools/build_badges.py

gif: $(PYTHON) ## Rebuild the animated terminal header
	$(PYTHON) tools/render_terminal_gif.py

assets: badges gif ## Rebuild everything the README points at

clean: ## Remove the virtualenv and Python caches
	rm -rf $(VENV)
	find . -name "__pycache__" -type d -exec rm -rf {} +
