import streamlit as st
import time
import os
from .components.chat import render_chat_view
from .components.dashboard import render_dashboard
from .components.config_panel import render_config_panel
from .components.style import inject_custom_css, get_theme
from .utils.api import APIClient
from .utils.ws import WebSocketClient, process_incoming_messages

st.set_page_config(page_title="俺寻思 AI 工厂", page_icon="🤖", layout="wide", initial_sidebar_state="expanded")
inject_custom_css()

api_host = os.environ.get("IRECKON_API_HOST", "localhost")
api_port = os.environ.get("IRECKON_API_PORT", "8000")
api_base = f"http://{api_host}:{api_port}"
ws_base = f"ws://{api_host}:{api_port}"

if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient(api_base)
if "ws_client" not in st.session_state:
    st.session_state.ws_client = WebSocketClient(ws_base)
if "current_task_id" not in st.session_state:
    st.session_state.current_task_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "theme_name" not in st.session_state:
    config = st.session_state.api_client._request("GET", "/api/config")
    st.session_state.theme_name = config.get("ui", {}).get("theme", "catgirl") if config else "catgirl"
if "view_mode" not in st.session_state:
    config = st.session_state.api_client._request("GET", "/api/config")
    st.session_state.view_mode = config.get("ui", {}).get("default_view", "styled") if config else "styled"
if "show_new_task" not in st.session_state:
    st.session_state.show_new_task = False
if "task_progress" not in st.session_state:
    st.session_state.task_progress = 0
if "task_status" not in st.session_state:
    st.session_state.task_status = ""
if "log_messages" not in st.session_state:
    st.session_state.log_messages = []
if "last_ws_rerun" not in st.session_state:
    st.session_state.last_ws_rerun = 0
if "last_reconnect_attempt" not in st.session_state:
    st.session_state.last_reconnect_attempt = 0
if "show_instance_form" not in st.session_state:
    st.session_state.show_instance_form = False
if "editing_instance" not in st.session_state:
    st.session_state.editing_instance = None
if "active_task_count" not in st.session_state:
    st.session_state.active_task_count = 0

with st.sidebar:
    st.title("🤖 俺寻思")
    st.caption("AI 工厂 v2.0")

    tasks = st.session_state.api_client.get_tasks()
    pending_tasks = [t for t in tasks if t["status"] in ("pending", "planning", "executing", "reviewing")]
    if pending_tasks:
        st.warning(f"有 {len(pending_tasks)} 个未完成任务，可尝试恢复。")
        for t in pending_tasks[:3]:
            c1, c2 = st.columns([4,1])
            with c1:
                st.write(f"📌 {t['task_id']}: {t['user_request'][:20]}...")
            with c2:
                if st.button("🔄", key=f"resume_{t['task_id']}"):
                    st.session_state.api_client._request("POST", f"/api/tasks/{t['task_id']}/resume")
                    st.success("已请求恢复")
                    st.rerun()

    st.subheader("📋 任务")
    task_options = {t["task_id"]: f"{t['user_request'][:30]}... ({t['status']})" for t in tasks}
    selected_task = st.selectbox("选择任务", options=list(task_options.keys()),
                                 format_func=lambda x: task_options[x],
                                 index=0 if task_options else None)
    if selected_task and selected_task != st.session_state.get("current_task_id"):
        st.session_state.current_task_id = selected_task
        api = st.session_state.api_client
        l1 = api.get_messages(selected_task, layer="L1")
        l3 = api.get_messages(selected_task, layer="L3")
        msgs = l1 + l3
        msgs.sort(key=lambda x: x.get("timestamp", ""))
        st.session_state.messages = msgs
        st.session_state.ws_client.connect(selected_task)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 新任务"):
            st.session_state.show_new_task = True
    with col2:
        if st.button("🔄 刷新"):
            st.rerun()

    if st.session_state.current_task_id:
        if st.button("⏹️ 撤销任务"):
            st.session_state.api_client._request("POST", f"/api/tasks/{st.session_state.current_task_id}/cancel")
            st.success("已请求撤销")

    with st.expander("⚙️ 配置中心", expanded=False):
        render_config_panel()

    new_theme = st.selectbox("🎨 风格", ["catgirl", "programmer", "raw"],
                             index=["catgirl","programmer","raw"].index(st.session_state.theme_name) if st.session_state.theme_name in ["catgirl","programmer","raw"] else 0)
    if new_theme != st.session_state.theme_name:
        st.session_state.theme_name = new_theme
        st.session_state.api_client.update_config({"ui.theme": new_theme})

if st.session_state.show_new_task:
    with st.form("new_task_form"):
        req = st.text_area("描述你的需求", height=100)
        if st.form_submit_button("启动任务") and req:
            resp = st.session_state.api_client.create_task(req)
            if resp:
                st.session_state.current_task_id = resp["task_id"]
                st.session_state.ws_client.connect(resp["task_id"])
                st.session_state.show_new_task = False
                st.rerun()
            else:
                st.error("创建失败")

tab1, tab2 = st.tabs(["💬 群聊广场", "📊 仪表盘"])
with tab1:
    if st.session_state.current_task_id:
        render_chat_view(st.session_state.current_task_id, st.session_state.messages,
                         get_theme(st.session_state.theme_name), st.session_state.view_mode,
                         st.session_state.api_client)
    else:
        st.info("选择或创建任务")
with tab2:
    if st.session_state.current_task_id:
        render_dashboard(st.session_state.current_task_id)
    else:
        st.info("选择或创建任务")

if process_incoming_messages():
    now = time.time()
    if now - st.session_state.last_ws_rerun >= 0.5:
        st.session_state.last_ws_rerun = now
        st.rerun()

if st.session_state.current_task_id:
    ws = st.session_state.ws_client
    if not ws.is_connected() and time.time() - st.session_state.last_reconnect_attempt > 5:
        ws.connect(st.session_state.current_task_id)
        st.session_state.last_reconnect_attempt = time.time()