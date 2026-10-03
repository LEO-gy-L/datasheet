# -*- coding: utf-8 -*-
"""
依赖注入层
==========
"依赖"指的是：接口函数**需要**、但不该由它**自己创建**的共享对象。

FastAPI 用 `Depends(某函数)` 表达"先跑这个函数，把它的返回值当我的参数"：

    @router.post("/ask")
    def ask(engine: RAGEngine = Depends(engine_dependency)):
        ...

为什么要绕这一下，而不是在接口里直接 `RAGEngine()`：

    1. **性能**：向量库 + 嵌入模型 + 大模型客户端的初始化要几秒。
       每个请求新建一次 = 接口慢到不可用，内存里还堆一堆重复对象。

    2. **可测试**：测试时用 `app.dependency_overrides` 把 engine_dependency
       换成假引擎，就能不开向量库、不花 API 钱跑通接口。直接 new 就没法换。

现在有：
    engine.py   注入唯一的 RAGEngine

下一步（做登录/用户时）加：
    auth.py     从请求头解析 token、查出当前用户，接口里写
                `user: User = Depends(get_current_user)` 即可
"""
