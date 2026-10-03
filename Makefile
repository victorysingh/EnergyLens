# Retail energy analytics pipeline.
#
# On Windows without GNU make, use mingw32-make (MSYS2) in place of make,
# e.g.  mingw32-make all
#
# Note: in this project `make clean` is the data VALIDATION & CLEANING step
# (as named in the project brief), not "delete outputs". Use `make reset`
# to delete generated outputs, or `make reset-all` to also delete raw data.

PY ?= python

.PHONY: all data clean analyze export test notebook reset reset-all

all: data clean analyze export test

data:          ## download + verify BDG2 files
	$(PY) src/01_download.py

clean:         ## validate, clean, select buildings
	$(PY) src/02_validate_clean.py

analyze:       ## KPIs, anomalies, savings
	$(PY) src/03_kpis.py
	$(PY) src/04_anomalies.py
	$(PY) src/05_savings.py

export:        ## Power BI CSVs, figures, RESULTS.md, preview page
	$(PY) src/06_export_powerbi.py
	$(PY) src/07_report.py

test:
	$(PY) -m pytest -q tests

notebook:      ## re-execute the EDA notebook in place
	$(PY) -m jupyter nbconvert --to notebook --execute --inplace notebooks/exploration.ipynb

reset:
	$(PY) src/00_reset.py

reset-all:
	$(PY) src/00_reset.py --raw
