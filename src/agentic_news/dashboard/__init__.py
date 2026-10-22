"""Streamlit dashboard sections, each a `render_*` function called in order by app.py.

Global context: dimensions -> selection (rules) -> plan (batching, settings, Get News) -> status -> results.
Sections share the workspace RunConfig through `state`; they never run agents themselves (launcher does).
"""
