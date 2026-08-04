import streamlit as st
import pandas as pd

def render_config_panel():
    api = st.session_state.api_client

    st.markdown("### 🤖 AI 能力池管理")

    if st.button("🔄 刷新实例列表"):
        st.rerun()

    instances = api.get_ai_instances()
    if not instances:
        st.info("暂无 AI 实例，请添加")
        instances = []

    if instances:
        df = pd.DataFrame(instances)
        df = df[["id", "name", "model", "endpoint", "enabled", "tags", "cost_per_1k_tokens"]]
        st.dataframe(df, use_container_width=True)

    st.markdown("#### 操作")
    instance_ids = [i['id'] for i in instances]
    selected_for_action = st.selectbox("选择实例", [""] + instance_ids, key="action_select")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if st.button("➕ 添加"):
            st.session_state.editing_instance = None
            st.session_state.show_instance_form = True
    with col2:
        if st.button("✏️ 编辑"):
            if selected_for_action:
                inst = next((i for i in instances if i['id'] == selected_for_action), None)
                if inst:
                    st.session_state.editing_instance = inst
                    st.session_state.show_instance_form = True
            else:
                st.warning("请先选择一个实例")
    with col3:
        if st.button("🗑️ 删除"):
            if selected_for_action:
                api.delete_ai_instance(selected_for_action)
                st.success("已删除")
                st.rerun()
            else:
                st.warning("请先选择一个实例")
    with col4:
        if st.button("🔌 测试连接"):
            if selected_for_action:
                result = api.test_ai_instance(selected_for_action)
                if result:
                    if result.get("status") == "reachable":
                        st.success(f"✅ 连接成功 (HTTP {result['http_status']})")
                    else:
                        st.error(f"❌ 无法连接: {result.get('error')}")
                else:
                    st.error("测试请求失败")
            else:
                st.warning("请先选择一个实例")
    with col5:
        pass

    if st.session_state.get("show_instance_form"):
        with st.form("ai_instance_form"):
            edit = st.session_state.get("editing_instance")
            is_edit = edit is not None
            st.subheader("编辑实例" if is_edit else "添加实例")
            inst_id = st.text_input("ID", value=edit["id"] if is_edit else "", disabled=is_edit, help="唯一标识，不可修改")
            name = st.text_input("名称", value=edit["name"] if is_edit else "")
            endpoint = st.text_input("API 端点", value=edit["endpoint"] if is_edit else "http://localhost:11434")
            model = st.text_input("模型名 (如 openai/gpt-4, 可省略 openai/ 前缀)", value=edit["model"] if is_edit else "qwen2.5:7b")
            api_key = st.text_input("API Key", type="password", value=edit.get("api_key","") if is_edit else "", help="留空保持不变")
            tags_str = st.text_input("标签 (逗号分隔)", value=",".join(edit["tags"]) if is_edit else "")
            cost_per_m = st.number_input("每百万token成本 ($)", value=float(edit.get("cost_per_1k_tokens", 0.0)) * 1000 if is_edit else 0.0, min_value=0.0, step=0.001, format="%.6f")
            max_ctx = st.number_input("最大上下文长度", value=int(edit.get("max_context", 4096)) if is_edit else 4096)
            enabled = st.checkbox("启用", value=edit.get("enabled", True) if is_edit else True)
            temperature = st.slider("默认温度", 0.0, 1.0, value=float(edit.get("parameters", {}).get("temperature", 0.3)) if is_edit else 0.3)
            max_tokens = st.number_input("默认最大生成token", value=int(edit.get("parameters", {}).get("max_tokens", 4096)) if is_edit else 4096)

            submitted = st.form_submit_button("保存")
            if submitted:
                cost_per_1k = cost_per_m / 1000.0
                data = {
                    "id": inst_id,
                    "name": name,
                    "endpoint": endpoint,
                    "model": model,
                    "api_key": api_key if api_key else (edit.get("api_key","") if is_edit else ""),
                    "parameters": {"temperature": temperature, "max_tokens": max_tokens},
                    "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                    "cost_per_1k_tokens": cost_per_1k,
                    "max_context": max_ctx,
                    "enabled": enabled,
                }
                if is_edit:
                    resp = api.update_ai_instance(inst_id, data)
                else:
                    resp = api.create_ai_instance(data)
                if resp:
                    st.success("保存成功")
                    st.session_state.show_instance_form = False
                    st.rerun()
                else:
                    st.error("保存失败")
        if st.button("取消"):
            st.session_state.show_instance_form = False
            st.rerun()

    st.markdown("---")

    st.markdown("### 🎨 界面设置")
    themes = api._request("GET", "/api/themes") or {}
    theme_names = list(themes.keys()) if themes else ["catgirl", "programmer", "raw"]
    default_theme = st.selectbox("默认主题", options=theme_names, index=theme_names.index(st.session_state.get("theme_name", "catgirl")) if st.session_state.get("theme_name") in theme_names else 0)
    if default_theme != st.session_state.get("theme_name"):
        st.session_state.theme_name = default_theme
        api.update_config({"ui.theme": default_theme})

    default_view = st.selectbox("默认视图", ["styled", "raw"], index=0 if st.session_state.get("view_mode")=="styled" else 1)
    if default_view != st.session_state.get("view_mode"):
        st.session_state.view_mode = default_view
        api.update_config({"ui.default_view": default_view})
