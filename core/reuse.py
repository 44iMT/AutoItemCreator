"""
结果复用缓存：Qdrant 单存储、双模式检索。

条目 = 一个 point：
  payload = {精确键字段(清洗后), 向量字段(原文), "out": LLM 原始输出}
  vector  = 向量字段拼接文本的 BGE 嵌入（未配向量字段则不带向量，仅供精确层检索）

铁规（改动前先想清楚）：
- key 只取行的内容字段，绝不掺行号/批次/文件名——续传的命根是同一行重跑出同一个 key
- 精确键任一为空的行跳过精确层（空串不能当 key，否则空键行互相"命中"）
- 只存 Agent 真跑出来的 out；缓存命中的行不回写（避免相似误判固化成精确事实）
- 查/存双向 best-effort：缓存故障降级为走 Agent，不拖死批处理
- 存与查共用同一个拼接/清洗函数，杜绝两侧拼法漂移
"""
import uuid

from qdrant_client.models import (
    Distance, VectorParams, PayloadSchemaType,
    Filter, FieldCondition, MatchValue, PointStruct,
)

from config import embed_model, qdrant_client, VECTOR_DIM

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "autoitemcreator.reuse")


def _value(row, field):
    """行内字段取值：缺失/NaN/None/空串统一为 ''。"""
    v = row.get(field, "")
    s = "" if v is None else str(v).strip()
    return "" if s in ("", "nan", "None") else s


def _clean(s):
    """精确键清洗：去 Excel 浮点尾巴 .0（同 core/builder.py 的做法）。"""
    return s[:-2] if s.endswith(".0") else s


class ReuseCache:
    def __init__(self, cfg: dict):
        self.collection = cfg["collection"]
        self.exact_fields = list(cfg.get("exact_fields") or [])
        self.vector_fields = list(cfg.get("vector_fields") or [])
        self.threshold = cfg.get("vector_threshold")
        rebuild = bool(cfg.get("rebuild", False))

        if not self.exact_fields and not self.vector_fields:
            raise ValueError("reuse 开了但没给 exact_fields / vector_fields，条目写进去也永远查不出来")
        if self.vector_fields and self.threshold is None:
            # 阈值是业务决策不是技术参数，逼着任务作者亲手定（同工具"不给默认值"的原则）
            raise ValueError("开了 vector_fields 就必须给 vector_threshold，不提供默认值")

        exists = qdrant_client.collection_exists(self.collection)
        rebuilt = False
        if exists and rebuild:
            qdrant_client.delete_collection(self.collection)
            exists, rebuilt = False, True
        if not exists:
            qdrant_client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
        # 精确键走 keyword 索引 + MatchValue 精确等值，不吃全文分词的模糊性
        for f in self.exact_fields:
            qdrant_client.create_payload_index(
                collection_name=self.collection,
                field_name=f,
                field_schema=PayloadSchemaType.KEYWORD,
            )

        layers = []
        if self.exact_fields:
            layers.append("精确(" + "+".join(self.exact_fields) + ")")
        if self.vector_fields:
            layers.append(f"向量({'+'.join(self.vector_fields)} @ {self.threshold})")
        print(f"[reuse] collection '{self.collection}' 就绪: {', '.join(layers)}"
              + ("（已删库重建）" if rebuilt else ""))

    # ── 检索键 ──────────────────────────────        ─
    def _exact_key(self, row):
        """全部精确键非空 → {字段: 清洗值}；任一为空 → None（该行精确层不可用）。"""
        keys = {f: _clean(_value(row, f)) for f in self.exact_fields}
        return keys if all(keys.values()) else None

    def _vector_text(self, row):
        """向量层文本：按配置顺序拼接字段值。存与查共用，两侧拼法永不漂移。"""
        return " ".join(_value(row, f) for f in self.vector_fields).strip()

    # ── 查 ──────────────────────────────        ─
    def lookup(self, row):
        """精确 → 向量依次查。返回 (out, 来源标签)，未命中 (None, None)。best-effort。"""
        # 1) 精确层：等值匹配，命中即复用
        if self.exact_fields:
            key = self._exact_key(row)
            if key:
                try:
                    hits, _ = qdrant_client.scroll(
                        collection_name=self.collection,
                        scroll_filter=Filter(must=[
                            FieldCondition(key=f, match=MatchValue(value=v))
                            for f, v in key.items()
                        ]),
                        limit=1,
                        with_payload=True,
                    )
                    if hits:
                        return hits[0].payload.get("out", {}), "精确缓存"
                except Exception as e:
                    print(f"  [reuse] 精确层查询失败，跳过: {e}")

        # 2) 向量层：拼接文本嵌入，最高分过阈值才复用
        if self.vector_fields:
            text = self._vector_text(row)
            if text:
                try:
                    vec = embed_model.get_text_embedding(text)
                    points = qdrant_client.query_points(
                        collection_name=self.collection,
                        query=vec,
                        limit=1,
                        with_payload=True,
                    ).points
                    if points:
                        best = points[0]
                        if best.score >= self.threshold:
                            return best.payload.get("out", {}), f"向量缓存 {best.score:.2f}"
                        # 未达标的最高分打出来，调阈值时看分布用
                        print(f"  [reuse] 向量未达标: '{text[:30]}' 最高 {best.score:.2f} < {self.threshold}")
                except Exception as e:
                    print(f"  [reuse] 向量层查询失败，跳过: {e}")

        return None, None

    # ── 存 ──────────────────────────────        ─
    def store(self, row, out):
        """Agent 成功后写入（内部吞异常，绝不影响主流程）。无任何可检索键的行不存。"""
        try:
            key = self._exact_key(row) if self.exact_fields else None
            text = self._vector_text(row) if self.vector_fields else ""
            # 点 id 确定性生成：同 key 重跑覆盖同一点，天然去重
            identity = "|".join(key.values()) if key else text
            if not identity:
                return
            vec = embed_model.get_text_embedding(text) if text else None
            payload = {"out": out}
            payload.update(key or {})
            payload.update({f: _value(row, f) for f in self.vector_fields})
            qdrant_client.upsert(
                collection_name=self.collection,
                points=[PointStruct(
                    id=uuid.uuid5(_NAMESPACE, identity),
                    vector=vec,
                    payload=payload,
                )],
            )
        except Exception as e:
            print(f"  [reuse] 写入缓存失败（忽略）: {e}")
