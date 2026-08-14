.PHONY: test smoke smoke-synthid bootstrap-synthid docker-synthid-build docker-synthid-help \
	smoke-ctrlregen bootstrap-ctrlregen docker-ctrlregen-build docker-ctrlregen-help \
	smoke-markllm bootstrap-markllm docker-markllm-build docker-markllm-help \
	smoke-markdiffusion bootstrap-markdiffusion docker-markdiffusion-build docker-markdiffusion-help \
	install-skill clean

SCRIPTS := skills/remove-ai-marks/scripts
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

test:
	$(PYTHON) -m pytest

smoke:
	-python3 $(SCRIPTS)/inspect_text.py tests/fixtures/sample_watermarked.txt
	python3 $(SCRIPTS)/clean_text.py tests/fixtures/sample_watermarked.txt -o /tmp/wm.cleaned.txt --stats
	python3 $(SCRIPTS)/rewrite_text.py tests/fixtures/sample_watermarked.txt --backend print-prompt >/dev/null
	-python3 $(SCRIPTS)/inspect_file.py tests/fixtures/sample_ai.md
	python3 $(SCRIPTS)/clean_file.py tests/fixtures/sample_ai.md -o /tmp/sample_ai.cleaned.md
	python3 $(SCRIPTS)/clean_file.py tests/fixtures/sample_ai.html -o /tmp/sample_ai.cleaned.html
	python3 $(SCRIPTS)/clean_file.py tests/fixtures/sample_meta.svg -o /tmp/sample_meta.cleaned.svg
	@echo "smoke ok"

smoke-synthid:
	@if [ -z "$(REVERSE_SYNTHID_DIR)" ]; then \
	  echo "smoke-synthid skipped (set REVERSE_SYNTHID_DIR)"; \
	else \
	  $(PYTHON) $(SCRIPTS)/score_synthid.py --help >/dev/null && echo "score_synthid adapter present"; \
	fi

bootstrap-synthid:
	./skills/remove-ai-marks/scripts/setup_synthid.sh

docker-synthid-build:
	docker build -f Dockerfile.synthid -t watermarks-remover-synthid-scorer .

docker-synthid-help:
	docker run --rm watermarks-remover-synthid-scorer --help

smoke-ctrlregen:
	@if [ -z "$(NOAI_WATERMARK_DIR)" ]; then \
	  echo "smoke-ctrlregen skipped (set NOAI_WATERMARK_DIR)"; \
	else \
	  $(PYTHON) $(SCRIPTS)/clean_ctrlregen.py --help >/dev/null && echo "clean_ctrlregen adapter present"; \
	fi

bootstrap-ctrlregen:
	./skills/remove-ai-marks/scripts/setup_ctrlregen.sh

docker-ctrlregen-build:
	docker build -f Dockerfile.ctrlregen -t watermarks-remover-ctrlregen .

docker-ctrlregen-help:
	docker run --rm watermarks-remover-ctrlregen --help

smoke-markllm:
	@if [ -z "$(MARKLLM_DIR)" ]; then \
	  echo "smoke-markllm skipped (set MARKLLM_DIR)"; \
	else \
	  $(PYTHON) $(SCRIPTS)/detect_text_watermark.py --help >/dev/null && echo "detect_text_watermark adapter present"; \
	fi

bootstrap-markllm:
	./skills/remove-ai-marks/scripts/setup_markllm.sh

docker-markllm-build:
	docker build -f Dockerfile.markllm -t watermarks-remover-markllm .

docker-markllm-help:
	docker run --rm watermarks-remover-markllm --help

smoke-markdiffusion:
	@if [ -z "$(MARKDIFFUSION_DIR)" ]; then \
	  echo "smoke-markdiffusion skipped (set MARKDIFFUSION_DIR)"; \
	else \
	  $(PYTHON) $(SCRIPTS)/markdiffusion_harness.py --help >/dev/null && echo "markdiffusion_harness adapter present"; \
	fi

bootstrap-markdiffusion:
	./skills/remove-ai-marks/scripts/setup_markdiffusion.sh

docker-markdiffusion-build:
	docker build -f Dockerfile.markdiffusion -t watermarks-remover-markdiffusion .

docker-markdiffusion-help:
	docker run --rm watermarks-remover-markdiffusion --help

install-skill:
	mkdir -p $(HOME)/.grok/skills
	ln -sfn $(CURDIR)/skills/remove-ai-marks $(HOME)/.grok/skills/remove-ai-marks
	@echo "linked -> $(HOME)/.grok/skills/remove-ai-marks"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .venv
