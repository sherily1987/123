#!/bin/bash
# 预测快捷入口: 自动设置系统代理(10809), 让 Groq 等海外 API 可用
# 用法:
#   ./run.sh predict.py --input data/raw_2026-08-05.json --evidence-dir data/evidence_2026-08-05
#   ./run.sh simulate_from_odds.py --input data/raw_2026-08-05.json --sim 10000
# 代理未开时 Groq 会失败(自动跳过), 其他模型不受影响。
if [ -z "$HTTPS_PROXY" ] && [ -z "$ALL_PROXY" ]; then
    export HTTPS_PROXY=http://127.0.0.1:10809
    export HTTP_PROXY=http://127.0.0.1:10809
    echo "[run.sh] 已设置代理 127.0.0.1:10809"
fi
# 从 Windows 注册表读取持久化的 keys
for V in ZHIPU_API_KEY GROQ_API_KEY MOONSHOT_API_KEY GOOGLE_API_KEY ARK_API_KEY DASHSCOPE_API_KEY DEEPSEEK_API_KEY; do
    if [ -z "${!V}" ]; then
        VAL=$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('$V','User')" | tr -d '\r')
        [ -n "$VAL" ] && export "$V=$VAL"
    fi
done
python "$@"
