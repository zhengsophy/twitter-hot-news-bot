import os
import json
from typing import Optional
from langchain.tools import tool
from coze_coding_dev_sdk import SearchClient
from coze_coding_utils.runtime_ctx.context import new_context, Context
from coze_coding_utils.log.write_log import request_context


@tool
def search_twitter_trending(query: str) -> str:
    """搜索Twitter上的热门话题和趋势信息，返回搜索结果摘要。输入查询关键词如'Twitter trending USA technology today'"""
    try:
        ctx = request_context.get() or new_context(method="search_twitter")
        client = SearchClient(ctx=ctx)

        # 搜索最近24小时的相关信息
        response = client.search(
            query=query,
            search_type="web",
            count=8,
            need_content=False,
            need_url=True,
            need_summary=True,
            time_range="1d",
        )

        if not response or not response.web_items:
            return f"【{query}】未找到相关结果。"

        results = []
        results.append(f"搜索关键词: {query}")
        results.append(f"找到 {len(response.web_items)} 条结果")
        if response.summary:
            results.append(f"摘要: {response.summary}")
        results.append("---")

        for i, item in enumerate(response.web_items, 1):
            title = item.title or "无标题"
            snippet = item.snippet or "无摘要"
            url = item.url or "无链接"
            results.append(f"{i}. {title}")
            results.append(f"   摘要: {snippet}")
            results.append(f"   链接: {url}")
            if item.publish_time:
                results.append(f"   时间: {item.publish_time}")
            results.append("")

        return "\n".join(results)

    except Exception as e:
        return f"搜索出错 ({query}): {str(e)}"