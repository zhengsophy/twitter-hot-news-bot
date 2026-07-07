#!/usr/bin/env python3
"""
每日Twitter热门信息推送脚本
用于GitHub Actions定时触发，也可在本地直接运行
"""
import os
import sys
import json
import datetime
import logging
import requests
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# 配置：从环境变量读取
# ============================================================
# LLM 配置（OpenAI兼容接口）
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "doubao-seed-2-0-lite-260215")

# 飞书配置
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_RECEIVE_ID = os.environ.get("FEISHU_RECEIVE_ID", "")
FEISHU_RECEIVE_ID_TYPE = os.environ.get("FEISHU_RECEIVE_ID_TYPE", "open_id")

# 模式：yesterday(昨日回顾) / today(今日实时)
MODE = os.environ.get("MODE", "today")

# 搜索配置
SEARCH_QUERIES = {
    "yesterday": {
        "美国_技术": "twitter trending USA technology yesterday",
        "美国_股市": "twitter trending USA stock market yesterday",
        "韩国_技术": "twitter trending Korea technology yesterday",
        "韩国_股市": "twitter trending Korea stock market yesterday",
        "中国_技术": "twitter trending China technology yesterday",
        "中国_股市": "twitter trending China stock market yesterday",
    },
    "today": {
        "美国_技术": "twitter trending USA technology today",
        "美国_股市": "twitter trending USA stock market today",
        "韩国_技术": "twitter trending Korea technology today",
        "韩国_股市": "twitter trending Korea stock market today",
        "中国_技术": "twitter trending China technology today",
        "中国_股市": "twitter trending China stock market today",
    },
}

SEARCH_COUNTRIES = {
    "美国_技术": ("🇺🇸", "美国", "技术/科技"),
    "美国_股市": ("🇺🇸", "美国", "股市/金融"),
    "韩国_技术": ("🇰🇷", "韩国", "技术/科技"),
    "韩国_股市": ("🇰🇷", "韩国", "股市/金融"),
    "中国_技术": ("🇨🇳", "中国", "技术/科技"),
    "中国_股市": ("🇨🇳", "中国", "股市/金融"),
}


# ============================================================
# 搜索功能
# ============================================================
def search_news(query: str) -> list[dict]:
    """使用搜索引擎搜索信息，返回结果列表"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }
    url = "https://www.bing.com/search"
    params = {"q": query, "count": 8}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"搜索失败 ({query}): {e}")
        return []

    # 解析搜索结果
    results = []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select("li.b_algo"):
            title_el = item.select_one("h2 a")
            snippet_el = item.select_one(".b_caption p")
            if title_el:
                results.append({
                    "title": title_el.get_text(strip=True),
                    "url": title_el.get("href", ""),
                    "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                })
    except ImportError:
        # 没有BeautifulSoup时用简单正则
        import re
        for match in re.finditer(
            r'<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            resp.text, re.DOTALL
        ):
            results.append({
                "title": re.sub(r"<[^>]+>", "", match.group(2)).strip(),
                "url": match.group(1),
                "snippet": "",
            })
    except Exception as e:
        logger.warning(f"解析搜索结果失败: {e}")

    return results[:8]


# ============================================================
# LLM 分类翻译
# ============================================================
def analyze_with_llm(all_results: dict) -> str:
    """使用LLM对搜索结果进行分类、整理和翻译，返回Markdown格式报告"""
    if not LLM_API_KEY or not LLM_BASE_URL:
        logger.warning("未配置LLM，使用模板方式生成报告")
        return _build_template_report(all_results)

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        logger.warning("langchain-openai 未安装，使用模板方式生成报告")
        return _build_template_report(all_results)

    # 构建LLM输入
    today_str = _get_date_str()
    mode_label = "昨日" if MODE == "yesterday" else "今日"

    # 将搜索结果拼成文本
    search_text = ""
    for key, results in all_results.items():
        emoji, country, category = SEARCH_COUNTRIES.get(key, ("", key, ""))
        search_text += f"\n## {emoji} {country} - {category}\n"
        for i, r in enumerate(results, 1):
            search_text += f"{i}. {r['title']}\n   {r['snippet'][:200]}\n   链接: {r['url']}\n"

    system_prompt = """你是一个专业的信息整理与翻译助手。你的任务是将搜索到的英文/韩文/中文信息整理成中文日报。

