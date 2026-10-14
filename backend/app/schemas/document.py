# -*- coding: utf-8 -*-
"""
文档（数据手册）的数据契约
==========================
和 history / feedback 一样：**出参不用 response_model**，
由 service 层手工组装成 dict。

为什么这次连入参模型也很少：
    上传走的是 multipart/form-data（文件不是 JSON），FastAPI 用
    `UploadFile` 直接接，套一层 pydantic 模型反而别扭。
    剩下的入参只有一个 id 和一句话，没什么可校验的。

那这个文件还有必要存在吗？有 —— 它是**字段名的单一出处**。
前端 api/docs.js 里那几个字段（indexedAt / createdAt / progress …）
和这里必须逐字符一致，写在一起才方便一眼对照。
"""
from __future__ import annotations

from pydantic import BaseModel


class DocumentOut(BaseModel):
    """一份手册在列表里的样子（字段名与前端对齐，驼峰命名）。

    `indexed` 和 `status` 是**故意重复**的：
        status  给"懂的人"看，四个状态一字不差
        indexed 给表格那个「已入库」列看，它只需要一个布尔
    前端保留原来的 `indexed` 列渲染逻辑，就不用因为这次改造重写表格；
    以后要做"建库中"的转圈动画，就直接读 status。
    """

    id: int
    name: str
    size: int = 0
    type: str = "pdf"                 # 前端的列名就叫 type，值是不带点的扩展名
    indexed: bool = False             # status == "indexed" 的布尔投影
    status: str = "uploaded"          # uploaded / indexing / indexed / failed
    stage: str = ""                   # 当前阶段的人话描述
    progress: int = 0                 # 0~100
    pages: int = 0
    chunks: int = 0
    error: str = ""                   # 建库失败原因，成功时是空串
    createdAt: str = ""
    indexedAt: str | None = None


class DocOptionOut(BaseModel):
    """助理页 PDF 选择器的下拉项 —— 只包含**已入库**的手册。

    ⚠️ 为什么不复用 DocumentOut 直接给前端过滤：
        选择器只该拿到 `{ value, label }` 这两样东西。
        把 status / error / progress 一起发下去，前端就多了一堆
        "反正用不到"的字段；更要紧的是，将来谁顺手在下拉里
        渲染了那个字段，就等于把后台状态泄漏给了普通用户。
        接口的返回值就该是**调用方需要的最小集合**。

    value = 向量库 metadata.source 里存的那个文件名（带 .pdf），
    因为它就是 /api/ask 的 source 参数要传的值，中间不做任何映射。
    """
    value: str
    label: str
    chunks: int = 0
    pages: int = 0
