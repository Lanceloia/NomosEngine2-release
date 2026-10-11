# 在线讲解字体

`nomos-introduction-sc.woff2` 是 Noto Sans CJK SC 的页面用字子集，按 SIL Open Font License 1.1 分发。
原字体版权：© 2014–2021 Adobe (http://www.adobe.com/)。完整许可见 [OFL.txt](OFL.txt)。
字体中的原版权元数据保留；修改后的字体族名为 `Nomos Introduction SC`。

2026-10-11 使用 fontTools 4.66.1，从 M1 已随附许可的 `m1-noto-sans-sc-fallback.woff`
提取当前 `film-v1/index.html` 所需字符，包含 392 个中文字符。输出 122740 字节。
这一静态子集服务于当前讲解；新增文案时应重新检查字形覆盖并更新子集。

| 文件 | SHA256 |
| --- | --- |
| 输入 WOFF | `ba443256a8c7975272a3c23611886522afd6ba09485ac09a3b4d8b99b081d221` |
| 输出 WOFF2 | `031a64dc9149db27592c1653369a0d5122794c727029b94aaaef32911bb0181d` |

构建工具把本目录复制到输出播放器的 `font/`。浏览器从页面同源加载，无需字体 CDN。
