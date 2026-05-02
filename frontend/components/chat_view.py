import streamlit as st
from datetime import datetime

def get_ai_name(api_client, agent_id):
    if "ai_names" not in st.session_state:
        try:
            instances = api_client.get_ai_instances()
            st.session_state.ai_names = {i["id"]: i["name"] for i in instances} if instances else {}
        except:
            st.session_state.ai_names = {}
    return st.session_state.ai_names.get(agent_id, agent_id[:8] if agent_id else "?")

def render_chat_view(task_id, messages, theme, view_mode, api_client=None):
    tab_l1, tab_l3 = st.tabs(["🏛️ 公共广场", "🔒 私人工作间 (L3)"])
    with tab_l1:
        _render_message_list([m for m in messages if m.get("layer") != "L3"], theme, view_mode, api_client)
        _render_input_box(task_id, api_client, layer="L1")
    with tab_l3:
        _render_message_list([m for m in messages if m.get("layer") == "L3"], theme, view_mode, api_client)
        st.caption("🤖 AI 之间的私聊，仅供查看")
    # 底部状态栏
    status = st.session_state.get("task_status", "")
    progress = st.session_state.get("task_progress", 0)
    if status:
        st.info(f"📡 当前状态：{status}  ({int(progress*100)}%)")
    else:
        st.caption("系统就绪，等待新任务...")

def _render_message_list(msgs, theme, view_mode, api_client):
    for msg in msgs:
        render_message(msg, theme, view_mode, api_client)

def render_message(msg, theme, view_mode, api_client):
    role = msg.get("sender_role", "system")
    content = msg["content"]
    timestamp = msg.get("timestamp", "")
    layer = msg.get("layer", "L1")
    sender_id = msg.get("sender_id", "")

    role_mapping = theme.get("role_mapping", {})
    role_info = role_mapping.get(role, {})
    avatar = role_info.get("avatar", "🤖" if role != "user" else "👤")
    base_name = role_info.get("name", role.capitalize() if role != "user" else "你")
    if sender_id and role != "user":
        ai_name = get_ai_name(api_client, sender_id)
        display_name = f"{base_name} ({ai_name})"
    else:
        display_name = base_name

    ts = ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            ts = dt.strftime("%H:%M:%S")
        except:
            ts = timestamp

    with st.chat_message(name=display_name, avatar=avatar):
        if layer == "L3":
            st.caption("🔒 私聊")
        st.markdown(content)
        if ts:
            st.caption(ts)

def _render_input_box(task_id, api_client, layer="L1"):
    c1, c2 = st.columns([6,1])
    with c1:
        inp = st.text_input("输入消息 (支持 @角色)", key=f"input_{layer}", label_visibility="collapsed")
    with c2:
        if st.button("发送", key=f"send_{layer}") and inp and api_client:
            api_client.send_message(task_id, inp, layer)
            st.rerun()