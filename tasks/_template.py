# -*- coding: utf-8 -*-
"""
调用模板：基于 core 底座的任务写法
────────────────────────────────────────────
用法：把要跑的任务区块取消注释（每块以 # ── TASK: xxx ── 分隔），
     其余保持注释，直接 python tasks/_template.py 运行。
每个区块 = 原 tasks/ 对应文件的全部配置，参数原样搬入，没做改动。

也可以复制本文件改名，只留一个区块当独立任务用。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import build_agent, run_excel_task
from tools import search_products, search_by_barcode, web_search, get_categories

# ══════════════════════════════════════════════════════════════
# ── TASK: match_hq（门店商品是否在总部存在）────────────────────
# ══════════════════════════════════════════════════════════════
# INPUT_FILE = r"C:\Users\Administrator\Desktop\测试数据.xls"
# OUTPUT_FILE = r"C:\Users\Administrator\Desktop\匹配结果.xlsx"
# CONCURRENCY = 4      # 并发数
# RETRY_TIMES = 3      # 重试次数
#
# COLUMNS_MAP = {
#     "商品条码": "商品条码",
#     "商品名称": "商品名称",
#     "规格": "商品规格",
#     "所属分类": "所属分类",
#     "供应商": "供应商",
#     "进货价": "进货价",
#     "零售价": "零售价",
# }
# OUT_COLUMNS = {
#     "总部商品编码": "总部系统中的商品编码，未找到则为空字符串",
#     "总部商品名称": "总部系统中的商品名称，未找到则为空字符串",
#     "置信度": "匹配置信度，用百分数表示，如 95%",
#     "判定理由": "简要说明判断依据",
# }
#
# agent = build_agent(
#     [search_products, search_by_barcode, web_search],
#     system_prompt=r"""
#     你是电商商品查询助手,需要查询并判断门店商品是否是总部商品。
#     门店没有加入总部系统，商品命名和信息很不规范（可能缩写、错别字、口语化）。
#
#     ## 处理流程（每个品按以下步骤执行）
#     1. 先用 search_by_barcode 搜条码，总部有则直接认定是同一商品。
#     2. 条码没命中时，用 search_products 搜品名/货号，看总部是否有相似商品。
#     3. 还没找到就 web_search 联网搜该商品信息，再和总部商品比对。
#     4. 参考价格、规格等信息综合判断。
#
#     ## 输出要求
#     只输出 JSON，不要 markdown 包裹，不要任何解释文字。
#     """,
# )
#
# run_excel_task(
#     agent,
#     input_file=INPUT_FILE,
#     output_file=OUTPUT_FILE,
#     columns_map=COLUMNS_MAP,
#     out_columns=OUT_COLUMNS,
#     concurrency=CONCURRENCY,
#     retry_times=RETRY_TIMES,
#     include_input=True,                    # 原始列 + 结果列
#     prompt_prefix="判断这个门店商品是否在总部存在：",
#     display_key="商品名称",
#     display_out_key="判定理由",
#     log_tag="match",
# )

# ══════════════════════════════════════════════════════════════
# ── TASK: diff_hq（门店 vs 总部商品信息差异）────────────────────
# ══════════════════════════════════════════════════════════════
# INPUT_FILE = r"C:\Users\Administrator\Desktop\南磨房.xlsx"
# OUTPUT_FILE = r"C:\Users\Administrator\Desktop\南磨房差异结果.xlsx"
# CONCURRENCY = 4
# RETRY_TIMES = 3
#
# COLUMNS_MAP = {
#     "商品条码": "商品条码",
#     "商品名称": "商品名称",
#     "售卖规格": "售卖规格",
# }
# OUT_COLUMNS = {
#     "总部商品编码": "总部系统中的商品编码，未找到则为空字符串",
#     "总部商品名称": "总部系统中的商品名称，未找到则为空字符串",
#     "总部售卖规格": "总部系统中的售卖规格，未找到则为空字符串",
#     "相似程度": "商品信息相似程度，百分数表示，完全一样为100%",
#     "异常标记": "规格异常/无匹配/无",
#     "判定理由": "简要说明判定理由",
# }
#
# agent = build_agent(
#     [search_by_barcode],
#     system_prompt=r"""
#     你是电商商品查询助手,需要匹配商品条码判断门店商品与总部商品的信息差异
#
#     输入的商品条码有的是多个条码，用逗号隔开了，需要分开匹配
#
#     根据商品名称、商品规格判断门店与总部商品信息是否一致
#
#     主要问题在商品的售卖规格上，需要判断两个品商品规格是否一致
#     比如商品名称
#     门店： 娃哈哈 AD 钙 一瓶
#     总部： 娃哈哈 AD 钙 一排
#     一排是四瓶，像这种需要标记出来
#
#     如果只是量词不一样但是 物品数量，克重等核心规格一致就不用标记了
#
#     商品规格有时可能过于笼统无法判断，比如刚刚的两个品，商品规格可能都为 1个/份，所以需要结合判断
#
#     ## 输出要求
#     只输出 JSON，不要 markdown 包裹，不要任何解释文字。
#     """,
# )
#
# run_excel_task(
#     agent,
#     input_file=INPUT_FILE,
#     output_file=OUTPUT_FILE,
#     columns_map=COLUMNS_MAP,
#     out_columns=OUT_COLUMNS,
#     concurrency=CONCURRENCY,
#     retry_times=RETRY_TIMES,
#     include_input=True,                    # 原始列 + 结果列
#     display_key="商品名称",
#     display_out_key="判定理由",
#     log_tag="diff",
# )

