#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云面板 - 自研服务器控制面板（零依赖，仅用 Python 标准库）"""
import os, sys, json, time, base64, hashlib, struct, threading, subprocess, socket
import fcntl, termios, signal, shutil, urllib.parse, platform, random, string
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get('PANEL_PORT', '8899'))
PASSWORD = os.environ.get('PANEL_PASSWORD', '123456')
BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, 'web')
TOKENS = set()
TASKS = {}
HIST = {'cpu': [], 'mem': [], 'net_rx': [], 'net_tx': []}
NET_LAST = {'rx': 0, 'tx': 0, 't': 0}
NET_RATE = {'rx': 0.0, 'tx': 0.0}
PROC_CACHE = {}
WS_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

def sh(cmd, t=8):
    try:
        return subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:
        return ''

def read_cpu_raw():
    try:
        with open('/proc/stat') as f:
            for line in f:
                if line.startswith('cpu '):
                    return [int(x) for x in line.split()[1:]]
    except Exception:
        pass
    return [0] * 8

def cpu_pct():
    a = read_cpu_raw(); time.sleep(0.25); b = read_cpu_raw()
    ta, tb = sum(a), sum(b)
    if tb - ta <= 0: return 0.0
    return round(100.0 * (1 - (b[3] - a[3]) / (tb - ta)), 1)

def meminfo():
    d = {}
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':')[0], line.split(':')[1].strip().split()[0]
                d[k] = int(v) * 1024
    except Exception:
        pass
    total = d.get('MemTotal', 0)
    avail = d.get('MemAvailable', d.get('MemFree', 0))
    return {
        'total': total, 'used': total - avail, 'free': avail,
        'buffers': d.get('Buffers', 0), 'cached': d.get('Cached', 0),
        'swap_total': d.get('SwapTotal', 0),
        'swap_used': d.get('SwapTotal', 0) - d.get('SwapFree', 0),
        'percent': round(100.0 * (total - avail) / total, 1) if total else 0,
    }

def disks():
    out, seen = [], set()
    try:
        with open('/proc/mounts') as f:
            for line in f:
                p = line.split()
                if len(p) < 2 or not p[0].startswith('/dev/'): continue
                mp = p[1]
                if mp in seen: continue
                try:
                    st = os.statvfs(mp)
                    total = st.f_blocks * st.f_frsize
                    free = st.f_bfree * st.f_frsize
                    used = total - free
                    seen.add(mp)
                    out.append({'mount': mp, 'dev': p[0], 'total': total, 'used': used,
                                'free': free, 'percent': round(100.0 * used / total, 1) if total else 0})
                except Exception:
                    pass
    except Exception:
        pass
    if not out:
        try:
            st = os.statvfs('/')
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            out.append({'mount': '/', 'dev': 'rootfs', 'total': total, 'used': total - free,
                        'free': free, 'percent': round(100.0 * (total - free) / total, 1) if total else 0})
        except Exception:
            pass
    return out

def net_io():
    rx = tx = 0
    try:
        with open('/proc/net/dev') as f:
            for line in f.readlines()[2:]:
                p = line.split()
                iface = p[0].rstrip(':')
                if iface == 'lo': continue
                rx += int(p[1]); tx += int(p[9])
    except Exception:
        pass
    return rx, tx

def load_avg():
    try:
        return [round(float(x), 2) for x in open('/proc/loadavg').read().split()[:3]]
    except Exception:
        return [0, 0, 0]

def uptime_s():
    try:
        return int(float(open('/proc/uptime').read().split()[0]))
    except Exception:
        return 0

def cpu_info():
    model = ''
    try:
        for line in open('/proc/cpuinfo'):
            if 'model name' in line:
                model = line.split(':')[1].strip(); break
    except Exception:
        pass
    cores = os.cpu_count() or 1
    return {'model': model or platform.machine(), 'cores': cores}

