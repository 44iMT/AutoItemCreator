"""
向量搜索工具：自然语言 → 向量检索 → 重排 → 返回结果
"""
import time

import httpx

from config import (
    embed_model, qdrant_client, COLLECTION_NAME,
    SILICONFLOW_KEY, RERANK_MODEL, RERANK_API_URL, RERANK_MAX_RETRIES,
    tls12_client,
)


def _rerank(query: str, documents: list[str], limit: int) -> list[dict]:
    """BGE Reranker 二次打分，返回 [{"index": 2, "relevance_score": 0.98}, ...]"""
    last_error = None
    for attempt in range(RERANK_MAX_RETRIES + 1):
        try:
            resp = tls12_client.post(
                RERANK_API_URL,
                headers={
                    "Authorization": f"Bearer {SILICONFLOW_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": RERANK_MODEL,
                    "query": query,
                    "documents": documents,
                    "top_n": limit,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except httpx.TransportError as e:
            # SSL/连接/超时等传输层错误（含 TLS1.3 抖动）都值得退避重试
            last_error = e
            if attempt < RERANK_MAX_RETRIES:
                time.sleep(2 ** attempt)
        except httpx.HTTPStatusError:
            last_error = None
            if attempt < RERANK_MAX_RETRIES:
                time.sleep(2)

    print(f"  [rerank] 全部重试失败: {last_error}")
    return []


def search_products(query: str, limit: int, recall: int, rerank: bool) -> str:
    """
    用自然语言描述搜索总部商品库。
    向量检索 → （可选）重排 → 返回结果。

    参数:
        query:  搜索词。传品类/特征词，去掉"便宜的""好的"等口语化形容词。
                正确: '移动硬盘'、'燕之坊 心意薏仁米 410g/袋'、'德华 原味奶雪糕'
                错误: '有没有便宜的移动硬盘'
        limit:  最终返回给用户的数量。一般推荐 3-5 条，可按用户要求设置，最大50。
        recall: 从向量库粗检的候选数。必须 >= limit。一般按 limit 的 2-5 倍设置。
        rerank: 是否调用重排模型精排。默认开启，浏览模式可关闭。
    """
    print(f"[search] '{query}' limit: {limit} recall: {recall} rerank: {rerank}")
    # 1. 向量检索
    query_vector = embed_model.get_text_embedding(query)
    results = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=recall,
        with_payload=True,
    ).points

    if not results:
        print(f"[search] '{query}' 没找到匹配商品")
        return "没找到匹配商品"

    # 2. 排序：能重排就重排，没结果（未启用/候选不足/重试全败）就向量排序兜底
    sorted_results = []
    score_label = "相似度"
    if rerank and len(results) > limit:
        candidate_names = [r.payload["商品名称"] for r in results]
        reranked = _rerank(query, candidate_names, limit=limit)
        if reranked:
            sorted_results = reranked
            score_label = "重排分"
        else:
            print(f"[search] 重排失败，回退到向量排序")

    if not sorted_results:
        sorted_results = [{"index": i, "relevance_score": results[i].score}
                          for i in range(min(limit, len(results)))]

    # 3. 格式化输出
    lines = []
    for rank, rr in enumerate(sorted_results, 1):
        hit = results[rr["index"]]
        p = hit.payload
        score = rr.get("relevance_score", 0)
        fields = "\n".join(f"  {k}: {v}" for k, v in p.items())
        lines.append(f"[{rank}] {score_label}: {score:.3f}\n{fields}")

    mode = "重排" if rerank else "向量排序"
    print(f"[search] '{query}' → 粗排{len(results)}条 → {mode}{len(lines)}条")
    return "\n".join(lines)
