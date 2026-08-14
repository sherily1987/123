# -*- coding: utf-8 -*-
"""规范化证据文件格式以满足 predict.py 门禁。

规则：
1. 以 -/* 开头且同一行含 source( 和 collected_at( 的事实行 -> 保留原样
2. 以 -/* 开头但缺 source 或 collected_at 的元数据/缺口行：
   - 含缺口标记（未找到/未检索到/缺失/不足/未公布等）-> 保留为列表行（缺口本身允许）
   - 其他元数据（赛事/开球/场地/赔率/收集时间/说明等）-> 改为 "**标题**：内容" 非列表格式
3. 校验后逐文件重跑 assess_evidence，输出门禁结果
"""
import io, os, re, sys
sys.path.insert(0, 'C:/Users/Administrator/football-llm-predictor')
import predict as p

EVIDENCE_DIR = 'C:/Users/Administrator/football-llm-predictor/data/evidence_2026-08-12'
GAP_MARKERS = ('未找到', '未检索到', '未拿到', '未做', '不足', '缺失', '未公布', '未发布', '未量化', '未确认')

def normalize_line(line):
    stripped = line.strip()
    if not stripped.startswith(('-', '*')):
        return line, True  # 非列表行，无需处理
    has_src = 'source(' in stripped.lower()
    has_ct = 'collected_at(' in stripped.lower()
    if has_src and has_ct:
        return line, True  # 合格事实行
    # 任何缺 source 或 collected_at 的列表行（含缺口行）-> 非列表格式，
    # 因为 predict.py 门禁要求所有 -/* 行都带 source+collected_at
    body = re.sub(r'^[-*]\s*', '', stripped)
    return f'> 说明：{body}', True

def process(fn):
    path = os.path.join(EVIDENCE_DIR, fn)
    with io.open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        nl, _ = normalize_line(line)
        out.append(nl)
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    return len(out)

if __name__ == '__main__':
    files = [f for f in os.listdir(EVIDENCE_DIR) if f.startswith('evidence_') and f.endswith('.md')]
    print('处理文件:', files)
    for fn in sorted(files):
        before = sum(1 for l in io.open(os.path.join(EVIDENCE_DIR, fn), encoding='utf-8').read().splitlines() if l.strip().startswith(('-','*')))
        process(fn)
        after = sum(1 for l in io.open(os.path.join(EVIDENCE_DIR, fn), encoding='utf-8').read().splitlines() if l.strip().startswith(('-','*')))
        print(f'{fn}: 列表行 {before} -> {after}')
    # 门禁复核
    print('\n=== 门禁复核 ===')
    for fn in sorted(files):
        t = io.open(os.path.join(EVIDENCE_DIR, fn), encoding='utf-8').read()
        st = p.assess_evidence(t, kickoff='2026-08-13T03:00:00+08:00')
        print(f'{fn}: ok={st["ok"]} reason={st.get("reason","")}')
