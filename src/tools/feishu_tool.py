import os
import json
import requests
import time
import logging
from typing import Optional
from langchain.tools import tool
from coze_coding_utils.runtime_ctx.context import new_context
from coze_coding_utils.log.write_log import request_context

logger = logging.getLogger(__name__)

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"

# 单个lark_md div的内容长度限制，超长时拆分到多个div
MAX_DIV_LENGTH = 3000


def _get_feishu_config() -> dict:
    """读取飞书配置（优先从环境变量，回退到配置文件）"""
    app_id = os.environ.get("FEISHU_APP_ID") or ""
    app_secret = os.environ.get("FEISHU_APP_SECRET") or ""
    receive_id = os.environ.get("FEISHU_RECEIVE_ID") or ""
    receive_id_type = os.environ.get("FEISHU_RECEIVE_ID_TYPE") or "open_id"

    # 如果环境变量缺失，尝试从配置文件读取
    if not app_id or not app_secret:
        workspace_path = os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects")
        config_path = os.path.join(workspace_path, "assets/feishu_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            app_id = cfg.get("app_id", app_id)
            app_secret = cfg.get("app_secret", app_secret)
            receive_id = cfg.get("receive_id", receive_id)
            receive_id_type = cfg.get("receive_id_type", receive_id_type)

    if not app_id or not app_secret:
        raise ValueError(
            "飞书配置缺失，请设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
        )

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "receive_id": receive_id,
        "receive_id_type": receive_id_type,
    }


def _get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """获取飞书tenant_access_token"""
    url = f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {"app_id": app_id, "app_secret": app_secret}

    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    result = resp.json()

    if result.get("code") != 0:
        raise Exception(f"获取飞书token失败: {result.get('msg', '未知错误')}")

    return result.get("tenant_access_token", "")


def _build_card_content(title: str, body_markdown: str) -> str:
    """将Markdown日报内容转换为飞书interactive卡片消息的content JSON字符串"""
    # 按国家/分类拆分段落（按 ## 或 ### 标题分割）
    sections = []
    current_section = []
    lines = body_markdown.strip().split("\n")

    for line in lines:
        stripped = line.strip()
        # 检测是否为二级/三级标题（国家/分类标题）
        if stripped.startswith("##") or stripped.startswith("###"):
            if current_section:
                sections.append("\n".join(current_section))
            current_section = [line]
        elif stripped.startswith("---"):
            # 分隔线跳过，作为视觉分隔
            continue
        else:
            current_section.append(line)

    if current_section:
        sections.append("\n".join(current_section))

    # 构建卡片elements
    elements = []

    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue

        # 添加小标题作为粗体头部（如果有）
        first_line = section.split("\n")[0].strip() if section else ""

        if len(section) > MAX_DIV_LENGTH:
            # 内容太长时拆分为多个div
            chunks = []
            current_chunk = ""
            for sec_line in section.split("\n"):
                if len(current_chunk) + len(sec_line) > MAX_DIV_LENGTH:
                    chunks.append(current_chunk)
                    current_chunk = sec_line
                else:
                    current_chunk += "\n" + sec_line if current_chunk else sec_line
            if current_chunk:
                chunks.append(current_chunk)
            for chunk in chunks:
                elements.append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": chunk.strip()
                    }
                })
        else:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": section
                }
            })

        # 在段落之间添加细分隔（除了最后一个）
        if i < len(sections) - 1:
            elements.append({"tag": "hr"})

    # 底部添加note
    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": "⏰ 每日08:00推送昨日热门 · 数据来源：Twitter / 网络搜索"}
        ]
    })

    card = {
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title
            },
            "template": "blue"
        },
        "elements": elements
    }

    return json.dumps(card, ensure_ascii=False)


@tool
def send_feishu_message(title: str, content: str) -> str:
    """发送格式化消息到飞书。输入title为消息标题，content为消息正文（Markdown格式，支持标题、粗体、列表、链接等Markdown语法）。"""
    try:
        cfg = _get_feishu_config()
        receive_id = cfg.get("receive_id", "")
        receive_id_type = cfg.get("receive_id_type", "open_id")

        if not receive_id:
            return (
                "⚠️ 飞书消息发送失败：未配置接收方(receive_id)。\n"
                "请先在 assets/feishu_config.json 中配置 receive_id（接收方ID）和 receive_id_type（如 open_id / chat_id）。\n"
                "例如：\n"
                "  - 发给用户：receive_id=\"ou_xxxxx\", receive_id_type=\"open_id\"\n"
                "  - 发给群聊：receive_id=\"oc_xxxxx\", receive_id_type=\"chat_id\""
            )

        # 获取token
        token = _get_tenant_access_token(cfg["app_id"], cfg["app_secret"])

        # 构建交互式卡片消息
        card_content = _build_card_content(title, content)

        # 发送消息（receive_id_type 作为 query 参数）
        url = f"{FEISHU_BASE_URL}/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": card_content,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            message_id = result.get("data", {}).get("message_id", "")
            logger.info(f"飞书消息发送成功，message_id: {message_id}")
            return f"✅ 飞书消息发送成功！消息ID: {message_id}"
        else:
            error_msg = result.get("msg", "未知错误")
            logger.error(f"飞书消息发送失败: {error_msg}")
            return f"❌ 飞书消息发送失败: {error_msg}"

    except FileNotFoundError as e:
        return f"❌ {str(e)}"
    except ValueError as e:
        return f"❌ 配置错误: {str(e)}"
    except Exception as e:
        logger.error(f"飞书消息发送异常: {str(e)}")
        return f"❌ 飞书消息发送异常: {str(e)}"