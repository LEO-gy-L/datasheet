# -*- coding: utf-8 -*-
"""
数据层：数据库表（ORM 模型）
============================
**现在是空的** —— 你还没建表。

加一张表的完整步骤（三步）：

  1. 打开 backend/app/database.py，里面已经有 Base（表的基类），不用改

  2. 在本目录新建文件，例如 document.py：

        from sqlalchemy import Integer, String
        from sqlalchemy.orm import Mapped, mapped_column

        from backend.app.database import Base


        class Document(Base):
            __tablename__ = "documents"          # 数据库里真实表名

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            filename: Mapped[str] = mapped_column(String(255), index=True)
            pages: Mapped[int] = mapped_column(Integer, default=0)

  3. 在下面把 import 打开（放在文件底部，避免循环 import）

然后建表：
        python -c "from backend.app.database import init_db; init_db()"

为什么每张表都要有这个文件里 `__tablename__`：
    SQLAlchemy 默认拿类名转小写当表名（Document -> document），
    显式写出来更可控 —— 复数、下划线风格由你自己决定，改类名不会意外改表名。
"""

# 建好模型文件后，把下面这行打开：
# from backend.app.models.document import Document   # noqa: F401