def procs(limit=40):
    now = time.time()
    total = sum(read_cpu_raw()[:8]) or 1
    hz = os.sysconf('SC_CLK_TCK')
    out = []
    prev = PROC_CACHE.get('cpu_total', total)
    for pid in os.listdir('/proc'):
        if not pid.isdigit(): continue
        try:
            with open('/proc/%s/stat' % pid) as f:
                s = f.read()
            name = s[s.index('(') + 1:s.rindex(')')]
            rest = s[s.rindex(')') + 2:].split()
            ut, st = int(rest[11]), int(rest[12])
            rss = int(rest[21]) * 4096
            state = rest[0]
            ticks = ut + st
            pt = PROC_CACHE.get('p_' + pid)
            cpu = round(100.0 * (ticks - pt[0]) / ((total - prev) / (os.cpu_count() or 1) or 1), 1) if pt else 0.0
            PROC_CACHE['p_' + pid] = (ticks, now)
            try:
                cmd = open('/proc/%s/cmdline' % pid).read().replace('\x00', ' ').strip() or name
            except Exception:
                cmd = name
            out.append({'pid': int(pid), 'name': name, 'cpu': max(cpu, 0.0), 'rss': rss,
                        'state': state, 'cmd': cmd[:120]})
        except Exception:
            continue
    PROC_CACHE['cpu_total'] = total
    out.sort(key=lambda x: -x['cpu'])
    return out[:limit]

def sampler():
    while True:
        try:
            c = cpu_pct()
            m = meminfo()
            rx, tx = net_io()
            t = time.time()
            if NET_LAST['t']:
                dt = t - NET_LAST['t']
                NET_RATE['rx'] = max(0.0, (rx - NET_LAST['rx']) / dt)
                NET_RATE['tx'] = max(0.0, (tx - NET_LAST['tx']) / dt)
            NET_LAST.update({'rx': rx, 'tx': tx, 't': t})
            for k, v in (('cpu', c), ('mem', m['percent']),
                         ('net_rx', round(NET_RATE['rx'] / 1024, 1)), ('net_tx', round(NET_RATE['tx'] / 1024, 1))):
                HIST[k].append(v)
                if len(HIST[k]) > 60: HIST[k].pop(0)
        except Exception:
            pass
        time.sleep(2)

threading.Thread(target=sampler, daemon=True).start()

APPS = [
    ('浏览器', 'Chromium 开源浏览器', 'chromium-browser'),
    ('浏览器', 'Epiphany 简洁浏览器', 'epiphany-browser'),
    ('浏览器', 'Midori 轻量浏览器', 'midori'),
    ('办公', 'LibreOffice 办公套件', 'libreoffice'),
    ('办公', 'PDF 阅读器 Evince', 'evince'),
    ('办公', '词典 GoldenDict', 'goldendict'),
    ('图形', 'GIMP 图像处理', 'gimp'),
    ('图形', 'Inkscape 矢量绘图', 'inkscape'),
    ('图形', '截图工具 Flameshot', 'flameshot'),
    ('影音', 'VLC 播放器', 'vlc'),
    ('影音', 'Audacity 音频编辑', 'audacity'),
    ('影音', 'MP3 编码器 lame', 'lame'),
    ('系统', 'htop 任务管理器', 'htop'),
    ('系统', 'neofetch 系统信息', 'neofetch'),
    ('系统', 'GParted 分区工具', 'gparted'),
    ('开发', 'Python 包管理 pip', 'python3-pip'),
    ('开发', 'Git 版本控制', 'git'),
    ('开发', 'Vim 编辑器', 'vim'),
    ('开发', 'Node.js 运行环境', 'nodejs npm'),
    ('工具', '7zip 压缩工具', 'p7zip-full'),
    ('工具', 'Wget/Curl 下载工具', 'wget curl'),
    ('工具', 'Wine 运行 Windows 程序', 'wine'),
    ('工具', '文件搜索 Recoll', 'recoll'),
    ('聊天', 'Pidgin 即时通讯', 'pidgin'),
    ('聊天', 'Thunderbird 邮件', 'thunderbird'),
]

