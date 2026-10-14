# -*- coding: utf-8 -*-
"""
documents 表 —— 库里有哪些手册、建到哪一步了
==============================================
这张表回答三个问题：

    ① 服务器上躺着哪些数据手册？（管理员「入库」页的表格）
    ② 哪几份已经进了向量库？（助理页那个 PDF 选择器的下拉项）
    ③ 正在建库的那份，卡在哪一步了？（进度条）

⚠️ 为什么 status 要有四个状态，而不是一个 is_indexed 布尔
--------------------------------------------------------
布尔只有两种取值，但真实过程有四种**语义完全不同**的情形：

    uploaded   已上传，但还没建库 —— 这是**正常待办**，不是错误
    indexing   正在建库 —— 这个过程要几十秒到十几分钟，必须能看见
    indexed    已入库 —— 可以被检索到
    failed     建库失败 —— 和 uploaded 长得像（都是"没入库"），但处理方式完全不同

为什么 failed 不能并进 uploaded：
    建库失败通常是**确定性**的原因（PDF 是扫描版没有文字层、文件损坏）。
    如果把 failed 降级成 uploaded，用户看到的是"未入库"，
    于是**再点一次建库**，再失败一次，反复烧钱。
    单独一个 failed 状态 + error 字段，才能把"再试一次有用"和
    "再试一次还是白搭"区分开。

⚠️ 为什么 stem 要唯一
--------------------------------------------------------
中间的每一道产物目录都是用 stem（去掉扩展名的文件名）命名的：

    data/text_v2/<stem>/          正文清洗结果
    data/tables_v5/<stem>/        表格清洗结果
    data/chunks_v2/<stem>/        切块结果

两份不同的 PDF 如果 stem 撞了（比如 a/手册.pdf 和 b/手册.pdf），
它们的清洗产物会写进**同一个目录**，后建的会把先建的覆盖掉，
而且不报任何错 —— 表现为"某份手册怎么搜都搜不到"。

所以让数据库自己把这条约束顶住（unique=True），
而不是指望上传时记得检查。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database import Base

# ---- 建库状态取值 ----
STATUS_UPLOADED = "uploaded"     # 已上传，未建库
STATUS_INDEXING = "indexing"     # 建库中
STATUS_INDEXED = "indexed"       # 已入库，可检索
STATUS_FAILED = "failed"         # 建库失败，见 error 字段

# ---- 建库流水线的四个阶段 ----
# 顺序是固定的：先抽出正文和表格，才有东西可切块；切完块才能向量化。
# 把这四步的**中文名**定义在这里，是为了让「当前阶段」这句话
# 只写一遍 —— 存库、给前端、打日志都用同一份文案，不会出现
# 后台说"切块中"、前端显示"正在处理"这种对不上的情况。
STAGES: list[tuple[str, str]] = [
    ("text",     "① 解析正文"),
    ("tables",   "② 解析表格"),
    ("chunking", "③ 切块"),
    ("indexing", "④ 向量化入库"),
]

# 每个阶段完成的百分比。四步各占 15/15/20/50 ——
# 权重不一样是因为耗时天差地别：向量化要调几百次 embedding 接口，
# 是整个流程里最慢的一段，给它一半的进度才符合"用户等了多久"的直觉。
# 进度条如果按"步数"平均分（25/25/25/25），会在最后一步卡住不动很久，
# 看着像死了。
STAGE_PROGRESS: dict[str, int] = {
    "text": 15,
    "tables": 30,
    "chunking": 50,
    "indexing": 100,
}


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 原始文件名，带扩展名："CH32F103_Datasheet_CN.pdf"
    # 用户看到的就是它，也是向量库 metadata.source 里存的那个值。
    name: Mapped[str] = mapped_column(String(255), index=True)

    # 去掉扩展名的文件名："CH32F103_Datasheet_CN"
    # 中间产物目录名、切块 id 前缀都用它。唯一约束就加在这里。
    stem: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    ext: Mapped[str] = mapped_column(String(16), default="pdf")   # 不带点的小写扩展名
    size: Mapped[int] = mapped_column(Integer, default=0)         # 字节

    status: Mapped[str] = mapped_column(String(16), default=STATUS_UPLOADED)

    # 当前阶段的**人话**描述，例如 "③ 切块"。
    # 为什么不直接存 stage 的英文 key 让前端翻译：
    #   前端多一份映射表就多一处会不同步的地方。后端把话说全，前端直接显示。
    stage: Mapped[str] = mapped_column(String(64), default="")

    # 0~100 的百分比，给进度条用。见 STAGE_PROGRESS 里的权重说明。
    progress: Mapped[int] = mapped_column(Integer, default=0)

    # 建库统计：PDF 页数、切出多少块（未入库时都是 0）
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)

    # 失败原因。用 Text 而不是 String(255)：
    #   pymupdf 的报错经常很长（带堆栈摘要、文件偏移），截断了反而看不出问题。
    error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 每次状态变化都刷新它 —— 前端靠它判断"这条是不是刚刚动过"
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now)
    # 可空：从没成功建过库就是 None
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Document id={self.id} stem={self.stem} status={self.status}>"
