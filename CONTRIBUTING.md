# Contributing

Thanks for trying this project. It is an alpha-stage, single-maintainer project, but issues and pull requests are welcome.

## Before opening an issue

1. Run `python src/preflight.py` and paste the report (remove any local paths you do not want public).
2. Include your OS, GPU / VRAM, ComfyUI version, Ollama version and the exact command you ran.
3. If a generation failed, attach the input title, the pipeline (`single` / `redraw` / `alpha`) and the relevant log lines.

## Pull requests

- Keep changes focused; one topic per PR.
- Do not commit model weights, generated image dumps, `__pycache__`, or local paths.
- Run `python -m compileall -q src workbench` before pushing.
- If you change prompts or defaults, include one before/after example and explain the trade-off.

## Scope

- The project targets local, single-machine use. Cloud APIs, hosted services and multi-tenant deployments are out of scope for v0.1.
- Prompt or pipeline changes that improve one style must not silently regress the 14-case benchmark. Update `benchmark/results.csv` if you re-run it.
