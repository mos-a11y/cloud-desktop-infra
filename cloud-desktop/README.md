# 云电脑配置存档（重置用）

这台云电脑每次启动都是全新容器，只有仓库里的文件会保留。
所有定制都放在 `cloud-desktop/` 目录，重置后执行一条命令即可恢复。

## 密码
```
123456
```

## 一键恢复（新机器启动后，在桌面终端里执行）
```bash
cd ~/work/ai-generated-operating-system/ai-generated-operating-system 2>/dev/null || \
cd /home/runner/work/ai-generated-operating-system/ai-generated-operating-system
bash cloud-desktop/setup.sh
```
或用命令台工作流执行 `bash cloud-desktop/setup.sh`（约 3 分钟）。

## 包含内容
| 文件 | 作用 |
|---|---|
| `setup.sh` | 一键配置：中文语言包/字体、深色主题+壁纸、三款浏览器、应用商店、桌面图标 |
| `app-store.sh` | 应用商店（zenity 图形界面，无图形时自动降级为终端菜单），25 款可选软件 |
| `README.md` | 本说明 |

## 浏览器
- **Firefox 火狐**：官方中文版，装在 `/opt/firefox`
- **谷歌浏览器**：`google-chrome-stable`
- **Falkon**：轻量浏览器

## 应用商店
桌面「应用商店」图标 → 终端里弹出勾选界面（或图形窗口）→ 勾选 → 自动安装。
可选：Chromium / Epiphany / Midori / LibreOffice / Evince / GoldenDict / GIMP / Inkscape /
Flameshot / VLC / Audacity / lame / htop / neofetch / GParted / pip / git / vim / Node.js /
7zip / wget curl / Wine / Recoll / Pidgin / Thunderbird。

## 流畅度与外观设置
- 色深 16 位，关闭窗口合成动画
- x11vnc：`-ncache 10 -ncache_cr -scrollcopyrect -compresslevel 6 -quality 6 -deferupdate 30`
- 访问链接带 `?autoconnect=true&resize=scale&quality=5&compression=6` 省流量参数
- 主题 Greybird-dark + Papirus 图标 + Noto Sans CJK 中文字体

## 注意
- 单次存活约 170 分钟，到点自动关闭，重开链接会变
- 桌面里的文件不持久，重要东西记得传出来
