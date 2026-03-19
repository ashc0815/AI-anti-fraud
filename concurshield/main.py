"""ConcurShield - Streamlit 应用入口

启动方式：streamlit run concurshield/main.py
"""

import streamlit as st


def main() -> None:
    """Streamlit 应用主函数。"""
    st.set_page_config(page_title="ConcurShield", page_icon="🛡️", layout="wide")
    st.title("ConcurShield - AI 发票反欺诈系统")

    render_sidebar()
    render_upload_section()
    render_results_section()


def render_sidebar() -> None:
    """渲染侧边栏：配置项和历史记录。"""
    pass


def render_upload_section() -> None:
    """渲染发票上传区域。"""
    pass


def render_results_section() -> None:
    """渲染分析结果展示区域。"""
    pass


if __name__ == "__main__":
    main()