def human(n):
    for u in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024: return '%.1f %s' % (n, u)
        n /= 1024.0
    return '%.1f PB' % n

def run_install(task, pkgs):
    TASKS[task]['status'] = 'running'
    try:
        p = subprocess.Popen(['sudo', 'apt-get', 'update', '-qq'],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        p.wait()
        for pkg in pkgs:
            TASKS[task]['log'] += '\n$ sudo apt-get install -y %s\n' % pkg
            p = subprocess.Popen(['sudo', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', pkg],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                TASKS[task]['log'] += line
            p.wait()
            TASKS[task]['log'] += '\n[完成] %s exit=%s\n' % (pkg, p.returncode)
        TASKS[task]['status'] = 'done'
    except Exception as e:
        TASKS[task]['log'] += '\n[错误] %s\n' % e
        TASKS[task]['status'] = 'error'
    TASKS[task]['log'] += '\n===== 全部完成 =====\n'

def recvn(sock, n):
    buf = b''
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c: raise ConnectionError('closed')
        buf += c
    return buf

def ws_send(sock, opcode, payload):
    if isinstance(payload, str): payload = payload.encode('utf-8')
    h = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126: h += bytes([n])
    elif n < 65536: h += bytes([126]) + struct.pack('>H', n)
    else: h += bytes([127]) + struct.pack('>Q', n)
    sock.sendall(h + payload)

def ws_recv(sock):
    b1, b2 = recvn(sock, 2)
    opcode = b1 & 0x0f
    ln = b2 & 0x7f
    masked = b2 & 0x80
    if ln == 126: ln = struct.unpack('>H', recvn(sock, 2))[0]
    elif ln == 127: ln = struct.unpack('>Q', recvn(sock, 8))[0]
    mask = recvn(sock, 4) if masked else None
    data = recvn(sock, ln) if ln else b''
    if mask: data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data

def serve_terminal(sock):
    import pty
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update({'LANG': 'zh_CN.UTF-8', 'LC_ALL': 'zh_CN.UTF-8',
                           'TERM': 'xterm-256color', 'PS1': '[\\u@云面板 \\W]\\$ '})
        os.execv('/bin/bash', ['bash', '-i'])
    def reader():
        while True:
            try:
                d = os.read(fd, 4096)
                if not d: break
                ws_send(sock, 1, d.decode('utf-8', 'replace'))
            except Exception:
                break
        try: ws_send(sock, 8, b'')
        except Exception: pass
    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            op, data = ws_recv(sock)
            if op == 8: break
            if op != 1: continue
            try:
                j = json.loads(data.decode('utf-8'))
                if isinstance(j, dict) and 'resize' in j:
                    cols, rows = j['resize']
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                    continue
                if isinstance(j, dict) and 'cmd' in j:
                    data = j['cmd'].encode('utf-8')
            except Exception:
                pass
            os.write(fd, data)
    except Exception:
        pass
    finally:
        try: os.kill(pid, signal.SIGKILL)
        except Exception: pass
        try: sock.close()
        except Exception: pass

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a): pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str): body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name, ctype):
        p = os.path.join(WEB, name)
        try:
            body = open(p, 'rb').read()
            self._send(200, body, ctype)
        except Exception:
            self._send(404, 'not found', 'text/plain')

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        if path == '/ws/terminal':
            key = q.get('token', [''])[0]
            if key not in TOKENS:
                self._send(401, 'unauthorized'); return
            headers = dict(self.headers)
            if headers.get('Upgrade', '').lower() != 'websocket':
                self._send(400, 'need websocket'); return
            accept = base64.b64encode(hashlib.sha1(
                (headers.get('Sec-WebSocket-Key', '') + WS_MAGIC).encode()).digest()).decode()
            self.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                              'Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n' % accept).encode())
            self.wfile.flush()
            self.close_connection = True
            serve_terminal(self.connection)
            return
        if path.startswith('/api/'):
            return self.api(path, q)
        if path == '/' or path == '/index.html':
            return self._file('index.html', 'text/html; charset=utf-8')
        if path == '/app.js': return self._file('app.js', 'application/javascript; charset=utf-8')
        if path == '/style.css': return self._file('style.css', 'text/css; charset=utf-8')
        self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        ln = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(ln) if ln else b'{}'
        try:
            body = json.loads(raw.decode('utf-8'))
        except Exception:
            body = {}
        self.api(u.path, {}, body)

    def api(self, path, q, post=None):
        post = post or {}
        tok = q.get('token', [''])[0] or post.get('token', '')
        if path == '/api/login':
            if post.get('password') == PASSWORD:
                t = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
                TOKENS.add(t)
                return self._send(200, {'ok': True, 'token': t})
            return self._send(200, {'ok': False, 'msg': '密码错误'})
        if tok not in TOKENS:
            return self._send(401, {'ok': False, 'msg': '未登录'})
        if path == '/api/stats':
            d = disks()
            root = d[0] if d else {'total': 0, 'used': 0, 'free': 0, 'percent': 0}
            return self._send(200, {
                'cpu': HIST['cpu'][-1] if HIST['cpu'] else 0,
                'cpu_hist': HIST['cpu'], 'mem_hist': HIST['mem'],
                'net_rx_hist': HIST['net_rx'], 'net_tx_hist': HIST['net_tx'],
                'mem': meminfo(), 'disk': root, 'disks': d,
                'load': load_avg(), 'uptime': uptime_s(),
                'net_rate': {'rx': NET_RATE['rx'], 'tx': NET_RATE['tx']},
                'cpu_info': cpu_info(),
                'hostname': platform.node(),
                'system': sh('lsb_release -d 2>/dev/null | cut -f2') or platform.platform(),
                'kernel': platform.release(),
                'ip': sh('curl -s -m 4 ifconfig.me'),
            })
        if path == '/api/processes':
            return self._send(200, {'ok': True, 'list': procs()})
        if path == '/api/kill':
            pid = int(post.get('pid', 0))
            try:
                os.kill(pid, signal.SIGKILL); return self._send(200, {'ok': True})
            except Exception as e:
                return self._send(200, {'ok': False, 'msg': str(e)})
        if path == '/api/exec':
            cmd = post.get('cmd', '')
            try:
                r = subprocess.run(['bash', '-lc', cmd], capture_output=True, text=True, timeout=25)
                return self._send(200, {'ok': True, 'out': r.stdout + r.stderr})
            except Exception as e:
                return self._send(200, {'ok': False, 'msg': str(e)})
        if path == '/api/apps':
            return self._send(200, {'ok': True, 'apps': [{'cat': a, 'name': b, 'pkg': c} for a, b, c in APPS]})
        if path == '/api/install':
            pkgs = post.get('pkgs', [])
            if not pkgs: return self._send(200, {'ok': False, 'msg': '未选择'})
            tid = str(int(time.time() * 1000))
            TASKS[tid] = {'status': 'running', 'log': '开始安装: %s\n' % ' '.join(pkgs)}
            threading.Thread(target=run_install, args=(tid, pkgs), daemon=True).start()
            return self._send(200, {'ok': True, 'task': tid})
        if path == '/api/task':
            t = TASKS.get(post.get('id') or q.get('id', [''])[0], None)
            return self._send(200, t or {'status': 'none', 'log': ''})
        if path == '/api/files':
            p = q.get('path', ['/'])[0] or '/'
            try:
                items = []
                for n in sorted(os.listdir(p)):
                    fp = os.path.join(p, n)
                    try:
                        st = os.stat(fp)
                        items.append({'name': n, 'dir': os.path.isdir(fp), 'size': st.st_size,
                                      'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})
                    except Exception:
                        pass
                return self._send(200, {'ok': True, 'path': p, 'list': items})
            except Exception as e:
                return self._send(200, {'ok': False, 'msg': str(e)})
        return self._send(404, {'ok': False})

if __name__ == '__main__':
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    srv.daemon_threads = True
    print('云面板 started on %d' % PORT, flush=True)
    srv.serve_forever()
