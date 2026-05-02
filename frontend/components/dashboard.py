import streamlit as st
import psutil

def render_dashboard(task_id: str):
    st.subheader(f"任务 {task_id} 仪表盘")

    progress = st.session_state.get("task_progress", 0)
    status = st.session_state.get("task_status", "未知")
    st.progress(min(progress, 1.0), text=f"进度: {int(progress*100)}% - {status}")

    col1, col2, col3 = st.columns(3)
    col1.metric("CPU", f"{psutil.cpu_percent()}%")
    col2.metric("内存", f"{psutil.virtual_memory().percent}%")
    col3.metric("活跃任务", st.session_state.get("active_task_count", 0))

    st.subheader("实时日志")
    log_container = st.container()
    with log_container:
        logs = st.session_state.get("log_messages", [])
        if logs:
            for log in logs[-10:]:
                st.text(f"[{log.get('level', 'INFO')}] {log.get('message', '')}")
        else:
            st.text("暂无日志...")