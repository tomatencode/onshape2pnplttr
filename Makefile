PY ?= python3
# The package lives in src/; run it without installing via PYTHONPATH.
PYTHONPATH ?= src

.PHONY: help install test convert clean

help:
	@echo "make test                 # run the unittest suite"
	@echo "make convert PDF=...      # convert a PDF to .pnplttr"
	@echo "make install              # editable install (use inside a venv)"
	@echo "make clean                # remove build artefacts"

install:
	$(PY) -m pip install -e .

test:
	PYTHONPATH=$(PYTHONPATH) $(PY) -m unittest discover -s tests -v

convert:
	@test -n "$(PDF)" || (echo "usage: make convert PDF=drawing.pdf [OUT=drawing.pnplttr]"; exit 1)
	PYTHONPATH=$(PYTHONPATH) $(PY) -m onshape2pnplttr "$(PDF)" $(if $(OUT),-o $(OUT),)

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
