#!/usr/bin/env bash
# 云电脑终端启动脚本（手动执行用）
# 注意：后台进程必须重定向 stdin 并 setsid 脱离，
#      否则会让调用方一直挂住等待
set -u
cd "$(dirname "$0")" || exit 0
PORT=7681

if curl -sf -o /dev/null --max-time 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
  echo "webterm already running on ${PORT}"
  exit 0
fi

if ! command -v node >/dev/null 2>&1; then
  echo "node not found, skip"
  exit 0
fi

setsid nohup node "$(dirname "$0")/webterm.js" "${PORT}" \
  > /tmp/webterm.log 2>&1 < /dev/null &
disown 2>/dev/null || true

sleep 1
echo "webterm started on ${PORT}"
exit 0
