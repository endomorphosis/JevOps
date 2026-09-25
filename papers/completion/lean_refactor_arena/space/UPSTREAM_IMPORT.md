# Vendored Lean Refactor Arena Space

This directory is the tracked source snapshot of the public Hugging Face
Space that hosts the Lean Refactor Arena UI. It complements the JevOps-local
warm-up harness and the vendored optimizer source in `../upstream/`.

- Source: https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena
- Source commit: `6a1384b7e3127f5d556e727d5d53cc17b4acdb40`
- Imported: 2026-09-22
- Snapshot manifest: [`VENDOR_MANIFEST.json`](VENDOR_MANIFEST.json)

The snapshot includes the Gradio/FastAPI application, benchmark and
leaderboard modules, Docker metadata, assets, warm-up data, and heartbeat
records. The Space README states that it is UI-only: Lean compilation and
official scoring are performed by a separate evaluation worker. Those worker
credentials, storage bucket, and deployment environment are not present in
the public Space repository and are not fabricated here.

The app has optional web dependencies (`gradio`, `fastapi`, and
`markdown-it-py`). They are intentionally not added to JevOps' core
`pyproject.toml`; the offline harness and kernel remain runnable without the
Space service stack.

For an explicitly provisioned Space environment, run from this directory:

```bash
python app.py
```

This is an application snapshot, not evidence that JevOps has submitted to or
received a score from the live Arena.
