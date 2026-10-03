# -*- coding: utf-8 -*-
"""
第 3 步：建向量库（已改为转调 app/ingestion/indexer.py）
=============================================

【这个文件为什么变了】

  旧版这里用的是：
        PyPDFLoader("datasheets/xxx.pdf")   +   RecursiveCharacterTextSplitter
  也就是"直接读原始 PDF 再切块"——
  它完全绕过了 P0/P1 辛苦清洗出来的表格和正文，而且切块会把表格切碎。

  实测后果：vectorstore/ 里只有一个 4 个向量的旧库（内容还是示例 txt），
  问答链路拿它回答 STM32 的问题，答案自然不靠谱。

  现在真正的建库逻辑在 app/ingestion/indexer.py（读 data/chunks_v2/**/chunks.jsonl 入库）。
  这个文件保留下来只做一件事：把旧命令转接过去，让你原来的习惯不失效。

运行方法（两种都可以，效果完全一样）：
    python -m backend.app.ingestion.indexer
    python backend/legacy/step3_vectorstore.py

想先空跑看看库里会装什么（不调接口、不花钱）：
    python -m backend.app.ingestion.indexer --dry-run
"""

import sys
from pathlib import Path

# 让这个脚本无论从哪个目录运行，都能 import 到同目录下的 p1_2_index
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

from backend.app.ingestion.indexer import main as build_index   # noqa: E402


if __name__ == "__main__":
    print("[提示] 建库逻辑已移到 -m backend.app.ingestion.indexer，"
          "本脚本自动转接过去（数据源：data/chunks_v2/**/chunks.jsonl）")
    print()
    build_index()
