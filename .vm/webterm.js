/* 云电脑 Web 终端 —— 零依赖，只用 Node 内置模块
   用法: node webterm.js [端口]  默认 7681 */
const http = require('http');
const crypto = require('crypto');
const { spawn } = require('child_process');
const os = require('os');

const PORT = Number(process.env.PORT || process.argv[2] || 7681);
const SHELL = process.env.SHELL || (os.platform() === 'win32' ? 'cmd.exe' : '/bin/bash');

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>云电脑</title><style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#0d1117;color:#c9d1d9;
  font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
#wrap{display:flex;flex-direction:column;height:100%}
#bar{padding:5px 10px;background:#161b22;border-bottom:1px solid #30363d;
  display:flex;gap:8px;align-items:center;font-size:12px;flex-shrink:0}
#dot{width:8px;height:8px;border-radius:50%;background:#f85149}
#dot.on{background:#3fb950}
#screen{flex:1;overflow-y:auto;padding:10px 12px;white-space:pre-wrap;word-break:break-all}
#input{width:100%;padding:9px 12px;border:none;border-top:1px solid #30363d;
  background:#0d1117;color:#c9d1d9;font:inherit;outline:none;flex-shrink:0}
.hint{color:#8b949e}
.btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;
  padding:2px 9px;cursor:pointer;font:inherit;font-size:12px}
