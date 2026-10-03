# -*- coding: utf-8 -*-
"""
入库层：PDF -> 干净的文本/表格 -> 切块 -> 向量库
================================================
这是**离线管线**，和"用户提问"那条线上没有交集 —— 跑一次，结果存磁盘，
问答时只读结果。所以它们被放在单独的包、单独的目录里。

执行顺序（每一步的输出就是下一步的输入）：

    1. tables.py      PDF -> data/tables_v5/<手册名>/page_*.md     表格页
    2. text.py        PDF -> data/text_v2/<手册名>/page_*.md       正文页
    3. figures.py     PDF -> 框图的结构化文本（用时再跑，不进主链路）
    4. chunking.py    tables_v5 + text_v2 -> data/chunks_v2/<手册名>/chunks.jsonl
    5. indexer.py     chunks.jsonl -> vectorstore/（FAISS 索引）

以后新增的两个脚本也放这里（CH32F103 中文手册）：
    table_struct.py   按坐标重建表格网格 + 处理合并单元格
                      （中文手册有双线边框，会被 find_tables() 认成 14 列的碎片）
    cn_clean.py       中文文本清洗：汉字间的排版空格、竖排表头的 <br>

为什么这五个不放在 scripts/ 里：
    scripts/ 是"你手动敲一次、看个结果"的工具（评测、诊断、选型对比）；
    这里五个是**生产管线的组成部分**，以后要做"前端上传 PDF 自动入库"时，
    接口直接 import 这里的函数就行，不用去 shell 里调脚本。
"""
