#!/usr/bin/env python3
"""fusion_predict — 源码入口（2026-08-02 重建）

原源码在文件系统同步事故中损坏，此前以 cpython-312 字节码 + 运行时补丁运行；
现由 fusion_predict_core.py（反编译重建的源码）提供全部逻辑，本文件仅做
模块加载与公共 API 转发，不再依赖任何 .pyc。
"""
import importlib.util
import copy
from pathlib import Path

from direction_policy import build_direction_policy, load_policy

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_fusion_predict_core_src", _HERE / "fusion_predict_core.py")
if _SPEC is None or _SPEC.loader is None:
    raise SystemExit("fusion_predict_core.py missing")
_core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_core)

_core_predict_one = _core.predict_one


def _attach_direction_policy(result, data):
    """Attach one policy to a formal output without touching its probabilities."""
    if result.get("fusion_status") != "ok" or result.get("research_only") is True:
        return result
    forecast = result.get("forecast") or {}
    probabilities = forecast.get("final_1x2_pct")
    try:
        policy = build_direction_policy(
            probabilities,
            prediction_as_of=data.get("prediction_as_of"),
            model_identity=result.get("build_identity"),
            policy=load_policy(),
        )
    except Exception as exc:
        identity = result.get("build_identity") or {}
        probability_map = (
            dict(zip(("H", "D", "A"), probabilities))
            if isinstance(probabilities, (list, tuple)) and len(probabilities) == 3
            else None
        )
        policy = {
            "schema_version": None,
            "rule_version": None,
            "policy_version": None,
            "status": "UNAVAILABLE",
            "classification": "UNAVAILABLE",
            "primary_direction": None,
            "alternative_direction": None,
            "probabilities": probability_map,
            "probability_unit": None,
            "probability_source": "final_1x2_pct",
            "trigger": None,
            "gap_pp": None,
            "prediction_as_of": data.get("prediction_as_of"),
            "model_version": identity.get("model_version"),
            "probability_signature": identity.get("probability_signature"),
            "decision_policy_signature": None,
            "decision_policy_signature_components": None,
            "reason": "validation_error",
            "validation_error": f"policy_generation_failed:{type(exc).__name__}",
        }
    result["direction_policy"] = policy
    # fusion_cli preserves core_output as the registry-compatible payload.
    # Carry the exact same decision into that projection so fusion_record sees
    # it without changing fusion_predict_core.py (a probability-signature file).
    core_output = result.get("core_output")
    if isinstance(core_output, dict):
        core_output["direction_policy"] = copy.deepcopy(policy)
    return result


def predict_one(core, version, data):
    return _attach_direction_policy(_core_predict_one(core, version, data), data)


# core.main resolves predict_one in its own module globals.  Redirect that
# orchestration call to this wrapper while retaining the original above.
_core.predict_one = predict_one

# 转发公共 API（与旧加载器一致）
main = _core.main
load_core = _core.load_core
decision = _core.decision
build_goal_rate = _core.build_goal_rate
build_injury_view = _core.build_injury_view

if __name__ == "__main__":
    _core.main()
