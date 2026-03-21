"""pytest 配置 — 初始化数据库 & 生成测试图片。"""

import subprocess
import sys

import pytest

from concurshield.db import store


@pytest.fixture(autouse=True, scope="session")
def _init_db_and_clean():
    """确保 SQLite 表存在，并在测试前清空历史数据避免干扰。"""
    store.init_db()
    conn = store._get_conn()
    try:
        conn.execute("DELETE FROM receipts")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True, scope="session")
def _generate_test_images():
    """如果缺少合成图片，自动生成。"""
    subprocess.run(
        [sys.executable, "scripts/generate_test_images.py"],
        check=True,
    )
