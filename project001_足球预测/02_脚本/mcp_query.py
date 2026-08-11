#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apifootball MCP 查询工具（2026-08-07 实测；项目唯一实现位于 project001_足球预测/02_脚本）
用法: python mcp_query.py <工具名> [参数JSON]
示例:
  python mcp_query.py search_football_leagues '{"country":"England"}'
  python mcp_query.py get_football_matches '{"date_from":"2026-08-08","date_to":"2026-08-08"}'
  python mcp_query.py get_football_odds '{"date_from":"2026-08-08","date_to":"2026-08-08","match_id":"716918"}'
  python mcp_query.py get_football_predictions '{"date_from":"2026-08-08","date_to":"2026-08-08","match_id":"716918"}'
  python mcp_query.py get_football_standings '{"league_id":"222"}'
  python mcp_query.py get_match_details '{"match_id":"716918"}'
  python mcp_query.py get_head_to_head '{"team1_name":"Valerenga","team2_name":"Bodo/Glimt"}'
  python mcp_query.py get_football_topscorers '{"league_id":"253"}'
  python mcp_query.py get_live_football_matches '{}'
  python mcp_query.py get_live_football_odds_comments '{"match_id":"716918"}'
环境变量: MCP_APIFOOTBALL_API_KEY (已 setx)
注意: 服务器慢(20-60s)且连接不稳, 脚本内置重试; odds/predictions/matches 必须带
      date_from/date_to (match_id 只是窄化); topscorers 当前套餐权限受限。
"""
import json, os, sys, time, http.client, ssl

HOST = "mcp.apifootball.com"
PATH = "/mcp"
KEY = os.environ.get("MCP_APIFOOTBALL_API_KEY", "")

def make_conn():
    return http.client.HTTPSConnection(HOST, timeout=180, context=ssl.create_default_context())

def call(payload, session=None, retries=4):
    last = None
    for i in range(retries):
        conn = make_conn()
        try:
            headers = {"Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream",
                       "Authorization": f"Bearer {KEY}"}
            if session:
                headers["Mcp-Session-Id"] = session
            conn.request("POST", PATH, body=json.dumps(payload).encode(), headers=headers)
            resp = conn.getresponse()
            sid = resp.getheader("Mcp-Session-Id")
            raw = resp.read().decode()
            conn.close()
            return sid, raw
        except Exception as e:
            last = e
            try: conn.close()
            except: pass
            time.sleep(3 * (i + 1))
    raise last

def parse(body):
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(body)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    sid, body = call({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"mcp_query","version":"1.0"}}})
    sid, body = call({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name": name, "arguments": args}}, session=sid)
    r = parse(body)
    if "error" in r:
        print(json.dumps(r["error"], ensure_ascii=False, indent=2))
        sys.exit(2)
    for item in r.get("result", {}).get("content", []):
        print(item.get("text", ""))

if __name__ == "__main__":
    main()
