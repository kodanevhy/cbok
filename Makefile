PYTHON ?= python3
VENV ?= venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help install migrate

help:
	@printf '%s\n' 'make install'
	@printf '%s\n' 'make migrate'

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install -r requirements.txt
	$(VENV_PIP) install -e .

migrate:
	$(VENV_PYTHON) manage.py migrate --run-syncdb
