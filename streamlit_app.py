from __future__ import annotations

from datetime import datetime, timedelta, timezone
import mimetypes
import os

import streamlit as st
from dotenv import load_dotenv

from app.charts import radar_chart
from app.export import export_json, sanitize_export
from app.models import PetProfile
from app.pipeline import evaluate_item
from app.providers import QwenVisionProvider, VisionError, VisionResult
from app.providers.vision_base import image_fingerprint, recognize_once
from app.storage import init_db, list_history, load_event_history, save_event
from app.ui.history import render_history
from app.ui.home import render_home
from app.ui.profile import render_profile

load_dotenv()
init_db()

st.set_page_config(page_title="PetLens / 小猫的家", page_icon="🐾", layout="centered")


def navigate(page: str) -> None:
    st.session_state["page"] = page
    st.rerun()


if "page" not in st.session_state:
    st.session_state["page"] = "home"

current_page = st.session_state["page"]
if current_page == "home":
    render_home(navigate)
    st.stop()
if current_page == "profile":
    render_profile(navigate)
    st.stop()
if current_page == "history":
    render_history(navigate)
    st.stop()
if current_page != "query":
    st.session_state["page"] = "home"
    st.rerun()

def continue_query() -> None:
    """Clear only transient query UI state while preserving vision cache and history."""
    for key in (
        "latest_result",
        "latest_event",
        "current_vision_result",
        "current_vision_fingerprint",
        "recognized_name_input",
        "query_item_input",
        "event_note_input",
        "event_question_input",
        "camera_input",
        "upload_input",
        "vision_error",
    ):
        st.session_state.pop(key, None)
    st.session_state["page"] = "query"
    st.rerun()


if "latest_result" not in st.session_state:
    if st.button("← 返回小猫的家", key="query_back_top"):
        navigate("home")

st.markdown("""
<style>
.block-container {max-width: 1040px; padding-top: 1.2rem; padding-bottom: 4rem;}
.hero {padding: 1.1rem 1.2rem; border-radius: 20px; background: linear-gradient(135deg,#f6f7ff,#fff7ee); margin-bottom: 1rem;}
.hero h1 {font-size: 2rem; margin: 0 0 .35rem 0;}
.hero p {margin: 0; opacity: .78;}
.risk-card {padding: 1rem 1.1rem; border: 1px solid rgba(120,120,120,.25); border-radius: 18px; margin: .5rem 0 1rem 0;}
.small-note {font-size: .86rem; opacity: .72;}
.context-tile {min-height: 108px; padding: .8rem; border-radius: 14px; background: #f6f7ff; border: 1px solid rgba(120,120,120,.18);}
.context-tile.muted {opacity: .62; background: #fafafa;}
.context-tile b {display: block; margin-bottom: .25rem;}
.context-tile span {font-size: .78rem; opacity: .7;}
.context-tile p {font-size: .86rem; margin: .5rem 0 0 0;}
</style>
<div class="hero"><h1>🐾 PetLens</h1><p>记录宠物身边的新情况，再结合宠物画像给出下一步判断。</p></div>
""", unsafe_allow_html=True)

status_bits = []
status_bits.append("百炼图片识别已配置" if os.getenv("DASHSCOPE_API_KEY") else "图片识别未配置（可手动输入）")
status_bits.append("百炼文本分析已配置" if os.getenv("DASHSCOPE_API_KEY") else "本地知识库模式")
st.caption(" · ".join(status_bits))

def _profile_seed() -> PetProfile:
    stored = st.session_state.get("pet_profile")
    if stored:
        try:
            return PetProfile.model_validate(stored)
        except (TypeError, ValueError):
            pass
    try:
        events = load_event_history(limit=1)
        if events:
            return events[0].profile
    except Exception:
        pass
    return PetProfile(name="我的小猫", species="猫")


