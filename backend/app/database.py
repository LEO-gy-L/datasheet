# -*- coding: utf-8 -*-
"""
数据库连接（SQLAlchemy 2.x）
============================
现状：**已备好，但还没接进接口**。
      `main.py` 现在没有 import 本文件 —— 故意的：你还没建表，接上去只会多一个空文件。
      等要做"文档记录 / 问答日志 / 用户登录"时再来用，本文件不用改。

三个概念，记住就够：

    engine        引擎     —— 管理连接池，回答"连到哪个库、怎么连"
    SessionLocal  会话工厂 —— 每次请求开一个会话，回答"这一轮对话"
    Base          表基类   —— 你写的每张表都继承它，Base.metadata 记录全部表结构

为什么要有 SessionLocal 而不是一个全局 session：
    Session **不是线程安全的**。FastAPI 每个请求可能跑在不同线程上，
    共用同一个 session 会让两个请求看到对方未提交的数据，或者干脆报错。
    正确做法：每个请求开一个、用完就关 —— 就是下面 get_db() 干的活。

SQLite / MySQL / PostgreSQL 的区别只在 config.DATABASE_URL 那一行，代码完全一样。
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.config import DATABASE_URL

# echo=True 会把执行的每条 SQL 打印到终端 —— 调试建表时很有用，平时保持 False。
# 注意：create_engine **不会立刻连接数据库**，只是准备好连接池；
# 真正连上去是第一次执行 SQL 的时候（所以 import 本文件没有任何副作用）。
engine = create_engine(DATABASE_URL, echo=False, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    继承它写出来的类，SQLAlchemy 才能知道"这是数据库里的一张表"。
    """


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求开一个会话，请求结束（哪怕是抛异常）自动关闭。

    以后写 CRUD 接口时这样用：

        from fastapi import Depends
        from sqlalchemy.orm import Session
        from backend.app.database import get_db

        @router.get("/documents")
        def list_documents(db: Session = Depends(get_db)):
            return db.query(Document).all()

    yield 的妙处：这行之后是"请求结束"才执行的部分，
    所以即使接口里抛了异常，finally 里的 db.close() 也一定会跑到，不会漏连接。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（表还不存在就创建；已存在的表不动）。

    这是最朴素的建表方式。等表结构开始改、库里有真实数据了，就该换 Alembic：
    Alembic 像 Git 一样管理每次表结构变更，能生成"升级/回滚"脚本 ——
    否则你直接改模型字段，SQLite 会悄悄忽略掉，或者丢数据。

    用法（把模型都定义好之后跑一次）：
        python -c "from backend.app.database import init_db; init_db()"
    """
    # 在函数内 import：确保 models 里的表类都注册到 Base.metadata 之后才建表
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