</style></head><body><div id="wrap">
<div id="bar"><span id="dot"></span><span id="st">连接中…</span>
<span style="margin-left:auto" class="hint">输入命令回车执行</span>
<button class="btn" onclick="send('\\x03')">Ctrl+C</button>
<button class="btn" onclick="send('\\x0c')">清屏</button>
</div>
<div id="screen"></div>
<input id="input" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false">
</div><script>
var ws,scr=document.getElementById('screen'),inp=document.getElementById('input'),
    dot=document.getElementById('dot'),st=document.getElementById('st');
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function out(t){scr.innerHTML+=esc(t);scr.scrollTop=scr.scrollHeight}
function connect(){
  var p=(location.protocol==='https:'?'wss://':'ws://')+location.host;
  ws=new WebSocket(p+location.pathname.replace(/\\/$/,'')+'/ws');
  ws.onopen=function(){dot.className='on';st.textContent='已连接';out('\\r\\n');};
  ws.onmessage=function(e){out(e.data)};
  ws.onclose=function(){dot.className='';st.textContent='已断开，3秒后重连…';setTimeout(connect,3000)};
  ws.onerror=function(){};
}
function send(s){ if(ws&&ws.readyState===1) ws.send(s); }
inp.addEventListener('keydown',function(e){
  if(e.key==='Enter'){ var v=inp.value+'\\r'; inp.value=''; send(v); e.preventDefault(); }
  else if(e.key==='Tab'){ send('\\t'); e.preventDefault(); }
  else if(e.ctrlKey&&e.key==='c'){ send('\\x03'); e.preventDefault(); }
  else if(e.key==='ArrowUp'){ send('\\x1b[A'); e.preventDefault(); }
  else if(e.key==='ArrowDown'){ send('\\x1b[B'); e.preventDefault(); }
});
inp.focus();
scr.addEventListener('click',function(){inp.focus()});
/* 通知父页面：终端已真正加载并就绪（父页面用它判断嵌入成功与否） */
try{ if(window.parent!==window) window.parent.postMessage({type:'VM_TERM_READY'},'*'); }catch(e){}
connect();
/* 连上 ws 后再报一次，带时间戳 */
var _t=setInterval(function(){
  if(ws&&ws.readyState===1){
    try{ if(window.parent!==window) window.parent.postMessage({type:'VM_TERM_READY',ws:true},'*'); }catch(e){}
    clearInterval(_t);
  }
},500);
</script></body></html>`;

function handshake(req, key) {
  const magic = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
  return crypto.createHash('sha1').update(key + magic).digest('base64');
}
function decode(buf) {
  if (buf.length < 2) return null;
  const b1 = buf[0], b2 = buf[1];
  const opcode = b1 & 0x0f;
  const masked = (b2 & 0x80) !== 0;
  let len = b2 & 0x7f, off = 2;
  if (len === 126) { if (buf.length < 4) return null; len = buf.readUInt16BE(2); off = 4; }
  else if (len === 127) { if (buf.length < 10) return null; len = Number(buf.readBigUInt64BE(2)); off = 10; }
  let mask = null;
  if (masked) { if (buf.length < off + 4) return null; mask = buf.slice(off, off + 4); off += 4; }
  if (buf.length < off + len) return null;
  const data = Buffer.from(buf.slice(off, off + len));
  if (mask) for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4];
  return { opcode, payload: data, bytesUsed: off + len };
}
function encode(str, opcode) {
  opcode = opcode || 1;
  const data = Buffer.from(str, 'utf8');
  const len = data.length;
  let head;
  if (len < 126) { head = Buffer.alloc(2); head[1] = len; }
  else if (len < 65536) { head = Buffer.alloc(4); head[1] = 126; head.writeUInt16BE(len, 2); }
  else { head = Buffer.alloc(10); head[1] = 127; head.writeBigUInt64BE(BigInt(len), 2); }
  head[0] = 0x80 | opcode;
  return Buffer.concat([head, data]);
}

const server = http.createServer(function (req, res) {
  const u = (req.url || '/').split('?')[0];
  if (u === '/' || u === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(PAGE); return;
  }
  if (u === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*' });
    res.end('{"ok":true}'); return;
  }
  /* script 标签探测专用：返回可执行 JS，只有真正的服务才会执行成功 */
  if (u === '/health.js') {
    res.writeHead(200, { 'Content-Type': 'application/javascript',
      'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
    res.end('window.__VM_HEALTH__=1;'); return;
  }
  if (u === '/pixel.png') {
    res.writeHead(200, { 'Content-Type': 'image/png',
      'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' });
    res.end(Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
      'base64'));
    return;
  }
  res.writeHead(404); res.end('not found');
});

server.on('upgrade', function (req, socket) {
  const u = (req.url || '').split('?')[0];
  if (u !== '/ws') { socket.destroy(); return; }
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\nConnection: Upgrade\r\n' +
    'Sec-WebSocket-Accept: ' + handshake(req, key) + '\r\n\r\n'
  );
  socket.setNoDelay(true);

  let sh;
  try {
    sh = spawn(SHELL, ['-i'], {
      env: Object.assign({}, process.env, {
        TERM: 'xterm-256color', COLUMNS: '220', LINES: '50', PS1: '$ '
      }),
      cwd: process.env.HOME || '/'
    });
  } catch (e) {
    try { socket.write(encode('无法启动 shell: ' + e.message)); } catch (x) {}
    socket.destroy(); return;
  }
  sh.stdout.on('data', function (d) { try { socket.write(encode(d.toString('utf8'))); } catch (e) {} });
  sh.stderr.on('data', function (d) { try { socket.write(encode(d.toString('utf8'))); } catch (e) {} });
  sh.on('exit', function () {
    try { socket.write(encode('\r\n[shell 已退出]')); socket.end(); } catch (e) {}
  });

  let buf = Buffer.alloc(0);
  socket.on('data', function (chunk) {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      const f = decode(buf);
      if (!f) break;
      buf = buf.slice(f.bytesUsed);
      if (f.opcode === 8) { try { sh.kill(); } catch (e) {} socket.end(); return; }
      if (f.opcode === 9) { try { socket.write(encode(f.payload.toString(), 10)); } catch (e) {} continue; }
      if (f.opcode === 1) { try { sh.stdin.write(f.payload.toString('utf8')); } catch (e) {} }
    }
  });
  socket.on('close', function () { try { sh.kill(); } catch (e) {} });
  socket.on('error', function () { try { sh.kill(); } catch (e) {} });
});

server.listen(PORT, '0.0.0.0', function () {
  console.log('webterm listening on ' + PORT);
});