def _recent_history_events() -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        events = load_event_history(limit=30)
    except Exception:
        return []
    recent = []
    for event in events:
        try:
            created = datetime.fromisoformat(event.created_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if created >= cutoff:
            recent.append(event)
    return recent[:8]


def _history_context(event) -> dict:
    return {
        "source": "recent_history",
        "event_id": event.event_id,
        "created_at": event.created_at,
        "event_note": event.event_note,
        "question": event.question,
        "subject": event.final_item or event.item_name,
        "prior_summary": event.result.quick_summary or event.result.direct_conclusion,
    }


def _render_context_tile(title: str, status: str, body: str, *, muted: bool = False) -> None:
    tone = " muted" if muted else ""
    st.markdown(
        f"<div class='context-tile{tone}'><b>{title}</b><span>{status}</span><p>{body}</p></div>",
        unsafe_allow_html=True,
    )


def recognize_uploaded_image(uploaded_file, button_prefix: str) -> None:
    image_bytes = uploaded_file.getvalue()
    media_type = uploaded_file.type or mimetypes.guess_type(getattr(uploaded_file, "name", ""))[0] or ""
    fingerprint = image_fingerprint(image_bytes)
    cache = st.session_state.get("vision_results", {})
    has_cached_result = fingerprint in cache
    label = "重新识别" if has_cached_result else "识别图片"
    if st.button(label, key=f"{button_prefix}_recognize", use_container_width=True):
        try:
            with st.spinner("正在识别图片中的主要对象…"):
                result = recognize_once(
                    QwenVisionProvider(), image_bytes, media_type, st.session_state,
                    force=has_cached_result,
                )
            st.session_state["current_vision_result"] = result.model_dump()
            st.session_state["current_vision_fingerprint"] = fingerprint
            st.session_state["recognized_name_input"] = result.item_name
            st.session_state.pop("vision_error", None)
        except VisionError as exc:
            st.session_state["vision_error"] = str(exc)
            st.session_state.pop("current_vision_result", None)
    elif has_cached_result:
        st.session_state["current_vision_result"] = cache[fingerprint]
        st.session_state["current_vision_fingerprint"] = fingerprint


profile_seed = _profile_seed()

detail_modes = ["最简易", "普通展开", "详尽展开"]
detail_mode = st.select_slider(
    "分析展开程度",
    options=detail_modes,
    value=st.session_state.get("analysis_detail_mode", "普通展开"),
    key="analysis_detail_mode",
)
mode_captions = {
    "最简易": "只写必答问题，系统自动整理少量相关背景。",
    "普通展开": "在问题之外补充图片和近期事件，画像细节保持简洁。",
    "详尽展开": "逐项查看并选择画像、近期事件和长期历史。",
}
st.caption(mode_captions[detail_mode])

st.subheader("组装这次分析")
st.caption("先写下这次想确认的问题，再决定哪些上下文要交给 PetLens。每张卡片都可以查看或修改。")

if detail_mode != "最简易":
    query_col, material_col = st.columns(2)
else:
    query_col = st.container()

with query_col:
    with st.container(border=True):
        st.markdown("### ① 当次查询")
        event_question = st.text_area(
            "这次想确认什么？",
            placeholder="例如：小猫吃完罐头后一直舔舌头，需要注意什么？",
            key="event_question_input",
            height=90,
        )
        event_note = ""
        if detail_mode != "最简易":
            event_note = st.text_area(
                "这次发生了什么？（可选补充）",
                placeholder="例如：刚吃完罐头，看起来很高兴，坐着舔舌头。",
                key="event_note_input",
                height=90,
            )
        st.caption("只填写问题即可，其他背景会由系统自动整理。" if detail_mode == "最简易" else "这张卡片是必答项。可以自由描述问题，不要求先选分类。")

query_item = ""
recognized = None
use_image_context = False
if detail_mode != "最简易":
    with material_col:
        with st.container(border=True):
            st.markdown("### ② 当次补充材料")
            query_item = st.text_input(
                "如果知道对象，可以先写在这里（可选）",
                placeholder="例如：葡萄、百合、药品、猫粮",
                key="query_item_input",
            )
            with st.expander("＋ 添加图片（可选）", expanded=False):
                st.caption("图片先只做识别和事实整理，识别结果可以修改后再进入分析。")
                upload_tab, camera_tab = st.tabs(["选择文件", "现场拍摄"])
                with upload_tab:
                    upload_file = st.file_uploader(
                        "选择一张相关图片",
                        type=["jpg", "jpeg", "png", "webp"],
                        key="upload_input",
                    )
                    if upload_file:
                        st.image(upload_file, use_container_width=True)
                        recognize_uploaded_image(upload_file, "upload")
                with camera_tab:
                    camera_file = st.camera_input("拍下这次发现的对象", key="camera_input")
                    if camera_file:
                        recognize_uploaded_image(camera_file, "camera")

            if st.session_state.get("vision_error"):
                st.error(st.session_state["vision_error"])
                st.caption("图片识别失败不影响本次提交，你仍可以手动描述问题。")

            recognized_data = st.session_state.get("current_vision_result")
            recognized = VisionResult.model_validate(recognized_data) if recognized_data else None
            if recognized:
                st.markdown("#### 识别结果（可修正）")
                c1, c2 = st.columns(2)
                c1.metric("识别对象", recognized.item_name)
                c2.metric("置信度", f"{recognized.confidence:.0%}")
                st.write(f"**标准名称：** {recognized.normalized_name}")
                st.write(f"**客观描述：** {recognized.description or '无'}")
                st.write(f"**可见文字：** {'、'.join(recognized.visible_text) or '未识别到'}")
                st.write(f"**候选名称：** {'、'.join(recognized.candidate_names) or '无'}")
                st.write(f"**不确定性：** {recognized.uncertainty or '无'}")
                if recognized.confidence < 0.65:
                    st.warning("识别置信度较低，请仔细核对并修改名称后再查询。")
                query_item = st.text_input("确认或修改识别对象", key="recognized_name_input")
                use_image_context = st.checkbox(
                    "把这次图片观察带入分析",
                    value=True,
                    key="use_image_context",
                )

profile = profile_seed
use_profile_context = True
if detail_mode == "详尽展开":
    with st.container(border=True):
        st.markdown("### ③ 长期宠物画像")
        st.caption("稳定信息默认用于分析；物种始终保留，其他画像细节可以临时排除。")
        c1, c2 = st.columns(2)
        with c1:
            pet_name = st.text_input("名字", value=profile_seed.name, key="profile_name_input")
            species_options = ["猫", "狗", "兔子", "鸟", "其他"]
            species = st.selectbox(
                "物种",
                species_options,
                index=species_options.index(profile_seed.species) if profile_seed.species in species_options else 0,
                key="profile_species_input",
            )
            sex_options = ["未知", "公", "母"]
            sex = st.selectbox(
                "性别",
                sex_options,
                index=sex_options.index(profile_seed.sex) if profile_seed.sex in sex_options else 0,
                key="profile_sex_input",
            )
        with c2:
            age = st.number_input(
                "年龄（岁，可选）",
                min_value=0.0,
                max_value=100.0,
                value=profile_seed.age_years,
                step=0.5,
                key="profile_age_input",
            )
            weight = st.number_input(
                "体重（kg，可选）",
                min_value=0.0,
                max_value=500.0,
                value=profile_seed.weight_kg,
                step=0.1,
                key="profile_weight_input",
            )
        notes = st.text_input(
            "补充信息（过敏、幼宠、疾病、用药等）",
            value=profile_seed.notes,
            placeholder="例如：3个月幼猫、曾有肾病、正在服药",
            key="profile_notes_input",
        )
        use_profile_context = st.checkbox(
            "把画像细节带入本次分析（物种始终保留）",
            value=True,
            key="use_profile_context",
        )
    profile = PetProfile(
        name=pet_name or "我的宠物",
        species=species,
        sex=sex,
        age_years=age if age and age > 0 else None,
        weight_kg=weight if weight and weight > 0 else None,
        notes=notes,
    )
    st.session_state["pet_profile"] = profile.model_dump()

analysis_profile = profile if use_profile_context else PetProfile(name=profile.name, species=profile.species, sex=profile.sex)

selected_recent_context: list[dict] = []
if detail_mode == "最简易":
    # The model receives a small candidate set while the UI stays as simple as a chat box.
    selected_recent_context = [_history_context(event) for event in _recent_history_events()[:3]]
elif detail_mode == "普通展开":
    st.caption("画像会自动保留；如果需要更细的画像字段或长期历史，请切换到详尽展开。")
    with st.expander("＋ 添加近期重点（可选）", expanded=False):
        manual_recent_text = st.text_area(
            "手动补充近期重点（每行一条）",
            placeholder="例如：\n最近食欲正常\n正在服用新的药物",
            key="recent_context_input",
            height=80,
        )
        manual_items = [line.strip() for line in manual_recent_text.splitlines() if line.strip()]
        for index, item in enumerate(manual_items):
            if st.checkbox(f"使用：{item}", value=True, key=f"manual_recent_{index}"):
                selected_recent_context.append({"source": "user_recent_note", "label": item})
        selected_recent_context.extend(
            _history_context(event) for event in _recent_history_events()[:3]
        )
elif detail_mode == "详尽展开":
    with st.container(border=True):
        st.markdown("### ④ 近期值得注意")
        st.caption("每行写一个简短重点。近三天的历史会作为便签出现，你可以逐条取消。")
        manual_recent_text = st.text_area(
            "手动补充近期重点（每行一条）",
            placeholder="例如：\n最近食欲正常\n正在服用新的药物",
            key="recent_context_input",
            height=80,
        )
        manual_items = [line.strip() for line in manual_recent_text.splitlines() if line.strip()]
        for index, item in enumerate(manual_items):
            if st.checkbox(f"使用：{item}", value=True, key=f"manual_recent_{index}"):
                selected_recent_context.append({
                    "source": "user_recent_note",
                    "label": item,
                })

        auto_events = _recent_history_events()
        if auto_events:
            st.markdown("**近三天自动带入的历史便签**")
            for index, event in enumerate(auto_events):
                history_context = _history_context(event)
                label = history_context["event_note"] or history_context["question"] or history_context["subject"]
                key_suffix = event.event_id.replace(":", "_")
                if st.checkbox(
                    f"{label} · {event.species}",
                    value=True,
                    key=f"auto_recent_{index}_{key_suffix}",
                ):
                    selected_recent_context.append(history_context)
                prior = history_context["prior_summary"]
                if prior:
                    st.caption(f"上次结果（仅作参考）：{prior}")
        else:
            st.caption("近三天还没有可自动带入的历史便签。")

recognized_data = (
    st.session_state.get("current_vision_result")
    if detail_mode != "最简易"
    else None
)
recognized = VisionResult.model_validate(recognized_data) if recognized_data else None
query_item = query_item.strip()
event_question = event_question.strip()
event_note = event_note.strip()
submitted_subject = query_item or event_note or event_question

if not event_question:
    st.info("先填写“这次想确认什么”，才能召唤分析。")

analysis_context = {
    "detail_mode": detail_mode,
    "selection_mode": "automatic" if detail_mode == "最简易" else "user_controlled",
    "current_query": {
        "question": event_question,
        "event_note": event_note,
    },
    "supplement": {
        "included": bool(recognized and use_image_context),
        "recognized_item": recognized.item_name if recognized else "",
        "normalized_name": recognized.normalized_name if recognized else "",
        "description": recognized.description if recognized else "",
        "user_subject": query_item,
    },
    "profile": {
        "included": use_profile_context,
        "name": profile.name,
        "species": profile.species,
        "sex": profile.sex,
        "age_years": profile.age_years,
        "weight_kg": profile.weight_kg,
        "notes": profile.notes if use_profile_context else "",
    },
    "recent_events": selected_recent_context,
}

with st.container(border=True):
    st.markdown("### 召唤前确认")
    preview_items = [("当次查询", "必用" if event_question else "待填写",
                      event_question or "还没有问题", False)]
    if detail_mode != "最简易":
        preview_items.append((
            "补充材料",
            "已选" if recognized and use_image_context else "未选",
            recognized.item_name if recognized and use_image_context else "可不添加图片",
            not bool(recognized and use_image_context),
        ))
    if detail_mode == "详尽展开":
        preview_items.append((
            "长期画像",
            "已选" if use_profile_context else "仅保留物种",
            f"{profile.species} · {profile.name}",
            not use_profile_context,
        ))
    if detail_mode != "最简易":
        preview_items.append((
            "近期事件",
            f"{len(selected_recent_context)} 条已选",
            "用户重点 + 近三天历史" if selected_recent_context else "暂时没有",
            False,
        ))
    preview_cols = st.columns(len(preview_items))
    for preview_col, (title, status, body, muted) in zip(preview_cols, preview_items):
        with preview_col:
            _render_context_tile(title, status, body, muted=muted)

analysis_label = "✨ 召唤分析"
if st.button(analysis_label, type="primary", use_container_width=True, disabled=not bool(event_question)):
    final_item = submitted_subject
    vision_for_analysis = recognized if recognized and use_image_context else None
    with st.spinner("正在按已选上下文分析……"):
        result = evaluate_item(
            final_item,
            analysis_profile,
            vision_result=vision_for_analysis,
            image_hash=st.session_state.get("current_vision_fingerprint") if vision_for_analysis else None,
            event_note=event_note,
            question=event_question,
            recent_context=selected_recent_context,
        )
        event = save_event(
            result,
            profile,
            input_text=final_item,
            event_note=event_note,
            question=event_question,
            recognized_item=recognized.item_name if recognized else final_item,
            final_item=final_item,
            user_corrected=bool(recognized and final_item != recognized.item_name),
            image_attached=bool(recognized),
            analysis_context=analysis_context,
        )
    st.session_state["latest_result"] = result.model_dump()
    st.session_state["latest_event"] = event.model_dump(exclude={"result", "profile"})

if "latest_result" in st.session_state:
    from app.models import SafetyResult
    result = SafetyResult.model_validate(st.session_state["latest_result"])
    evidence_labels = {
        "verified_local": "本地资料已验证", "mixed": "本地资料 + AI 推断",
        "general_inference": "AI 一般性推断", "insufficient": "信息不足",
    }
    st.subheader("本次事件的分析结果")
    latest_event = st.session_state.get("latest_event") or {}
    st.caption(f"事件分析 · {latest_event.get('created_at', '刚刚')}")
    saved_context = latest_event.get("analysis_context") or {}
    with st.expander("查看本次实际使用的上下文"):
        saved_mode = saved_context.get("detail_mode", "未记录")
        selected_contexts = saved_context.get("recent_events") or []
        st.caption(f"展开程度：{saved_mode} · 近期上下文：{len(selected_contexts)} 条")
        if saved_context.get("profile", {}).get("included"):
            st.write(f"- 长期画像：{saved_context['profile'].get('species', '宠物')} · {saved_context['profile'].get('name', '未命名')}")
        supplement = saved_context.get("supplement", {})
        if supplement.get("included"):
            st.write(f"- 图片材料：{supplement.get('recognized_item') or '已识别图片'}")
        for item in selected_contexts:
            label = item.get("label") or item.get("event_note") or item.get("question") or item.get("subject") or "近期记录"
            st.write(f"- 近期记录：{label}")
    st.markdown(f"<div class='risk-card'><b>{result.risk_level}</b> · 置信度 {result.confidence}%<br><h3>{result.normalized_item}</h3>{result.quick_summary}</div>", unsafe_allow_html=True)
    st.caption(f"证据等级：{evidence_labels[result.evidence_level]} · 类别：{result.item_category}")
    if result.evidence_level == "general_inference":
        st.info("此结果主要来自模型一般性推断，尚未经过 PetLens 已验证资料或外部权威资料验证。")
    if result.analysis_error:
        st.warning(result.analysis_error)
    st.write(" ".join(f"`{tag}`" for tag in result.tags[:5]))
    if result.recommended_actions:
        st.subheader("关键行动建议")
        for action in result.recommended_actions[:3]:
            st.write(f"- {action}")

    evidence_numbers = {item.evidence_id: number for number, item in enumerate(result.evidence, 1)}
    with st.expander("展开详细判断"):
        st.markdown("#### 结构化结论")
        for claim in result.claims:
            refs = "".join(f"[{evidence_numbers[eid]}]" for eid in claim.evidence_ids if eid in evidence_numbers)
            st.markdown(f"- {claim.text} <sup>{refs}</sup>", unsafe_allow_html=True)
        st.plotly_chart(radar_chart(result.scores), use_container_width=True, config={"displayModeBar": False})
        st.markdown("#### 详细说明")
        st.write(result.detailed_explanation)
        if result.exceptions:
            st.markdown("#### 例外情况")
            for exception in result.exceptions:
                st.write(f"- {exception}")
        if result.recommended_actions:
            st.markdown("#### 完整建议")
            for action in result.recommended_actions:
                st.write(f"- {action}")
        if result.emergency_signs:
            st.markdown("#### 紧急症状")
            for sign in result.emergency_signs:
                st.write(f"- {sign}")

    source_type_labels = {
        "verified_database": "PetLens 已验证资料", "trusted_web": "权威网络资料",
        "model_inference": "模型一般性推断", "vision_observation": "图片观察结果",
        "user_input": "用户确认信息",
    }
    with st.expander("查看证据来源"):
        for number, evidence in enumerate(result.evidence, 1):
            st.markdown(f"**[{number}] {source_type_labels[evidence.source_type]}**")
            if evidence.organization:
                st.write(f"机构：{evidence.organization}")
            if evidence.title:
                st.write(f"标题：{evidence.title}")
            if evidence.url:
                st.markdown(f"URL：[{evidence.url}]({evidence.url})")
            if evidence.source_type == "model_inference":
                st.caption("无外部资料验证")
            elif evidence.source_type == "vision_observation":
                st.caption("仅来自图片识别，不代表宠物安全事实")

    with st.expander("查看原始 JSON"):
        safe_result = sanitize_export(result)
        st.json(safe_result)
        st.download_button("下载 JSON", export_json(result), file_name="petlens-result.json",
                           mime="application/json", use_container_width=True)

    st.caption(result.disclaimer)

    result_home, result_continue = st.columns(2)
    with result_home:
        if st.button("返回小猫的家", key="result_back_home", use_container_width=True):
            navigate("home")
    with result_continue:
        if st.button("继续查询", key="result_continue", use_container_width=True):
            continue_query()

st.divider()
with st.expander("长期历史（只查看，不进入本次分析）"):
    history = list_history()
    if not history:
        st.caption("还没有查询记录。")
    for row in history:
        st.write(f"{row['species']} · **{row['item_name']}** · {row['risk_level']} · {row['confidence']}%")
