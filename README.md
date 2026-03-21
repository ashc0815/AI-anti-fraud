# ConcurShield

AI 驱动的发票反欺诈检测系统，使用 Claude Vision 多模态能力和多 Agent 架构，对报销发票进行全方位真伪审核。

## 功能概览

- **OCR 识别**：基于 Claude Vision 提取发票结构化信息
- **规则引擎**：预定义确定性规则（金额上限、周末交易、整数金额等）
- **重复检测**：基于感知哈希的相似发票检测
- **视觉取证**：检测图片篡改和 AI 生成痕迹
- **商户验证**：验证商户信息的真实性和一致性
- **元数据分析**：分析 EXIF 等文件元数据中的异常信号
- **复合评分**：综合所有模块结果输出风险等级和处理建议

## 项目结构

```
concurshield/
├── main.py                  # Streamlit 入口
├── config.py                # 配置管理
├── models/
│   └── schemas.py           # Pydantic v2 数据模型
├── engine/
│   ├── ocr.py               # Claude Vision OCR
│   ├── rules.py             # 确定性规则引擎
│   ├── hasher.py            # 感知哈希与重复检测
│   └── scorer.py            # 复合风险评分器
├── agents/
│   ├── main_agent.py        # Main Agent 编排器
│   ├── visual_forensics.py  # 视觉取证子 Agent
│   ├── merchant_verify.py   # 商户验证子 Agent
│   └── metadata_agent.py    # 元数据分析子 Agent
├── db/
│   └── store.py             # SQLite 存储层
├── utils/
│   └── audit_trail.py       # 审计轨迹记录器
└── tests/
    └── test_adversarial.py  # 对抗性测试用例
```

## 环境要求

- Python 3.10+
- Anthropic API Key

## 快速开始

```bash
# 1. 克隆项目
git clone <repo-url> && cd AI-anti-fraud

# 2. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 OPENAI_API_KEY

# 5. 启动应用
streamlit run concurshield/main.py
```

## 运行测试

```bash
pytest concurshield/tests/ -v
```

## 配置项

在 `.env` 文件中设置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API 密钥 | （必填） |
| `OPENAI_MODEL` | 使用的 OpenAI 模型 | `gpt-4o` |
| `DB_PATH` | SQLite 数据库路径 | `concurshield.db` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `DUPLICATE_HASH_THRESHOLD` | 重复检测哈希距离阈值 | `10` |
| `RISK_SCORE_THRESHOLD` | 风险得分告警阈值 | `0.7` |
