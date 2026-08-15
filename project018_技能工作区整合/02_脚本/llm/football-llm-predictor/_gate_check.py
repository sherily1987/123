
import sys, json
from pathlib import Path
# 2026-08-16：工程已迁入仓库，改用自身所在目录，不再硬编码 C 盘
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import predict
files = json.loads(sys.argv[1])
for fn, kickoff in files.items():
    p = str(HERE / "data" / "evidence_2026-08-15" / fn)
    text = open(p, encoding="utf-8").read()
    try:
        r = predict.assess_evidence(text, kickoff=kickoff, now="2026-08-15T11:00:00+08:00")
        print(fn, "=>", json.dumps(r, ensure_ascii=False))
    except Exception as e:
        print(fn, "ERROR", repr(e))
