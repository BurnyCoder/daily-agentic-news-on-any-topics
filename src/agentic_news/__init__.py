"""agentic_news — launch one Codex CLI agent per topic to collect top news, and show the results in Streamlit.

Global context: `pipeline.run_pipeline` is the wrapper that calls each phase; `cli` runs it headless and
`app.py` (Streamlit) launches the CLI in the background when the user clicks "Get News".
"""
