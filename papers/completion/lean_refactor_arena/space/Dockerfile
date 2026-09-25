FROM python:3.11-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# UI-only image: all Lean compilation and scoring runs on a dedicated
# evaluation worker that exchanges jobs/results with this Space through the
# shared storage bucket mounted at /data. Nothing Lean-related is installed.
# fastapi/uvicorn come with gradio (app.py mounts the UI on its own FastAPI app
# so it can also serve the standalone /contribute page); markdown-it-py renders
# contribution.md into that page and is pinned here rather than relied on as a
# transitive dependency.
RUN pip install --no-cache-dir --user "gradio>=5,<6" "markdown-it-py>=3"

COPY --chown=user app.py benchmark.py leaderboard.py contribution.md \
                  benchmark_data_warmup.jsonl benchmark_heartbeats.jsonl .
COPY --chown=user assets /home/user/app/assets

EXPOSE 7860
CMD ["python", "app.py"]
