import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import build_agent, run_excel_task
from tools import search_products, search_by_barcode, web_search, get_third_categories


INPUT_FILE = r"C:\Users\Administrator\Desktop\测试集.xlsx"
OUTPUT_FILE = r"C:\Users\Administrator\Desktop\测试集-分类结果.xlsx"
CONCURRENCY = 4
RETRY_TIMES = 3

COLUMNS_MAP = {
    "商品编码": "商品编码",
    "商品条码": "商品条码",
    "商品名称": "商品名称",
}
OUT_COLUMNS = {
    "前台类目": "根据范本和搜索生成的前台类目",
    "类目建议": "建议增添的前台类目名称",
}

agent = build_agent(
    [search_products, search_by_barcode, web_search],
    system_prompt=f"""
    你是商超商品标准化专家。门店商品前台类目缺失，请参考总部范本搜索进行标准化。

    请通过总部商品的类目信息或联网搜索， 从三方类目中选择最符合的含有二级的类目，

    如果三方类目完全无法归类时，就在原三方类目一级类目的基础上生成一个你认为合适的类目放在 类目建议 中吧，

    三方类目已直接附在下方参考区：

    {get_third_categories()}

    返回的字段结果都采用字符串类型的

    只输出 JSON，不要 markdown 包裹。
    """,
)

run_excel_task(
    agent,
    input_file=INPUT_FILE,
    output_file=OUTPUT_FILE,
    columns_map=COLUMNS_MAP,
    out_columns=OUT_COLUMNS,
    concurrency=CONCURRENCY,
    retry_times=RETRY_TIMES,
    include_input=True,                   # 只输出结果列
    display_key="商品名称",
    display_out_key="类目建议",
    log_tag="ReCategory",
)