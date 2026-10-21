#!/bin/bash
# 采样 + 指令处理（由主循环反复调用，每次都是新 bash 进程，自动使用最新脚本）
export PATH=/usr/bin:/bin:/usr/local/bin:$PATH
mkdir -p .vm-output

# ---------- A. 处理指令 ----------
CID=""
if [ -f .vm-output/commands.json ]; then
  CID=$(python3 -c 'import json;print(json.load(open(".vm-output/commands.json")).get("id",""))' 2>/dev/null)
fi
LAST=$(cat .vm-output/.last-cmd 2>/dev/null)
if [ -n "$CID" ] && [ "$CID" != "$LAST" ]; then
  echo "$CID" > .vm-output/.last-cmd
  python3 -c 'import json;d=json.load(open(".vm-output/commands.json"));open("/tmp/_t","w").write(d.get("type",""));open("/tmp/_p","w").write(d.get("payload",""))' 2>/dev/null
  TYPE=$(cat /tmp/_t 2>/dev/null)
  PAY=$(cat /tmp/_p 2>/dev/null)
  printf '{"id":"%s","status":"running","log":"执行中: %s\n"}' "$CID" "$TYPE" > .vm-output/command-result.json

  LOG="\$ $PAY\n"
  case "$TYPE" in
    install)
      LOG+="--- apt-get update ---\n"
      LOG+=$(sudo apt-get update -qq 2>&1 | tail -3)"\n"
      for p in $PAY; do
        LOG+="\n--- 安装 $p ---\n"
        OUT=$(sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" 2>&1 | tail -10)
        LOG+="$OUT\n"
        if echo "$OUT" | grep -qi "无法定位\|Unable to locate\|没有可用的软件包\|no installation candidate\|未找到"; then
          LOG+="[提示] 软件源里没有 $p，可能是名字变更或该版本系统不支持，请换其它软件\n"
        fi
      done ;;
    remove)
      for p in $PAY; do
        LOG+="\n--- 卸载 $p ---\n"
        LOG+=$(sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq "$p" 2>&1 | tail -8)"\n"
      done ;;
    *)
      LOG+=$(bash -lc "$PAY" 2>&1 | tail -60)"\n" ;;
  esac
  LOG+="\n===== 完成 =====\n"

  python3 - "$CID" "$LOG" <<'PY'
import sys, json
json.dump({"id": sys.argv[1], "status": "done", "log": sys.argv[2]},
          open('.vm-output/command-result.json', 'w'), ensure_ascii=False)
PY
fi

# ---------- B. 面板自启动（幂等）----------
if ! pgrep -f "panel/server.py" >/dev/null 2>&1; then
  export DISPLAY=:1
  export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/dbus-sock
  export LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8
  setsid nohup python3 cloud-desktop/panel/server.py > /tmp/panel.log 2>&1 < /dev/null &
  sleep 5
  mkdir -p "$HOME/Desktop"
  printf '[Desktop Entry]\nVersion=1.0\nType=Application\nName=%s\nName[zh_CN]=%s\nExec=%s\nIcon=%s\nTerminal=false\nCategories=%s;\n' \
    "云面板" "云面板" "firefox http://localhost:8899" "utilities-system-monitor" "System" > "$HOME/Desktop/cloud-panel.desktop"
  chmod 755 "$HOME/Desktop/cloud-panel.desktop" 2>/dev/null
  gio set "$HOME/Desktop/cloud-panel.desktop" metadata::xfce-exe-checksum "*" 2>/dev/null
  FF=""
  [ -x /opt/firefox/firefox ] && FF=/opt/firefox/firefox
  [ -z "$FF" ] && [ -x /usr/bin/firefox ] && FF=/usr/bin/firefox
  if [ -n "$FF" ]; then
    export MOZ_DISABLE_CONTENT_SANDBOX=1
    setsid nohup "$FF" --display=:1 "http://localhost:8899" > /tmp/ff-panel.log 2>&1 < /dev/null &
  fi
fi
echo "panel_pid=$(pgrep -f panel/server.py | head -1)" > .vm-output/panel.info

# ---------- C. 采样 ----------
PT=$(curl -s -m 10 -X POST -H 'Content-Type: application/json' -d '{"password":"123456"}' http://localhost:8899/api/login | python3 -c 'import sys,json;print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
curl -s -m 8 "http://localhost:8899/api/stats?token=$PT" > /tmp/_d.json
curl -s -m 8 "http://localhost:8899/api/processes?token=$PT" > /tmp/_p.json
python3 - <<'PY'
import json, time
try:
    d = json.load(open('/tmp/_d.json'))
    if 'cpu_info' not in d:
        raise ValueError('bad stats')
    try:
        p = json.load(open('/tmp/_p.json')).get('list', [])
    except Exception:
        p = []
    d['processes'] = p
    d['ts'] = time.strftime('%H:%M:%S')
    # 附加常用系统信息，供面板展示
    import subprocess
    def sh(c):
        try:
            return subprocess.run(['bash','-lc',c],capture_output=True,text=True,timeout=6).stdout.strip()
        except Exception:
            return ''
    d['ports'] = sh("ss -tlnp 2>/dev/null | head -20")
    d['services'] = sh("systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -25")
    d['docker'] = sh("docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null | head -15")
    d['ip'] = d.get('ip') or sh("curl -s -m 4 ifconfig.me")
    json.dump(d, open('.vm-output/panel-stats.json', 'w'), ensure_ascii=False)
    # 同步到 novnc 静态目录，让手机端通过 VNC 隧道域名直接读取（无需密钥）
    import shutil, os
    for w in ('/usr/share/novnc', '/opt/novnc', '/usr/share/novnc'):
        if os.path.isdir(w):
            try:
                shutil.copy('.vm-output/panel-stats.json', os.path.join(w, 'panel-stats.json'))
                break
            except Exception:
                pass
    print('ok')
except Exception as e:
    open('/tmp/sample.err', 'w').write(str(e))
    print('err', e)
PY
