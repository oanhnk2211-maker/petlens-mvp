from __future__ import annotations

from datetime import datetime
from typing import Callable

import streamlit as st

from app.storage import list_history, load_history


def _format_time(value: object) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text or "时间未知"


def render_history(navigate: Callable[[str], None]) -> None:
    if st.button("← 返回小猫的家", key="history_back"):
        navigate("home")

    st.title("🕘 历史记录")
    rows = list_history()
    summaries: list[str] = []
    try:
        summaries = [result.quick_summary or result.direct_conclusion for result, _ in load_history()]
    except Exception:
        # Keep the page useful for legacy rows whose JSON cannot be decoded.
        pass

    if not rows:
        st.caption("还没有查询记录。")
        return

    for index, row in enumerate(rows):
        with st.container(border=True):
            st.subheader(str(row.get("item_name") or "未命名物品"))
            st.caption(f"{_format_time(row.get('created_at'))} · {row.get('species') or '物种未知'}")
            st.write(f"**风险等级：** {row.get('risk_level') or '未知'}")
            if index < len(summaries) and summaries[index]:
                st.write(summaries[index])

