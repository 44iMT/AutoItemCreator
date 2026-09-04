"""
全局配置模板。复制为 config.py 并填入真实值。
config.py 已在 .gitignore 中，不会被提交。
"""
import os
import ssl

import httpx
from llama_index.embeddings.openai import OpenAIEmbedding
from qdrant_client import QdrantClient

# ---- API Keys ----
SILICONFLOW_KEY = "sk-your-siliconflow-key"
DEEPSEEK_KEY = "sk-your-deepseek-key"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


# ---- TLS 1.2 强制降级（共用）----
# api.siliconflow.cn 线路在 TLS1.3 下有 BAD_RECORD_MAC 抖动，统一用一个 httpx 客户端降级：
# 嵌入模型（OpenAIEmbedding）与重排接口（tools/search.py）共用
def _tls12_httpx_client() -> httpx.Client:
    """构造强制 TLS 1.2 的 httpx 客户端。"""
    ctx = ssl.create_default_context()
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return httpx.Client(verify=ctx)


tls12_client = _tls12_httpx_client()

# ---- 嵌入模型（SiliconFlow 托管 BGE）----
embed_model = OpenAIEmbedding(
    model_name="BAAI/bge-large-zh-v1.5",
    api_key=SILICONFLOW_KEY,
    api_base="https://api.siliconflow.cn/v1",
    http_client=_tls12_httpx_client(),
)

# ---- 重排模型 ----
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_API_URL = "https://api.siliconflow.cn/v1/rerank"
RERANK_MAX_RETRIES = 3

# ---- 数据文件（web 类目页管理，目录即类型：category/通用、third_category/三方）----
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATEGORY_FILE = os.path.join(_BASE_DIR, "data", "category", "通用类目.csv")
THIRD_CATEGORY_FILE = os.path.join(_BASE_DIR, "data", "third_category", "第三方类目.csv")

# ---- Qdrant 连接 ----
COLLECTION_NAME = "总部商品"
VECTOR_DIM = 1024  # bge-large-zh-v1.5 输出维度

qdrant_client = QdrantClient(url="http://localhost:6333")
