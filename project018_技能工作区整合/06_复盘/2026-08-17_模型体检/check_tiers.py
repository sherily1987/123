# -*- coding: utf-8 -*-
import sys, collections, json
from pathlib import Path
p = Path(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练")
sys.path.insert(0, str(p / "02_脚本" / ".deps"))
sys.path.insert(0, str(p / "02_脚本"))
import predict_no_odds as pno
t = pno.league_tiers(p)
k0 = next(iter(t))
print("样例:", k0, "->", json.dumps(t[k0], ensure_ascii=False)[:300])
def tier_of(v):
    if isinstance(v, str): return v
    for key in ("tier", "grade", "label"):
        if key in v: return v[key]
    return str(v)
c = collections.Counter(tier_of(v) for v in t.values())
print("分档分布:", dict(sorted(c.items())))
print("联赛数:", len(t))
for k in sorted(t, key=lambda x: (tier_of(t[x]), x)):
    v = t[k]
    extra = ""
    if isinstance(v, dict):
        extra = " ".join("%s=%s" % (a, b) for a, b in v.items() if a not in ("tier","grade","label"))
    print("  %-5s %-34s %s" % (tier_of(v), k, extra[:90]))
