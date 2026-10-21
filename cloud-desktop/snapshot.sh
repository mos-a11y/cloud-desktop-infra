#!/bin/bash
# 云面板监控快照采集器 —— 每 3 秒取本机面板数据，写入本地 .vm-output/panel-stats.json
# 由工作流主循环负责 git 推送到仓库，本脚本不需要任何密钥
export PATH=/usr/bin:/bin:/usr/local/bin:$PATH
mkdir -p .vm-output

PT=$(curl -s -m 10 -X POST -H 'Content-Type: application/json' \
     -d '{"password":"123456"}' http://localhost:8899/api/login \
     | python3 -c 'import sys,json;print(json.load(sys.stdin).get("token",""))' 2>/dev/null)

while true; do
  D=$(curl -s -m 8 "http://localhost:8899/api/stats?token=$PT")
  P=$(curl -s -m 8 "http://localhost:8899/api/processes?token=$PT")
  if [ -n "$D" ] && echo "$D" | grep -q cpu_info; then
    echo "$D" > /tmp/_d.json
    echo "$P" > /tmp/_p.json
    python3 - <<'PYEOF'
import json, time
try:
    d = json.load(open('/tmp/_d.json'))
    try:
        p = json.load(open('/tmp/_p.json')).get('list', [])
    except Exception:
        p = []
    d['processes'] = p
    d['ts'] = time.strftime('%H:%M:%S')
    json.dump(d, open('.vm-output/panel-stats.json', 'w'), ensure_ascii=False)
except Exception as e:
    open('/tmp/snap.err', 'w').write(str(e))
PYEOF
  fi
  sleep 3
done
