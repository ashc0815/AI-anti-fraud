"""配置管理模块 - 从 .env 文件读取配置项"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    """应用配置，从环境变量中读取"""

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    DB_PATH: str = os.getenv("DB_PATH", "concurshield.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DUPLICATE_HASH_THRESHOLD: int = int(os.getenv("DUPLICATE_HASH_THRESHOLD", "10"))
    RISK_SCORE_THRESHOLD: float = float(os.getenv("RISK_SCORE_THRESHOLD", "0.7"))


settings = Settings()
