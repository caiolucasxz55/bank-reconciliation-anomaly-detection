"""Small Markdown table renderer for the README tables (avoids an extra dependency)."""

from __future__ import annotations

import pandas as pd


def format_percent(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.0%}"


def to_markdown(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    divider = "|" + "|".join(" --- " for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider, *rows])
