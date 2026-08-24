"""
网页搜索工具：通过 DeepSeek 内置联网搜索获取信息
"""
from config import DEEPSEEK_KEY, DEEPSEEK_BASE_URL
from openai import OpenAI


_client = OpenAI(
    api_key=DEEPSEEK_KEY,
    base_url=DEEPSEEK_BASE_URL
)


def web_search(query: str, max_results: int) -> str:
    """
    在互联网上搜索信息，返回最新网页内容。适用于查询商品信息、市场价格、资讯等。

    参数:
        query:       搜索关键词，越具体越好。
                     正确: '阿里山茉莉花爆珠 价格'、'乐芙娜 商品规格'
                     错误: '查一下这个是什么'
        max_results: 最多返回几条结果，推荐 3-5 条
    """
    print(f"[web_search] '{query}' max: {max_results}")
    response = _client.responses.create(
        model="deepseek-v4-flash",
        input=f"你是网页搜索助手。请搜索并总结与查询相关的最新信息。"
              f"返回最多 {max_results} 条结果，每条包含标题和摘要。"
              f"用户查询：{query}",
        tools=[{"type": "web_search"}],
        extra_body={
            "search_context_size": "high"  # 可选，控制搜索上下文
        }
    )
    content = response.output_text
    print(f"[web_search] '{query}' → 完成")
    return content
