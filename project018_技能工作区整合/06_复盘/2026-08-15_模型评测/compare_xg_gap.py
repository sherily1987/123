import json
d = json.load(open(r"F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付\backtest_20260815_dixon_coles.json", encoding="utf-8"))
lg = d["leagues"]
for key in ("滚动+xG", "滚动（无"):
    rows = [v for v in lg.values()
            if v["config"].startswith(key)
            and isinstance(v.get("model_subset"), float)
            and isinstance(v.get("market"), float)]
    n = sum(v["n_subset"] for v in rows)
    m = sum(v["n_subset"] * v["model_subset"] for v in rows) / n
    mk = sum(v["n_subset"] * v["market"] for v in rows) / n
    print(key, "联赛数=", len(rows), "场次=", n,
          "模型=", round(m, 4), "市场=", round(mk, 4), "gap=", round(m - mk, 4))
