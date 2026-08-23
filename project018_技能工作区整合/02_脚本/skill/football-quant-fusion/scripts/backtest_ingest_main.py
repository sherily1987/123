#!/usr/bin/env python3
"""接续主登记库预测到回测库。

默认只做 dry-run；--apply 才会复制预测快照并追加回测 registry。原主库不改写。
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fusion_record import append_jsonl, load_jsonl, sha
from runtime_paths import backtest_store, data_root


def _path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else Path.cwd() / p


def _result_ids(root: Path) -> set[str]:
    reg = root / "results_registry.jsonl"
    return {str(x.get("match_id")) for x in load_jsonl(reg) if x.get("match_id")}


def _select(source: Path, model_version: str, signature: str) -> list[tuple[dict, dict, Path]]:
    out = []
    for entry in load_jsonl(source / "registry.jsonl"):
        pid = str(entry.get("prediction_id") or "")
        if not pid:
            continue
        p = _path(entry.get("path", ""))
        if not p.exists():
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        model = rec.get("model") or {}
        if model.get("model_version") != model_version:
            continue
        if signature and model.get("probability_signature") != signature:
            continue
        if rec.get("prediction_id") != pid or rec.get("match_id") != entry.get("match_id"):
            raise ValueError(f"identity mismatch: {pid}")
        if entry.get("record_hash") and entry["record_hash"] != sha(rec):
            raise ValueError(f"record hash mismatch: {pid}")
        out.append((entry, rec, p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-version", default="m4")
    ap.add_argument("--probability-signature", default="")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    source = data_root()
    target = backtest_store()
    selected = _select(source, args.model_version, args.probability_signature)
    existing = {str(x.get("prediction_id")) for x in load_jsonl(target / "registry.jsonl")}
    results = _result_ids(target)
    rows = [
        {
            "prediction_id": e["prediction_id"],
            "match_id": e.get("match_id"),
            "already_in_backtest": e["prediction_id"] in existing,
            "result_available": e.get("match_id") in results,
        }
        for e, _, _ in selected
    ]
    pending = [(e, rec, p) for e, rec, p in selected if e["prediction_id"] not in existing]
    missing_results = [r["match_id"] for r in rows if not r["result_available"]]
    if missing_results:
        raise SystemExit(f"refuse ingest: missing result for {missing_results}")

    audit = {
        "schema_version": "backtest-main-ingest-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "target": str(target),
        "model_version": args.model_version,
        "probability_signature": args.probability_signature or None,
        "selected": len(selected),
        "pending": len(pending),
        "already_present": len(selected) - len(pending),
        "rows": rows,
        "dry_run": not args.apply,
    }
    if args.apply:
        target_reg = target / "registry.jsonl"
        target.mkdir(parents=True, exist_ok=True)
        for entry, rec, src_path in pending:
            rel = Path("predictions") / src_path.parent.relative_to(source / "predictions") / src_path.name
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise SystemExit(f"refuse overwrite: {dst}")
            shutil.copy2(src_path, dst)
            prev = load_jsonl(target_reg)
            previous_hash = prev[-1].get("entry_hash", "") if prev else ""
            new_entry = {
                "prediction_id": entry["prediction_id"],
                "match_id": entry.get("match_id"),
                "path": str(dst),
                "record_hash": sha(rec),
                "previous_hash": previous_hash,
                "created_at": entry.get("created_at") or rec.get("created_at"),
            }
            new_entry["entry_hash"] = sha(previous_hash + new_entry["record_hash"])
            append_jsonl(target_reg, new_entry)
        audit["dry_run"] = False
    audit_dir = target / "migrations"
    audit_dir.mkdir(parents=True, exist_ok=True)
    suffix = "apply" if args.apply else "dry_run"
    audit_path = audit_dir / f"main_ingest_{args.model_version}_{suffix}.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "applied" if args.apply else "dry_run", "selected": len(selected), "pending": len(pending), "audit": str(audit_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
