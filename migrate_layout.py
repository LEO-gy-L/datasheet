# -*- coding: utf-8 -*-
"""
一次性迁移脚本：把 backend/ 下平铺的 15 个脚本按职责分组到 app/ scripts/ legacy/
==============================================================================

它做什么（按顺序）：
  1. 建目录骨架 + 每个包一个 __init__.py
  2. 用 git mv 把 15 个文件搬到新位置并改成语义名（保留 git 历史）
  3. 新建 app/core/paths.py —— 全项目唯一的"项目根"定义处
  4. 替换代码：ROOT 改集中 import、删掉 sys.path 注入、同目录 import 改绝对导入
  5. 替换文档与提示文字：把已经失效的旧命令（backend\\p1_2_index.py 之类）更新成新写法
  6. 改 start_backend.bat 里的 uvicorn 目标

用法（在项目根目录，一行一行敲）：
    git add -A
    git commit -m "迁移到 app/ 布局前的快照"
    python migrate_layout.py

想全部回滚（会丢掉上面快照之后的所有改动）：
    git reset --hard HEAD~1

确认没问题后删掉本文件：
    Remove-Item migrate_layout.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"

# ---------------------------------------------------------------- 目录骨架
PACKAGES = [
    "app",
    "app/core",
    "app/api",
    "app/services",
    "app/retrieval",
    "app/generation",
    "app/ingestion",
    "scripts",
]

# ---------------------------------------------------------------- 搬家表
# (旧路径, 新路径)，都相对 backend/
MOVES = [
    ("api.py",                   "app/main.py"),
    ("rag_engine.py",            "app/services/rag_engine.py"),
    ("llm.py",                   "app/generation/llm.py"),
    ("p0_1_extract_tables.py",   "app/ingestion/tables.py"),
    ("p0_2_extract_text.py",     "app/ingestion/text.py"),
    ("chunk_loader.py",          "app/ingestion/chunking.py"),
    ("figure_extract.py",        "app/ingestion/figures.py"),
    ("p1_2_index.py",            "app/ingestion/indexer.py"),
    ("main.py",                  "scripts/chat.py"),
    ("app.py",                   "scripts/streamlit_app.py"),
    ("eval.py",                  "scripts/evaluate.py"),
    ("diag_crosslingual.py",     "scripts/diag_crosslingual.py"),
    ("p0_scan_quality.py",       "scripts/scan_quality.py"),
    ("p0_compare_pdfplumber.py", "scripts/compare_pdfplumber.py"),
    ("step3_vectorstore.py",     "legacy/step3_vectorstore.py"),
]

# ---------------------------------------------------------------- 代码替换
CODE_REPLACEMENTS = [
    # 同目录 import 改绝对导入
    ("from rag_engine import RAGEngine",
     "from backend.app.services.rag_engine import RAGEngine"),
    ("from p1_2_index import main as build_index",
     "from backend.app.ingestion.indexer import main as build_index"),
    # 项目根改为集中 import（带换行边界 = 只命中"独占整行"那句，不误伤文档说明）
    ("\nROOT = Path(__file__).resolve().parents[1]\n",
     "\nfrom backend.app.core.paths import ROOT\n"),
    # 删掉 sys.path 注入（改用 python -m 运行后不再需要）
    ("sys.path.insert(0, str(Path(__file__).resolve().parent))\n", ""),
]

# ---------------------------------------------------------------- 文档替换
DOC_REPLACEMENTS = [
    # uvicorn 目标
    ("uvicorn src.api:app", "uvicorn backend.app.main:app"),
    # 早已改名的历史遗留
    ("backend\\step4_rag.py", "-m backend.scripts.chat"),
]

# 由搬家表自动生成：
#   "backend\p1_2_index.py"  ->  "-m backend.app.ingestion.indexer"
#   同时覆盖单反斜杠与双反斜杠两种写法（不同作者写的风格不一致）
for _old, _new in MOVES:
    _mod = "backend." + _new[:-3].replace("/", ".")
    DOC_REPLACEMENTS.append((f"backend\\{_old}", f"-m {_mod}"))
    DOC_REPLACEMENTS.append((f"backend\\\\{_old}", f"-m {_mod}"))

# 去掉 .venv\Scripts\python 前缀：venv 已激活时 python 就够用，
# 顺带消掉 "\S" 这个无效转义序列（Python 3.12+ 会对此发 SyntaxWarning）
DOC_REPLACEMENTS.append((".venv\\Scripts\\python ", "python "))
DOC_REPLACEMENTS.append((".venv\\\\Scripts\\\\python ", "python "))

# 过时注释：目录结构描述已不再成立
NOTE_RE = re.compile(r"^#.*parents\[1\] = 项目根.*$", re.M)
NOTE_NEW = "# 项目根路径统一由 backend.app.core.paths 提供"

# ---------------------------------------------------------------- paths.py
PATHS_PY = '''# -*- coding: utf-8 -*-
"""全项目唯一的路径定义处。

