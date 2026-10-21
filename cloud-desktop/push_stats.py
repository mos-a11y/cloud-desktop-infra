#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云面板数据桥 —— 在云电脑内部运行，一次调用完成：
   1. 处理远程指令（读取 commands.json -> 执行 -> 写回 command-result.json）
   2. 自启动云面板服务（幂等）
   3. 采集系统状态 -> 推送到仓库 .vm-output/panel-stats.json

全部通过 GitHub API 完成，不依赖 git 工作区状态。
访问令牌从环境变量 GITHUB_TOKEN 读取（由工作流注入）。
"""
import os, json, time, base64, subprocess, urllib.request, urllib.error

TOKEN = os.environ.get('GITHUB_TOKEN', '')
REPO = 'mos-a11y/ai-generated-operating-system'
BR = 'main'
BASE = 'https://api.github.com/repos/%s/contents/' % REPO
RAW = 'https://raw.githubusercontent.com/%s/%s' % (REPO, BR)
H = {
    'Authorization': 'token ' + TOKEN,
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'cloud-panel-bridge',
    'Content-Type': 'application/json',
}
OUT = '.vm-output'


def log(*a):
    print('[bridge]', *a, flush=True)


def api_get(path):
    """读取仓库文件内容，返回 (text, sha)"""
    try:
        req = urllib.request.Request(BASE + path + '?ref=' + BR + '&_=' + str(time.time()), headers=H)
        j = json.load(urllib.request.urlopen(req, timeout=20))
        return base64.b64decode(j['content'].replace('\n', '')).decode('utf-8', 'replace'), j.get('sha')
    except Exception:
        return None, None


def api_put(path, text, msg='update'):
    _, sha = api_get(path)
    payload = {
        'message': msg,
        'content': base64.b64encode(text.encode('utf-8')).decode(),
        'branch': BR,
    }
    if sha:
        payload['sha'] = sha
    try:
        req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                     method='PUT', headers=H)
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        log('put fail', path, str(e)[:80])
        return False


def sh(cmd, t=10):
    try:
        r = subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=t)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return '(执行超时或失败) ' + str(e)[:40]


# ---------------- 1. 处理指令 ----------------
def handle_commands():
    raw, _ = api_get(OUT + '/commands.json')
    if not raw:
        return
    try:
        cmd = json.loads(raw)
    except Exception:
        return
    cid = str(cmd.get('id', ''))
    if not cid:
        return
    try:
        last = open('/tmp/.last_cmd').read().strip()
    except Exception:
        last = ''
    if cid == last:
        return
    open('/tmp/.last_cmd', 'w').write(cid)

    ctype = cmd.get('type', 'shell')
    payload = cmd.get('payload', '')
    log('执行命令', ctype, payload[:60])
    api_put(OUT + '/command-result.json',
            json.dumps({'id': cid, 'status': 'running', 'log': '执行中：%s\n%s\n' % (ctype, payload)},
                       ensure_ascii=False), 'cmd running')

    out = '$ ' + payload + '\n'
    if ctype == 'install':
        out += '--- 更新软件源 ---\n' + sh('sudo apt-get update -qq 2>&1 | tail -3', 90) + '\n'
        for p in payload.split():
            out += '\n--- 安装 %s ---\n' % p
            r = sh('sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq %s 2>&1 | tail -12' % p, 240)
            out += r + '\n'
            if any(k in r for k in ('Unable to locate', '无法定位', 'no installation candidate', '没有可用的软件包')):
                out += '[提示] 软件源里没有「%s」，该软件在当前系统版本不可用，请换其它软件。\n' % p
    elif ctype == 'remove':
        for p in payload.split():
            out += '\n--- 卸载 %s ---\n' % p
            out += sh('sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq %s 2>&1 | tail -8' % p, 180) + '\n'
    else:
        out += sh(payload, 120) + '\n'
    out += '\n===== 完成 =====\n'

    api_put(OUT + '/command-result.json',
            json.dumps({'id': cid, 'status': 'done', 'log': out}, ensure_ascii=False), 'cmd done')
    log('命令完成', cid)


# ---------------- 2. 面板自启动 ----------------
def ensure_panel():
    r = subprocess.run(['pgrep', '-f', 'panel/server.py'], capture_output=True, text=True)
    if r.stdout.strip():
        return True
    log('启动面板服务')
    env = dict(os.environ)
    env.update({'DISPLAY': ':1', 'LANG': 'zh_CN.UTF-8', 'LC_ALL': 'zh_CN.UTF-8'})
    subprocess.Popen(['python3', 'cloud-desktop/panel/server.py'],
                     stdout=open('/tmp/panel.log', 'a'), stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    time.sleep(6)
    # 桌面图标 + 用浏览器打开
    home = os.path.expanduser('~')
    os.makedirs(home + '/Desktop', exist_ok=True)
    try:
        open(home + '/Desktop/cloud-panel.desktop', 'w').write(
            '[Desktop Entry]\nVersion=1.0\nType=Application\nName=云面板\nName[zh_CN]=云面板\n'
            'Exec=firefox http://localhost:8899\nIcon=utilities-system-monitor\n'
            'Terminal=false\nCategories=System;\n')
        os.chmod(home + '/Desktop/cloud-panel.desktop', 0o755)
    except Exception:
        pass
    for ff in ('/opt/firefox/firefox', '/usr/bin/firefox'):
        if os.path.exists(ff):
            e2 = dict(env)
            e2['MOZ_DISABLE_CONTENT_SANDBOX'] = '1'
            subprocess.Popen([ff, '--display=:1', 'http://localhost:8899'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, env=e2, start_new_session=True)
            break
    return True


# ---------------- 3. 采集并推送 ----------------
def collect():
    try:
        req = urllib.request.Request('http://localhost:8899/api/login',
                                     data=json.dumps({'password': '123456'}).encode(),
                                     headers={'Content-Type': 'application/json'})
        tok = json.load(urllib.request.urlopen(req, timeout=10)).get('token', '')
    except Exception:
        tok = ''
    if not tok:
        log('面板未就绪')
        return False
    try:
        d = json.load(urllib.request.urlopen(
            'http://localhost:8899/api/stats?token=' + tok, timeout=10))
        p = json.load(urllib.request.urlopen(
            'http://localhost:8899/api/processes?token=' + tok, timeout=10))
    except Exception as e:
        log('采样失败', str(e)[:60])
        return False

    d['processes'] = p.get('list', [])
    d['ts'] = time.strftime('%H:%M:%S')
    d['ports'] = sh('ss -tlnp 2>/dev/null | head -20', 8)
    d['services'] = sh('systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -25', 8)
    d['ip'] = d.get('ip') or sh('curl -s -m 4 ifconfig.me', 8)

    os.makedirs(OUT, exist_ok=True)
    json.dump(d, open(OUT + '/panel-stats.json', 'w'), ensure_ascii=False)

    # 同步到 noVNC 静态目录，让手机通过 VNC 域名直接读取（免密钥）
    for w in ('/usr/share/novnc', '/opt/novnc', '/usr/local/share/novnc'):
        if os.path.isdir(w):
            try:
                open(os.path.join(w, 'panel-stats.json'), 'w').write(
                    json.dumps(d, ensure_ascii=False))
                log('已同步到', w)
                break
            except Exception:
                pass

    ok = api_put(OUT + '/panel-stats.json', json.dumps(d, ensure_ascii=False), 'stats')
    log('推送', 'OK' if ok else '失败', d['ts'])
    return ok


if __name__ == '__main__':
    if not TOKEN:
        log('缺少 GITHUB_TOKEN')
        raise SystemExit(1)
    try:
        handle_commands()
    except Exception as e:
        log('指令处理异常', str(e)[:80])
    try:
        ensure_panel()
    except Exception as e:
        log('面板启动异常', str(e)[:80])
    try:
        collect()
    except Exception as e:
        log('采集异常', str(e)[:80])
