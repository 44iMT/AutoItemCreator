"""
向量索引构建器：读取 Excel → 清洗 → 向量化 → 存入 Qdrant

"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from qdrant_client.models import Distance, VectorParams, PointStruct, PayloadSchemaType
from config import embed_model, qdrant_client, COLLECTION_NAME, VECTOR_DIM

# ═══════════════════════════════════════════════════
# 构建器专用配置
# ═══════════════════════════════════════════════════
BATCH_SIZE = 256

PATH = r"C:\Users\Administrator\Desktop\总部商品导出.xlsx"
HQ_FIELDS_MAP = {
    "商品编码": "商品编码",
    "商品条码": "商品条码",
    "商品名称": "商品名称",
    "总部前台类目名称": "前台类目名称",
    "后台叶子类目名称": "后台类目名称",
    "淘宝闪购渠道类目": "淘宝闪购渠道类目",
    "商品价格(元)": "商品价格",
    "售卖规格": "售卖规格",
    "商品重量": "商品重量",
    "库存单位": "基本单位",
    "重量单位": "重量单位",
}

# ═══════════════════════════════════════════════════
# 建库
# ═══════════════════════════════════════════════════
def build(excel_path: str):
    # 1. 读 Excel + 清洗（dtype=str 防条码被读成浮点数，如 6901234567890.0）
    df = pd.read_excel(excel_path, dtype=str)
    available = [k for k in HQ_FIELDS_MAP if k in df.columns]
    df = df[available].rename(columns=HQ_FIELDS_MAP)
    df = df.where(pd.notnull(df), "")  # NaN → ""，避免脏 null 进 payload
    for col in ("商品条码", "商品编码"):
        df[col] = (
            df[col].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        )
    print(f"[build] 读取 {excel_path}: {len(df)} 条, {len(available)} 字段")

    # 2. 重建集合
    if qdrant_client.collection_exists(COLLECTION_NAME):
        qdrant_client.delete_collection(COLLECTION_NAME)
    qdrant_client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )

    # 3. 分批嵌入 + 写入
    for start in range(0, len(df), BATCH_SIZE):
        end = min(start + BATCH_SIZE, len(df))
        batch = df.iloc[start:end]

        names = batch["商品名称"].tolist()
        vectors = embed_model.get_text_embedding_batch(names)

        points = [
            PointStruct(id=start + i, vector=vectors[i], payload=row.to_dict())
            for i, (_, row) in enumerate(batch.iterrows())
        ]
        qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f"  [{end}/{len(df)}]")

    # 4. 建 text 索引
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="商品条码",
        field_schema=PayloadSchemaType.TEXT,
    )
    print(f"[build] 完成，共 {len(df)} 条\n")

# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    build(PATH)
