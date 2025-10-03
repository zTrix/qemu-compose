# Repository Guidelines

## Project Structure & Module Organization
- Source: `qemu_compose/` (CLI entry `main.py`, helpers like `jsonlisp.py`, `qemu/` utils).
- Examples: `script/` (e.g., `script/ubuntu-cloudimg__amd64/` demo scenarios).
- Assets: `assets/` (images, asciicast SVG).
- Packaging: `pyproject.toml`, `dist/` (build artifacts), `build_and_install.sh`.
- Docs: `README.md`, `devbox.yml` (example VM definition).

## Build, Test, and Development Commands
- Install for dev: `pip install -e .` (use a venv; Python ≥3.8).
- Build wheel: `uv build` (writes to `dist/`).
- Local install from wheel: `pip install ./dist/qemu_compose-*.whl`.
- Quick demo: `cd script/ubuntu-cloudimg__amd64 && qemu-compose up`.
- Help: `qemu-compose --help`.

## Coding Style & Naming Conventions
- Python, PEP 8, 4‑space indent; prefer type hints.
- Use `snake_case` for functions/variables, `CapWords` for classes, kebab/snake for CLI flags/options.
- Modules under `qemu_compose/qemu/` mirror QEMU concepts; keep filenames descriptive (e.g., `qmp_client.py`).
- Keep functions small; avoid side effects in helpers; log through `log_tool.py`.

## Testing Guidelines
- No formal suite yet. If adding tests, use `pytest` under `tests/` with `test_*.py` files.
- Prefer fast, unit‑level coverage for `jsonlisp`, `qmp` client, and config parsing.
- Smoke test changes via example scripts (`qemu-compose up`) and document steps in PR.

## Commit & Pull Request Guidelines
- Commit messages: imperative, scoped prefix when relevant (e.g., `qmp: fix handshake retry`).
- PRs must include: summary, rationale, affected modules/paths, reproduction or demo (`script/...`), and before/after logs.
- Link issues when applicable; add screenshots or console output for UX changes.

## Security & Configuration Tips
- QEMU/OVMF paths vary by distro; avoid hard‑coding. Use env interpolation in YAML (`{storage_path}` style).
- Prefer venv installs; avoid `sudo pip` unless using `build_and_install.sh` knowingly.

## Architecture Overview
- CLI reads `qemu-compose.yml`, composes QEMU args, runs lifecycle hooks (`before_script`, `boot_commands`, `after_script`), and exposes HTTP provisioning via cloud‑init helpers.
