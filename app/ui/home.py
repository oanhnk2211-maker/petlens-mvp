from __future__ import annotations

import base64
import html
import random
from datetime import datetime
from pathlib import Path
from typing import Callable

import streamlit as st

from app.storage import list_history, load_history


ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "pet_home"
HOME_CAT_PATH = ASSET_ROOT / "cats" / "home_cat.png"
ICON_PATHS = {
    "query": ASSET_ROOT / "icons" / "query.png",
    "profile": ASSET_ROOT / "icons" / "profile.png",
    "history": ASSET_ROOT / "icons" / "history.png",
}
TOUCH_MESSAGES = (
    "喵～",
    "今天也要好好检查家里的东西哦。",
    "这里是我的家！",
    "今天也一起安全生活吧。",
)


def _image_data_uri(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:image/png;base64,{encoded}"


def _format_time(value: object) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text or "时间未知"


def _risk_tone(risk_level: object) -> tuple[str, str]:
    level = str(risk_level or "")
    if level in {"紧急", "避免"}:
        return "high", "⚠"
    if level == "谨慎":
        return "medium", "!"
    if level == "通常可用":
        return "low", "✓"
    return "neutral", "•"


def _latest_query() -> tuple[dict, str] | None:
    try:
        rows = list_history(limit=1)
    except Exception:
        return None
    if not rows:
        return None

    row = rows[0]
    summary = ""
    try:
        loaded = load_history(limit=1)
        if loaded:
            result = loaded[0][0]
            summary = result.quick_summary or result.direct_conclusion
    except Exception:
        # Old or incomplete history rows still show their safe summary fields.
        summary = ""
    return row, summary


def _render_icon(path: Path, fallback: str, label: str) -> None:
    if path.is_file():
        st.image(str(path), width=58)
        return
    st.markdown(
        f"<div class='pet-entry-fallback' role='img' aria-label='{html.escape(label)}'>{fallback}</div>",
        unsafe_allow_html=True,
    )


def _render_recent_query() -> None:
    st.markdown("<div class='recent-title'>最近发现</div>", unsafe_allow_html=True)
    recent = _latest_query()
    if recent is None:
        st.caption("还没有查询记录，去看看家里有什么吧。")
        return

    row, summary = recent
    tone, symbol = _risk_tone(row.get("risk_level"))
    item_name = html.escape(str(row.get("item_name") or "未命名物品"))
    risk_level = html.escape(str(row.get("risk_level") or "信息不足"))
    conclusion = html.escape(str(summary or "暂无简短结论"))
    created_at = html.escape(_format_time(row.get("created_at")))
    st.markdown(
        f"""
        <div class="recent-card risk-{tone}">
          <div class="recent-main"><span class="risk-symbol">{symbol}</span><b>{item_name}</b></div>
          <div class="recent-risk">{risk_level} · {conclusion}</div>
          <div class="recent-time">{created_at}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_home(navigate: Callable[[str], None]) -> None:
    """Render the compact, mobile-first PetHome v0.2 landing page."""
    st.markdown(
        """
        <style>
        .stApp { background: #fffaf0; overflow-x: hidden; }
        .block-container {
            max-width: 560px;
            padding: 1.2rem .9rem 2.8rem;
        }
        .pet-home-title { text-align: center; margin-bottom: .2rem; }
        .pet-home-title .brand { color: #76552c; font-size: 1rem; letter-spacing: .12em; }
        .pet-home-title h1 { color: #3f2d1d; font-size: 2rem; margin: .1rem 0 .2rem; }
        .pet-home-title p { color: #8a6d42; margin: 0; font-size: .9rem; }
        .pet-cat-stage {
            min-height: 210px;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: .25rem 0 .1rem;
        }
        .pet-cat-stage img {
            width: min(230px, 62vw);
            height: auto;
            image-rendering: pixelated;
            animation: pet-breathe 3s ease-in-out infinite;
            transform-origin: center bottom;
        }
        @keyframes pet-breathe {
            0%, 100% { transform: translateY(0) scale(1); }
            50% { transform: translateY(-3px) scale(1.015); }
        }
        .pet-entry-fallback {
            height: 58px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2.35rem;
            line-height: 1;
        }
        [data-testid="stImage"] { display: flex; justify-content: center; }
        [data-testid="stHorizontalBlock"] { align-items: end; }
        .stButton > button {
            min-height: 2.35rem;
            border-radius: 14px;
            border-color: #e7c96d;
            color: #49331f;
            font-size: .9rem;
            padding: .2rem .35rem;
        }
        .stButton > button[kind="primary"] {
            background: #f7cf55;
            border-color: #f0c33d;
        }
        .pet-touch-row { text-align: center; margin: .15rem 0 .8rem; }
        .pet-touch-message { text-align: center; color: #8a6d42; font-size: .88rem; min-height: 1.35rem; }
        .recent-title { color: #4a3824; font-size: 1.05rem; font-weight: 700; margin: 1rem 0 .45rem; }
        .recent-card {
            border-radius: 17px;
            border: 1px solid #eadcb9;
            background: rgba(255,255,255,.74);
            padding: .8rem .9rem;
        }
        .recent-card.risk-high { border-color: #efb2a8; background: #fff4f1; }
        .recent-card.risk-medium { border-color: #efd68a; background: #fff9e8; }
        .recent-card.risk-low { border-color: #b8d7ad; background: #f4fbf1; }
        .recent-main { color: #3f2d1d; font-size: 1.02rem; }
        .risk-symbol { display: inline-flex; width: 1.35rem; height: 1.35rem; align-items: center; justify-content: center; margin-right: .35rem; border-radius: 50%; font-weight: 800; }
        .risk-high .risk-symbol { color: #a83327; background: #ffd8d1; }
        .risk-medium .risk-symbol { color: #8b6500; background: #ffe9a9; }
        .risk-low .risk-symbol { color: #3d7f3b; background: #d9f0cf; }
        .risk-neutral .risk-symbol { color: #806a4a; background: #eee5d2; }
        .recent-risk { margin-top: .3rem; color: #5e4932; font-size: .9rem; }
        .recent-time { margin-top: .25rem; color: #9a8467; font-size: .76rem; }
        @media (prefers-reduced-motion: reduce) { .pet-cat-stage img { animation: none; } }
        </style>
        <div class="pet-home-title">
          <div class="brand">PetLens</div>
          <h1>小猫的家</h1>
          <p>今天也一起检查家里的东西吧。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cat_uri = _image_data_uri(HOME_CAT_PATH)
    if cat_uri:
        st.markdown(
            f"<div class='pet-cat-stage'><img src='{cat_uri}' alt='像素小猫'></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='pet-cat-stage'><div class='pet-entry-fallback' role='img' aria-label='小猫'>🐱</div></div>",
            unsafe_allow_html=True,
        )

    touch_left, touch_center, touch_right = st.columns([1, 2, 1])
    with touch_center:
        if st.button("摸摸小猫", key="home_pet_touch", use_container_width=True):
            st.session_state["cat_interaction_message"] = random.choice(TOUCH_MESSAGES)
    message = st.session_state.get("cat_interaction_message", "")
    st.markdown(
        f"<div class='pet-touch-message'>{html.escape(message) if message else '&nbsp;'}</div>",
        unsafe_allow_html=True,
    )

    entries = (
        ("query", "查询", "📷", "识别家里的东西"),
        ("profile", "档案", "🐾", "查看猫咪档案"),
        ("history", "历史", "🕘", "查看最近记录"),
    )
    columns = st.columns(3, gap="small")
    for column, (page, label, fallback, help_text) in zip(columns, entries):
        with column:
            _render_icon(ICON_PATHS[page], fallback, label)
            if st.button(label, key=f"home_{page}", help=help_text, use_container_width=True):
                navigate(page)

    _render_recent_query()

