# -*- coding: utf-8 -*-
"""由 mapping.py 生成全局函数映射档案 references/function_map.md。

输出两份：
  1) 技能套件内 canonical：football-quant-fusion/references/function_map.md
  2) 项目交付副本：project006/05_交付/function_map.md
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mapping import MAP  # noqa: E402

FUSION_REF = pathlib.Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\references\function_map.md"
)
PROJECT_COPY = pathlib.Path(
    r"H:\claude AI自媒体\project006_融合引擎全功能测试\05_交付\function_map.md"
)

HEADER = """# 函数映射档案（英文函数名 → 中文功能）

> 全局统一管理本文件：新增/修改函数时，先更新 `project006_融合引擎全功能测试/02_脚本/mapping.py`，
> 再运行 `insert_comments.py`（同步代码内注释）与 `gen_map_doc.py`（重新生成本档案），保持两处一致。

## 注释约定

- 代码内统一格式：`# [中文功能] <说明>`，放在 `def` 上方一行，缩进与 def 对齐。
- 本档案按脚本归档：`文件 → 函数 → 中文功能`。
- 覆盖范围：football-quant-fusion 融合层 + zu-yu-dashi-3 核心引擎全部 `.py` 脚本。
- 只维护注释与说明，不改变任何代码逻辑。

"""


def render() -> str:
    out = [HEADER]
    for fname, entries in MAP.items():
        out.append(f"## {fname}\n")
        if not entries:
            out.append("（加载器/无自定义函数）\n")
            continue
        out.append("| 函数名 | 中文功能 |")
        out.append("| --- | --- |")
        for func, note in entries:
            out.append(f"| `{func}` | {note} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    doc = render()
    for p in (FUSION_REF, PROJECT_COPY):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")
        print(f"已生成 {p}")


if __name__ == "__main__":
    main()
