from __future__ import annotations

from typing import Callable

import streamlit as st

from app.models import PetProfile
from app.storage import load_history


def _current_profile() -> PetProfile:
    stored = st.session_state.get("pet_profile")
    if stored:
        try:
            return PetProfile.model_validate(stored)
        except (TypeError, ValueError):
            pass

    try:
        history = load_history(limit=1)
        if history:
            return history[0][1]
    except Exception:
        # A profile shell must remain usable even when old history is unreadable.
        pass

    return PetProfile(name="我的小猫", species="猫")


def render_profile(navigate: Callable[[str], None]) -> None:
    if st.button("← 返回小猫的家", key="profile_back"):
        navigate("home")

    profile = _current_profile()
    st.title("🐱 猫咪档案")
    with st.container(border=True):
        st.markdown(f"### {profile.name or '我的小猫'}")
        st.write(f"**物种：** {profile.species}")
        st.write(f"**年龄：** {f'{profile.age_years:g} 岁' if profile.age_years is not None else '未填写'}")
        st.write(f"**体重：** {f'{profile.weight_kg:g} kg' if profile.weight_kg is not None else '未填写'}")
        st.write(f"**补充信息：** {profile.notes or '未填写'}")

    st.info("个性化档案将在后续版本继续完善")

