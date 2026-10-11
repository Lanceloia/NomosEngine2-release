# M1 Web 试玩

M1 是同一作者编译链的应用样例：位置、永焰充能、观察、寒冷与居民行动共同组成冰宫冒险。
[视频介绍](showcase/introduction/README.md)可以先看实际变化，再决定是否安装。

## 获取匹配版本

两个公开仓库使用相同展示标签 `showcase-2026-10-11`。标签固定这次对外展示，
后续开发更新保留在各自默认分支。

| 仓库 | 负责什么 |
| --- | --- |
| [NomosEngine2-release](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-2026-10-11) | C0/K0/T0、作者资产与实验 |
| [nomos-m1-web](https://github.com/Lanceloia/nomos-m1-web/tree/showcase-2026-10-11) | React 页面、Python 会话服务、公开选项上的人格评分 |

```bash
git clone --branch showcase-2026-10-11 https://github.com/Lanceloia/NomosEngine2-release.git nomosengine2-release
git clone --branch showcase-2026-10-11 https://github.com/Lanceloia/nomos-m1-web.git m1-tabletop-prototype
cd m1-tabletop-prototype
python3 -m venv .venv
.venv/bin/python -m pip install -e ../nomosengine2-release
npm ci
npm run build
npm start
```

需要 Node.js 20.3+、Python 3.11+；本轮实现验证环境为 Python 3.14.4 / Linux。
Windows 将 Python 路径换成 `.venv\Scripts\python.exe`。
打开 <http://127.0.0.1:5173/>，首次编译完成后开始新游戏。新游戏共享规则 Program，各局状态独立。
开发用 `npm run dev`；端口占用可使用 `M1_WEB_PORT=5180 npm start`。

## 玩家会看到什么

眼前人物与物件、地图、确认前已有代价提示、实际行动后果和终局评价。
可以自己探索，也可以选择人格倾向查看推荐或授权有限步数代行。
评分基于当前公开选项与已有观察；世界后果仍由真实 C0/K0 Session 结算。

Web 服务提供请求去重、版本校核与局内状态隔离。
`/api/health` 给出实际引擎路径、Git 版本、作者文件摘要与编译次数，便于核对连线。
桌面检查覆盖1280×720、1440×900、1920×1080；手机以纵向滚动使用，已有三尺寸布局检查。
运行和分享说明见 Web README；远程邀请使用限时私有 HTTPS 入口，公共主页提供视频与本地源码。

## 计时记录怎样阅读

2026-10-11 的浏览器短样本中，检查脚下、跨冰、邀请三次响应约0.87、1.27、1.59秒，
包含实际 NPC 行动与世界推进，首次 Compile 单列。
[2026-10-10 固定43项行动／1180条发生的历史报告](evidence/runtime-pair-2026-10-10/README.md)
约45秒，用于核对同输入的状态与来源摘要；两种计时对应不同负载。

展示标签只更新介绍、文档与获取入口，引擎执行代码承接 `a1843474f28880819a937613ed09fc266177207e`，
Web 应用代码承接 `715ebc7ad10cd3053b2d9f88d38b25a0070b8a3f`。
影片另保留[采集版本](showcase/introduction/film-v3/README.md)，可分别核查。
