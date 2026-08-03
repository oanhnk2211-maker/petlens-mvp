from __future__ import annotations

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
from app.storage import init_db, list_history, save_result

load_dotenv()
init_db()

st.set_page_config(page_title="PetLens 宠物视角", page_icon="🐾", layout="centered")
st.markdown("""
<style>
.block-container {max-width: 760px; padding-top: 1.2rem; padding-bottom: 4rem;}
.hero {padding: 1.1rem 1.2rem; border-radius: 20px; background: linear-gradient(135deg,#f6f7ff,#fff7ee); margin-bottom: 1rem;}
.hero h1 {font-size: 2rem; margin: 0 0 .35rem 0;}
.hero p {margin: 0; opacity: .78;}
.risk-card {padding: 1rem 1.1rem; border: 1px solid rgba(120,120,120,.25); border-radius: 18px; margin: .5rem 0 1rem 0;}
.small-note {font-size: .86rem; opacity: .72;}
</style>
<div class="hero"><h1>🐾 PetLens</h1><p>从宠物视角判断：能吃吗、有毒吗、能玩吗、危险吗、会感兴趣吗？</p></div>
""", unsafe_allow_html=True)

status_bits = []
status_bits.append("百炼图片识别已配置" if os.getenv("DASHSCOPE_API_KEY") else "图片识别未配置（可手动输入）")
status_bits.append("百炼文本分析已配置" if os.getenv("DASHSCOPE_API_KEY") else "本地知识库模式")
st.caption(" · ".join(status_bits))

with st.expander("宠物画像", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        pet_name = st.text_input("名字", value="我家宝贝")
        species = st.selectbox("物种", ["猫", "狗", "兔子", "鸟", "其他"])
    with c2:
        age = st.number_input("年龄（岁，可选）", min_value=0.0, max_value=100.0, value=None, step=0.5)
        weight = st.number_input("体重（kg，可选）", min_value=0.0, max_value=500.0, value=None, step=0.1)
    notes = st.text_input("补充信息（过敏、幼宠、疾病等）", placeholder="例如：3个月幼猫、曾有肾病")

profile = PetProfile(
    name=pet_name or "我的宠物",
    species=species,
    age_years=age if age and age > 0 else None,
    weight_kg=weight if weight and weight > 0 else None,
    notes=notes,
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
            with st.spinner("正在识别图片中的主要物品…"):
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


query_item = ""
input_tab, camera_tab, upload_tab = st.tabs(["⌨️ 输入名称", "📷 直接拍照", "🖼️ 上传图片"])
with input_tab:
    query_item = st.text_input("输入物品", placeholder="例如：葡萄、百合、毛线、巧克力")
with camera_tab:
    camera_file = st.camera_input("拍下要查询的物品")
    if camera_file:
        recognize_uploaded_image(camera_file, "camera")
with upload_tab:
    upload_file = st.file_uploader("上传物品照片", type=["jpg", "jpeg", "png", "webp"])
    if upload_file:
        st.image(upload_file, use_container_width=True)
        recognize_uploaded_image(upload_file, "upload")

if st.session_state.get("vision_error"):
    st.error(st.session_state["vision_error"])
    st.caption("图片识别失败不影响查询，你仍可在上方“输入名称”中手动输入物品。")

recognized_data = st.session_state.get("current_vision_result")
if recognized_data:
    recognized = VisionResult.model_validate(recognized_data)
    st.subheader("图片识别结果")
    c1, c2 = st.columns(2)
    c1.metric("物品名称", recognized.item_name)
    c2.metric("置信度", f"{recognized.confidence:.0%}")
    st.write(f"**标准名称：** {recognized.normalized_name}")
    st.write(f"**客观描述：** {recognized.description or '无'}")
    st.write(f"**图片中的可见文字：** {'、'.join(recognized.visible_text) or '未识别到'}")
    st.write(f"**候选名称：** {'、'.join(recognized.candidate_names) or '无'}")
    st.write(f"**不确定性：** {recognized.uncertainty or '无'}")
    if recognized.confidence < 0.65:
        st.warning("识别置信度较低，请仔细核对并修改名称后再查询。")
    query_item = st.text_input("确认或修改物品名称", key="recognized_name_input")

if species not in ["猫", "狗"]:
    st.warning("当前高可信本地资料先覆盖猫和狗；其他物种可以运行，但会更多依赖一般性推断并降低置信度。")

analysis_label = "确认并查询" if recognized_data else "开始宠物视角分析"
if st.button(analysis_label, type="primary", use_container_width=True, disabled=not bool(query_item.strip())):
    final_item = query_item.strip()
    vision_for_analysis = VisionResult.model_validate(recognized_data) if recognized_data else None
    with st.spinner("正在结合宠物画像和知识库分析……"):
        result = evaluate_item(final_item, profile, vision_result=vision_for_analysis,
                               image_hash=st.session_state.get("current_vision_fingerprint"))
        save_result(result, profile)
    st.session_state["latest_result"] = result.model_dump()

if "latest_result" in st.session_state:
    from app.models import SafetyResult
    result = SafetyResult.model_validate(st.session_state["latest_result"])
    evidence_labels = {
        "verified_local": "本地资料已验证", "mixed": "本地资料 + AI 推断",
        "general_inference": "AI 一般性推断", "insufficient": "信息不足",
    }
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

st.divider()
with st.expander("最近查询"):
    history = list_history()
    if not history:
        st.caption("还没有查询记录。")
    for row in history:
        st.write(f"{row['species']} · **{row['item_name']}** · {row['risk_level']} · {row['confidence']}%")
