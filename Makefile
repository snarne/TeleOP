# Teleop Station developer shortcuts
PY ?= .venv/bin/python
STATION ?= .venv/bin/station

.PHONY: help setup sim serve doctor test e2e ui cad firmware-test clean

help:            ## list targets
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup:           ## one-time PC setup (Ubuntu)
	bash scripts/setup_ubuntu.sh

sim:             ## run the full station simulated (no hardware) on :8000
	$(STATION) serve --sim

serve:           ## run the station on real hardware on :8000
	$(STATION) serve

doctor:          ## check hardware + setup, with fixes
	$(STATION) doctor

test:            ## unit + in-process integration tests
	$(PY) -m pytest -q

e2e:             ## end-to-end test against a running `make sim` (other terminal)
	$(PY) tests/e2e_sim.py --url http://localhost:8000

ui:              ## build the web UI into ui/dist
	cd ui && npm ci && npm run build

cad:             ## regenerate STEP/STL/renders for the haptic grip module
	$(PY) hardware/cad/build.py

firmware-test:   ## host-side tests for both firmwares (trigger and fingertip sensor)
	$(MAKE) -C hardware/firmware/haptic_grip/test/native
	$(MAKE) -C hardware/firmware/fingertip/test/native

clean:
	rm -rf .sim_data .pytest_cache ui/dist
