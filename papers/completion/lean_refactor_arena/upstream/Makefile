.PHONY: install
install: ## Install the virtual environment
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv pip install "flash_attn==2.8.3" --no-build-isolation

.DEFAULT_GOAL := install
