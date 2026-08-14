# -*- coding: utf-8 -*-
"""为融合引擎全部 .py 脚本的英文函数名插入中文功能注释。

规则：
  - 注释统一为 `# [中文功能] <说明>`，放在 def 上方一行，缩进与 def 对齐；
  - 只新增注释行，不改动任何代码；
  - 幂等：已存在相同注释则跳过；
  - 保留原文件编码（含BOM）与换行符。

用法：python insert_comments.py [--restore]
  --restore：删除全部已插入的 `# [中文功能] ...` 注释行（恢复原文件）。
"""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mapping import MAP  # noqa: E402

ROOTS = {
    "fusion": pathlib.Path(
        r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts"
    ),
    "core": pathlib.Path(
        r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts"
    ),
}
PREFIX = "# [中文功能] "


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def build_func_lines(src: str):
    """返回 {函数名: (行号1基, 缩进列)}。"""
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, []).append((node.lineno, node.col_offset))
    return out


def restore_all() -> int:
    removed = 0
    for root in ROOTS.values():
        for p in root.glob("*.py"):
            raw = p.read_bytes()
            has_bom = raw.startswith(b"\xef\xbb\xbf")
            text = raw.decode("utf-8-sig")
            nl = detect_newline(text)
            kept = [
                line
                for line in text.splitlines()
                if not line.strip().startswith(PREFIX.rstrip())
            ]
            if len(kept) != len(text.splitlines()):
                removed += len(text.splitlines()) - len(kept)
                new_text = nl.join(kept)
                if not new_text.endswith(nl):
                    new_text += nl
                p.write_bytes((("\ufeff" if has_bom else "") + new_text).encode("utf-8"))
    return removed


def main() -> None:
    if "--restore" in sys.argv:
        print(f"已恢复原始文件，删除注释 {restore_all()} 条")
        return
    total_inserted = 0
    warnings = []
    for fname, entries in MAP.items():
        target = None
        for key, root in ROOTS.items():
            p = root / fname
            if not p.exists():
                continue
            target = (key, p)
            break
        if target is None:
            warnings.append(f"文件不存在于任何根目录: {fname}")
            continue
        key, p = target
        raw = p.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        nl = detect_newline(text)
        lines = text.splitlines()
        func_lines = build_func_lines(text)
        notes = dict(entries)
        # 收集全部插入点，按行号倒序处理：先插靠后的函数，避免前面的插入
        # 使后面函数的 def 行号漂移（正序插入会把注释插进函数体）。
        insertions = []
        for func, positions in func_lines.items():
            note = notes.pop(func, None)
            if note is None:
                warnings.append(f"[{key}/{fname}] 未收录函数: {func}")
                continue
            for lineno, col in positions:
                insertions.append((lineno, col, PREFIX + note))
        for lineno, col, comment in sorted(insertions, reverse=True):
            idx = lineno - 1
            # 幂等：跳过空行向上找最近非空行，已有相同注释则跳过
            k = idx - 1
            while k >= 0 and lines[k].strip() == "":
                k -= 1
            if k >= 0 and lines[k].strip() == comment:
                continue
            indent = " " * col
            lines.insert(idx, indent + comment)
            total_inserted += 1
        if notes:
            for func in notes:
                warnings.append(f"[{key}/{fname}] 映射存在但代码中无此函数: {func}")
        new_text = nl.join(lines)
        if not new_text.endswith(nl):
            new_text += nl
        new_bytes = ("\ufeff" if has_bom else "") + new_text
        p.write_bytes(new_bytes.encode("utf-8"))
    print(f"已插入注释 {total_inserted} 条")
    if warnings:
        print("警告：")
        for w in warnings:
            print("  " + w)


if __name__ == "__main__":
    main()