要求：
1. 按国家(美国/韩国/中国)和类别(技术/股市)分类整理
2. 将每条信息翻译成中文，保留原文链接
3. 每条信息用一句话概括核心要点（不超过50字）
4. 输出格式为Markdown，使用 ## 标题、**粗体**、[链接](url) 等格式
5. 内容精炼，每类3-5条即可
6. 报告开头标注日期和模式（昨日回顾/今日实时）"""

    try:
        llm = ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=0.3,
            timeout=120,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"请整理以下 {today_str} 的{mode_label}热门信息，翻译成中文日报：\n\n{search_text}"),
        ]
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        logger.error(f"LLM调用失败: {e}")
        return _build_template_report(all_results)


def _build_template_report(all_results: dict) -> str:
    """模板方式生成报告（当LLM不可用时的降级方案）"""
    today_str = _get_date_str()
    mode_label = "昨日回顾" if MODE == "yesterday" else "今日实时"
    lines = [f"**📅 {today_str}（{mode_label}）**\n"]

    for key in ["美国_技术", "美国_股市", "韩国_技术", "韩国_股市", "中国_技术", "中国_股市"]:
        results = all_results.get(key, [])
        emoji, country, category = SEARCH_COUNTRIES.get(key, ("", "", ""))
        if not results:
            continue

        lines.append(f"\n## {emoji} {country} - {category}")
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "").strip()[:80]
            url = r.get("url", "")
            snippet = r.get("snippet", "").strip()[:100]
            if title:
                link_text = f"[查看详情]({url})" if url else ""
                snippet_text = f" — {snippet}" if snippet else ""
                lines.append(f"{i}. **{title}**{snippet_text} {link_text}")

    return "\n".join(lines)


def _get_date_str() -> str:
    """获取报告的日期字符串"""
    today = datetime.date.today()
    if MODE == "yesterday":
        yesterday = today - datetime.timedelta(days=1)
        return yesterday.strftime("%Y年%m月%d日")
    return today.strftime("%Y年%m月%d日")


# ============================================================
# 飞书推送
# ============================================================
def _get_feishu_token() -> str:
    """获取飞书tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json; charset=utf-8"},
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    result = resp.json()
    if result.get("code") != 0:
        raise Exception(f"获取飞书token失败: {result.get('msg', '未知错误')}")
    return result["tenant_access_token"]


def _build_card(title: str, body_md: str) -> str:
    """构建飞书interactive卡片消息"""
    MAX_DIV = 3000
    elements = []
    sections = []
    current = []
    for line in body_md.split("\n"):
        if line.strip().startswith("##"):
            if current:
                sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    for i, sec in enumerate(sections):
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) > MAX_DIV:
            for j in range(0, len(sec), MAX_DIV):
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": sec[j:j+MAX_DIV].strip()}})
        else:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": sec}})
        if i < len(sections) - 1:
            elements.append({"tag": "hr"})

    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "⏰ 每日08:00推送昨日回顾 · 17:00推送今日实时 · 数据来源：Twitter / 网络搜索"}]
    })

    card = {
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
        "elements": elements,
    }
    return json.dumps(card, ensure_ascii=False)


def send_feishu(title: str, content_md: str) -> str:
    """推送消息到飞书"""
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_RECEIVE_ID]):
        return "❌ 飞书配置不完整，请检查环境变量 FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_RECEIVE_ID"

    token = _get_feishu_token()
    card_content = _build_card(title, content_md)

    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={FEISHU_RECEIVE_ID_TYPE}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    payload = {"receive_id": FEISHU_RECEIVE_ID, "msg_type": "interactive", "content": card_content}

    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    result = resp.json()
    if result.get("code") == 0:
        msg_id = result.get("data", {}).get("message_id", "")
        logger.info(f"飞书推送成功: {msg_id}")
        return f"✅ 推送成功！消息ID: {msg_id}"
    else:
        return f"❌ 推送失败: {result.get('msg', '未知错误')}"


# ============================================================
# 主流程
# ============================================================
def main():
    logger.info(f"🚀 开始执行 - 模式: {MODE}")

    # 1. 搜索6个维度的信息
    queries = SEARCH_QUERIES.get(MODE, SEARCH_QUERIES["today"])
    all_results = {}
    for key, query in queries.items():
        logger.info(f"🔍 搜索: {key} ({query})")
        results = search_news(query)
        all_results[key] = results
        logger.info(f"   找到 {len(results)} 条结果")

    # 2. LLM分类翻译整理
    logger.info("🤖 正在整理和翻译...")
    report = analyze_with_llm(all_results)

    # 3. 生成标题
    today_str = _get_date_str()
    mode_label = "昨日回顾" if MODE == "yesterday" else "今日实时"
    title = f"🌐 Twitter热门信息日报（{today_str}）"
    logger.info(f"📋 标题: {title}")

    # 4. 推送飞书
    logger.info("📤 正在推送飞书...")
    result = send_feishu(title, report)
    logger.info(f"📬 {result}")


if __name__ == "__main__":
    main()