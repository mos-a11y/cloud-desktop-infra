#!/bin/bash
# 云面板指令执行器 —— 读仓库指令文件、在本机执行、结果写本地文件（由主循环推送）
# 读取走公开 API，不需要任何密钥
export PATH=/usr/bin:/bin:/usr/local/bin:$PATH
mkdir -p .vm-output
LAST=""
URL='https://api.github.com/repos/mos-a11y/ai-generated-operating-system/contents/.vm-output/commands.json'

getjson() {
  python3 - "$1" <<'PYEOF'
import sys, json, base64, urllib.request
path = sys.argv[1]
H = {'Accept': 'application/vnd.github+json', 'User-Agent': 'panel'}
try:
    r = urllib.request.Request(path + '?ref=main&_=' + str(__import__('time').time()), headers=H)
    j = json.load(urllib.request.urlopen(r, timeout=20))
    print(base64.b64decode(j['content'].replace('\n', '')).decode('utf-8', 'replace'))
except Exception:
    print('')
PYEOF
}

while true; do
  RAW=$(getjson "$URL")
  CID=$(echo "$RAW" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))' 2>/dev/null)
  if [ -n "$CID" ] && [ "$CID" != "$LAST" ]; then
    LAST="$CID"
    echo "$RAW" > /tmp/_cmd.json
    python3 -c 'import json;d=json.load(open("/tmp/_cmd.json"));open("/tmp/_t","w").write(d.get("type",""));open("/tmp/_p","w").write(d.get("payload",""))' 2>/dev/null
    TYPE=$(cat /tmp/_t 2>/dev/null)
    PAY=$(cat /tmp/_p 2>/dev/null)
    printf '{"id":"%s","status":"running","log":"开始执行: %s\\n%s\\n"}' "$CID" "$TYPE" "$PAY" > .vm-output/command-result.json

    LOG="\$ $PAY\n"
    if [ "$TYPE" = "install" ]; then
      LOG+="--- apt-get update ---\n"
      LOG+=$(sudo apt-get update -qq 2>&1 | tail -3)"\n"
      for p in $PAY; do
        LOG+="\n--- 安装 $p ---\n"
        LOG+=$(sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" 2>&1 | tail -10)"\n"
      done
    else
      LOG+=$(bash -lc "$PAY" 2>&1 | tail -40)"\n"
    fi
    LOG+="\n===== 完成 =====\n"

    python3 - "$CID" "$LOG" <<'PYEOF'
import sys, json
json.dump({"id": sys.argv[1], "status": "done", "log": sys.argv[2]},
          open('.vm-output/command-result.json', 'w'), ensure_ascii=False)
PYEOF
  fi
  sleep 5
done