为什么集中在这里：
    脚本一旦搬到更深的目录，Path(__file__).resolve().parents[N] 就算错了，
    而 N 是几完全取决于文件埋得多深 —— 这正是"重构完就烂掉"的根源。
    全项目只在这里数一次层数，其他地方一律：
        from backend.app.core.paths import ROOT
    以后目录再调整，也只有这一个文件需要改。
"""
from pathlib import Path

# 本文件在 backend/app/core/ 下：
#   parents[0] = app/core
#   parents[1] = app
#   parents[2] = backend
#   parents[3] = 项目根
ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = ROOT / "data"
STORE_DIR = ROOT / "vectorstore"
DATASHEETS_DIR = ROOT / "datasheets"
EVAL_DIR = ROOT / "eval"
ENV_FILE = ROOT / ".env"
'''

BAT_OLD = "uvicorn backend.api:app"
BAT_NEW = "uvicorn backend.app.main:app"


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def main() -> int:
    if (BACKEND / "app").exists():
        print("[中止] backend/app 已经存在，说明迁移过或跑到一半。")
        print("       请先人工确认当前状态，再决定是否继续。")
        return 1

    # ---------- 1. 目录骨架 ----------
    step(1, "创建目录骨架与 __init__.py")
    for pkg in PACKAGES:
        d = BACKEND / pkg
        d.mkdir(parents=True, exist_ok=True)
        init = d / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
            print(f"  + {init.relative_to(ROOT)}")
    (BACKEND / "legacy").mkdir(exist_ok=True)
    print("  + backend/legacy/")

    # ---------- 2. git mv ----------
    step(2, "移动文件（git mv，保留历史）")
    for old, new in MOVES:
        src, dst = BACKEND / old, BACKEND / new
        if not src.exists():
            print(f"  [警告] 找不到 {old}，跳过")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        cp = subprocess.run(
            ["git", "mv", str(src.relative_to(ROOT)), str(dst.relative_to(ROOT))],
            cwd=ROOT, capture_output=True, text=True,
        )
        if cp.returncode != 0:
            print(f"  [失败] {old} -> {new}")
            print("         " + (cp.stderr or "").strip())
            return 1
        print(f"  {old:<26} ->  {new}")

    # ---------- 3. paths.py ----------
    step(3, "新建 app/core/paths.py")
    paths_py = BACKEND / "app" / "core" / "paths.py"
    paths_py.write_text(PATHS_PY, encoding="utf-8")
    print(f"  + {paths_py.relative_to(ROOT)}")

    # ---------- 4 & 5. 代码与文档替换 ----------
    step(4, "替换代码与文档")
    targets = (sorted((BACKEND / "app").rglob("*.py"))
               + sorted((BACKEND / "scripts").rglob("*.py"))
               + sorted((BACKEND / "legacy").rglob("*.py")))
    n_code = n_doc = 0
    for f in targets:
        if f.name == "__init__.py":
            continue
        text = f.read_text(encoding="utf-8")
        original = text
        code_hits, doc_hits = [], []

        for old, new in CODE_REPLACEMENTS:
            if old in text:
                code_hits.append(old.strip().split("\n")[-1][:50])
                text = text.replace(old, new)

        for old, new in DOC_REPLACEMENTS:
            if old in text:
                doc_hits.append(old[:50])
                text = text.replace(old, new)

        new_text, n = NOTE_RE.subn(NOTE_NEW, text)
        if n:
            doc_hits.append(f"过时注释 x{n}")
            text = new_text

        # 文档里残留的 parents[1] 说法（独占整行的已在上面处理掉）
        if "ROOT = Path(__file__).resolve().parents[1]" in text:
            text = text.replace("ROOT = Path(__file__).resolve().parents[1]",
                                "ROOT（来自 backend.app.core.paths）")
            doc_hits.append("文档里的 parents[1] 说明")

        if text != original:
            f.write_text(text, encoding="utf-8")
            rel = f.relative_to(ROOT)
            print(f"  * {rel}")
            for h in code_hits:
                print(f"      [代码] {h}")
            for h in doc_hits:
                print(f"      [文档] {h}")
            n_code += bool(code_hits)
            n_doc += bool(doc_hits)
    print(f"  代码有改动的文件 {n_code} 个，文档有改动的文件 {n_doc} 个")

    # ---------- 6. start_backend.bat ----------
    step(5, "更新 start_backend.bat")
    bat = ROOT / "start_backend.bat"
    if bat.exists():
        t = bat.read_text(encoding="utf-8")
        if BAT_OLD in t:
            bat.write_text(t.replace(BAT_OLD, BAT_NEW), encoding="utf-8")
            print(f"  {BAT_OLD}  ->  {BAT_NEW}")
        elif BAT_NEW in t:
            print("  已经是新目标，无需改动")
        else:
            print(f"  [警告] 没找到 {BAT_OLD}，请手动检查")
    else:
        print("  [警告] 找不到 start_backend.bat")

    print("\n完成。请按顺序验证：")
    print('  1) python -c "from backend.app.core.paths import ROOT; print(ROOT)"')
    print("  2) python -m backend.app.ingestion.chunking --help")
    print("  3) python -W error::SyntaxWarning -m compileall -f -q backend")
    print("  4) 双击 start_backend.bat，看到 Uvicorn running 即成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