# ══════════════════════════════════════════════════════════════
# ── TASK: rename_by_hq（参考总部范本标准化命名）─────────────────
# ══════════════════════════════════════════════════════════════
# INPUT_FILE = r"C:\Users\Administrator\Desktop\门店商品导出 (静海门店品).xlsx"
# OUTPUT_FILE = r"C:\Users\Administrator\Desktop\门店商品导出 (静海门店品)—重命名结果.xlsx"
# CONCURRENCY = 10
# RETRY_TIMES = 3
#
# COLUMNS_MAP = {
#     "商品编码": "商品编码",
#     "商品条码": "商品条码",
#     "商品名称": "商品名称",
#     "售卖规格": "商品规格",
#     # "所属分类": "所属分类",     # 原 task 里就是注释掉的，保留
#     # "供应商": "供应商",         # 同上
#     "单件成本价": "进货价",
#     "POS零售价(元)": "零售价",
# }
# OUT_COLUMNS = {
#     "商品编码": "商品编码",
#     "商品条码": "原商品条码",
#     "商品名称": "原商品名称",
#     "标准化商品名称": "标准化后的商品名称",
#     "售卖规格": "根据范本和搜索生成的售卖规格",
#     "前台类目": "根据范本和搜索生成的前台类目",
#     "商品重量": "根据范本和搜索生成的商品重量",
#     "重量单位": "根据范本和搜索生成的重量单位",
#     "基本单位": "根据范本和搜索生成的基本单位",
#     "范本商品": "范本商品",
# }
#
# agent = build_agent(
#     [search_products, search_by_barcode, web_search],
#     system_prompt=r"""
#     你是商超商品标准化专家。门店商品命名不规范，请参考总部范本和联网搜索进行标准化。
#
#     商品名称需要符合总部命名风格
#     其他字段像 售卖规格 商品重量 重量单位 基本单位 请结合范本和联网搜索填充
#
#     若商品条码精确匹配总部商品，直接使用总部商品信息填充，
#
#     最后再检查一下各字段是否符合上述要求，可以再次联网搜索，保证字段填充完整
#
#     商品编码有的是以@开头， 所以输出的商品编码也不要省略@， 输入和输出要保持一致
#
#     返回的字段结果都采用字符串类型的
#
#     只输出 JSON，不要 markdown 包裹。
#     """,
# )
#
# run_excel_task(
#     agent,
#     input_file=INPUT_FILE,
#     output_file=OUTPUT_FILE,
#     columns_map=COLUMNS_MAP,
#     out_columns=OUT_COLUMNS,
#     concurrency=CONCURRENCY,
#     retry_times=RETRY_TIMES,
#     include_input=False,                   # 只输出结果列
#     display_key="商品名称",
#     display_out_key="标准化商品名称",
#     log_tag="rename",
# )

# ══════════════════════════════════════════════════════════════
# ── TASK: category_by_hq（淘宝闪购渠道类目填充）─────────────────
# ══════════════════════════════════════════════════════════════
# INPUT_FILE = r"C:\Users\Administrator\Desktop\门店商品导出-待分类.xlsx"
# OUTPUT_FILE = r"C:\Users\Administrator\Desktop\门店商品导出-分类结果.xlsx"
# CONCURRENCY = 4
# RETRY_TIMES = 3
#
# COLUMNS_MAP = {
#     "商品编码": "商品编码",
#     "商品条码": "商品条码",
#     "商品名称": "商品名称",
# }
# OUT_COLUMNS = {
#     "商品编码": "商品编码",
#     "商品条码": "商品条码",
#     "商品名称": "商品名称",
#     "淘宝闪购渠道类目": "根据范本和搜索生成的淘宝闪购渠道类目",
# }
#
# agent = build_agent(
#     [search_products, search_by_barcode, get_categories],
#     system_prompt=r"""
#     你是商超商品标准化专家。门店商品淘宝闪购渠道类目缺失，请参考总部范本搜索进行标准化。
#
#     若商品条码精确匹配总部商品，直接使用总部商品 淘宝闪购渠道类目 信息填充，
#
#     淘宝闪购渠道类目 只需要填充一个符合的即可，不要放多个， 需要保证填充 类目编号和类目信息 与 参考完全一致 不要丢失或者混搭
#
#     返回的字段结果都采用字符串类型的
#
#     只输出 JSON，不要 markdown 包裹。
#     """,
# )
#
# run_excel_task(
#     agent,
#     input_file=INPUT_FILE,
#     output_file=OUTPUT_FILE,
#     columns_map=COLUMNS_MAP,
#     out_columns=OUT_COLUMNS,
#     concurrency=CONCURRENCY,
#     retry_times=RETRY_TIMES,
#     include_input=False,                   # 只输出结果列
#     display_key="商品名称",
#     display_out_key="淘宝闪购渠道类目",
#     log_tag="category",
# )

print("模板未启用：请取消注释要跑的任务区块（见 tasks/_template.py）")
