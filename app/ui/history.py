from __future__ import annotations

from datetime import datetime
from typing import Callable

import streamlit as st

from app.storage import load_event_history


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
    events = load_event_history()
    rows = [
        {
            "created_at": event.created_at,
            "item_name": event.final_item or event.item_name,
            "species": event.species,
            "risk_level": event.risk_level,
            "confidence": event.confidence,
            "event_note": event.event_note,
            "question": event.question,
            "summary": event.result.quick_summary or event.result.direct_conclusion,
        }
        for event in events
    ]
    if not rows:
        st.caption("还没有查询记录。")
        return

    for index, row in enumerate(rows):
        with st.container(border=True):
            st.subheader(str(row.get("item_name") or "未命名物品"))
            st.caption(f"{_format_time(row.get('created_at'))} · {row.get('species') or '物种未知'}")
            st.write(f"**风险等级：** {row.get('risk_level') or '未知'}")
            if row.get("event_note"):
                st.write(f"**当时发生：** {row['event_note']}")
            if row.get("question"):
                st.write(f"**当时想确认：** {row['question']}")
            if row.get("summary"):
                st.write(row["summary"])

