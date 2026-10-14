# -*- coding: utf-8 -*-
"""
数据表模型汇总
==============
这个文件看起来"只是几行 import"，但它是**必须存在的**，原因在 SQLAlchemy 的机制：

    Base.metadata.create_all() 是拿 `Base.metadata` 里登记的表来建表的。
    而一张表**只有在它的类被 import 执行过之后**，才会登记进去。

    也就是说：如果没人 import models/user.py，那么 User 类根本没被定义过，
    create_all() 会安安静静地建出一个空数据库 —— 不报错，但一张表都没有。
    这种"没报错但也没干活"的坑最难查。

所以约定：**加新表 = 新建 models/xxx.py + 来这里加一行 import**。
database.init_db() 里那句 `from backend.app import models` 就是靠这个文件把全部表带出来。
"""
from __future__ import annotations

from backend.app.models.document import Document
from backend.app.models.feedback import Feedback
from backend.app.models.qa_history import QaHistory
from backend.app.models.user import User

__all__ = ["User", "QaHistory", "Feedback", "Document"]
