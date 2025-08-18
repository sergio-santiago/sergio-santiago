.PHONY: install generate-gif clean

# Virtual environment directory
VENV := .venv

# Binaries inside the virtual environment
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Create virtual environment and install dependencies
install: $(PYTHON)

# Rule to set up the venv if it does not exist yet
$(PYTHON):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r tools/requirements.txt

# Generate the animated GIF using the venv's Python
generate-gif: $(PYTHON)
	$(PYTHON) tools/hi_terminal_prompt.py

# Clean up: remove venv and Python caches
clean:
	rm -rf $(VENV)
	find . -name "__pycache__" -type d -exec rm -rf {} +
