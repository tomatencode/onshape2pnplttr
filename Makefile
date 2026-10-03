PY ?= python3
# The package lives in src/; run it without installing via PYTHONPATH.
PYTHONPATH ?= src

.PHONY: help install test convert tidy clean

help:
	@echo "make test                 # run the unittest suite"
	@echo "make convert PDF=...      # convert a PDF to .pnplttr"
	@echo "make tidy IN=...          # clean up a generated .pnplttr"
	@echo "make install              # editable install (use inside a venv)"
	@echo "make clean                # remove build artefacts"

install:
	$(PY) -m pip install -e .

test:
	PYTHONPATH=$(PYTHONPATH) $(PY) -m unittest discover -s tests -v

convert:
	@test -n "$(PDF)" || (echo "usage: make convert PDF=drawing.pdf [OUT=drawing.pnplttr]"; exit 1)
	PYTHONPATH=$(PYTHONPATH) $(PY) -m onshape2pnplttr "$(PDF)" $(if $(OUT),-o $(OUT),)

tidy:
	@test -n "$(IN)" || (echo "usage: make tidy IN=drawing.pnplttr [OUT=clean.pnplttr] [ARGS=--dry-run]"; exit 1)
	PYTHONPATH=$(PYTHONPATH) $(PY) -m onshape2pnplttr.clean_cli "$(IN)" \
		$(if $(OUT),-o $(OUT),) $(ARGS)

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
