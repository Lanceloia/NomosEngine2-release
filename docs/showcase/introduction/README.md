# 让规则产生故事

首次认识 NomosEngine2，先看这支约三分钟的中文项目介绍，再查看实验录像。

[浏览器中文介绍入口](https://lanceloia.github.io/NomosEngine2-release/showcase/introduction/film-v1/index.html)：
点击开始观看，可暂停、拖动和选章；[真实规则编辑实验讲解](https://lanceloia.github.io/NomosEngine2-release/showcase/recording/narrated-v1/experiment.mp4)
展示实际命令与结果。
也可以下载下方视频文件，用本地播放器观看。

- [项目介绍视频](film-v1/introduction.mp4)：中文合成旁白、画内字幕、随讲解切换重点的架构与实验示意。
- [可暂停、拖动、选章的讲解页面](film-v1/index.html)：浏览器直接打开，点击「开始观看」；旁白文件须与网页保持同目录。
- [完整中文讲稿](film-v1/TRANSCRIPT.md)、[独立字幕](film-v1/subtitles.srt)、[作者分镜](storyboard.json)。
- 接着看[真实规则编辑实验的中文讲解版](../recording/narrated-v1/experiment.mp4)，或[原始分章回放](../recording/capture-v1/replay.html)。

`player.html` 是构建模板。在线使用上方 Pages 入口；GitHub 的源码预览不执行 HTML。下载后打开 `film-v1/index.html`，
或直接下载 MP4 用播放器观看。MP4 已包含音轨和画内字幕，不依赖外部字幕文件。

## 讲什么

先解释不预写剧情分支的 RPG/TRPG 沙盒动机，再介绍作者声明、C0、K0、T0 的职责。
用三组已有实验区分规则准入、结算后果和开局编辑；M1 说明规则组合的验证用途。
最后说明 LLM 主持人方向、当前尚未实现的能力，以及发起者和协作者的真实归因。

所有关系图和实验摘要均为**教学动画，不是游戏实录**。真实报告仍保留在原来的证据目录；
本次没有重跑世界、修改引擎、补造新证据，也不把概念图当 M1 的实际画面。
LLM 主持人管线明确属于未来愿景。语音是本机 Microsoft Huihui Desktop 合成，不是发起者的录音，
文本没有上传到语音服务。视频导出使用本机字体；在线页面另附约 120 KiB 的中文字体子集，
使缺少系统中文字体的浏览器也能阅读。[字体来源与 SIL OFL 许可](font/README.md)随页面提供。

## 核对证据

| 介绍中的实验 | 已有可检查来源 |
| --- | --- |
| 禁止自救，前九步相同，第十步拒绝且本步无写入 | [原录制记录与报告](../recording/README.md) |
| 全票一致改多数票，行动都获准但清晨后果不同 | [共同袭击实验](../wolf-vote/README.md) |
| 女巫 B 改 E、六席扩八席 | [人物与人数实验](../world-edits/README.md) |
| M1 有限规则组合与尚未覆盖范围 | [项目导览](../../PROJECT_TOUR.md)、[展示矩阵](../../SHOWCASE_MATRIX.md) |

`film-v1/manifest.json` 保存输入和输出摘要，`export.json` 保存浏览器检查、媒体导出和文件摘要。
它们用于核对字节，不是发行签名。字幕依据实际合成音频的段长生成；浏览器视频合成使用测得的
页面准备偏移，对齐精度为近似视频帧级。本轮旁白合成和导出依赖 Windows/WSL，不是引擎的安装依赖。

2026-10-11 在线发布补充：播放器加入本地中文字体及随附许可，音频、字幕、MP4 和时间线保持原样。
`film-v1/manifest.json` 与 `export.json` 保留原制作快照；此后网页与字体的变更由 Git 提交记录，
不改写历史摘要。再次制作时，构建工具会复制字体并将它纳入新摘要。

## 再制作

修改分镜后，构建到一个不存在的新目录，避免覆盖已分享的视频：

```bash
python tools/build_project_introduction.py /mnt/d/ne2-introduction-new
node tools/render_project_introduction.cjs /mnt/d/ne2-introduction-new \
  /path/to/playwright /path/to/full-ffmpeg /mnt/c/Windows/Fonts/NotoSansSC-VF.ttf
```

语音构建需要本机 Windows 的 `Microsoft Huihui Desktop` 及 `wslpath`。
视频导出需要 Playwright/Chromium 和支持 H.264、AAC 的完整 FFmpeg；工具使用两个编码线程。
这些是可选制作工具，不是 C0/K0/T0 的运行依赖。短检查只测讲稿、音轨时间线和播放器，不跑 M1 整局。
