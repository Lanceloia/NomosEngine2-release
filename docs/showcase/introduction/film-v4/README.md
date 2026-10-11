# 声明世界，让行动形成故事

当前为[新版字幕动画](index.html)与[无声 MP4 预演](introduction.mp4)，
按阅读节奏估计时间。新版录音待提供，收到后再制作有声版。

讲稿先提出自由探索的创作问题，再介绍 C0/K0/T0 为何形成，
用狼人杀和 M1 检验规则怎样真正进入运行。

- [讲稿](../draft-v4/SCRIPT.md)
- [可直接复制的完整口播](../draft-v4/NARRATION.txt)
- [分镜与制作边界](../draft-v4/DIRECTION.md)
- [M1 真实素材的版本、内容与署名](../film-v3/README.md)

实验图示和 M1 原始录像沿用已有证据，本轮没有重新运行世界。
第三方 M1 冒险、字体的署名与许可继续保留。
旧有声版见 [film-v3](../film-v3/README.md)，其讲稿属于校准前的历史版本。

## 制作与检查

```bash
node tools/build_introduction_v4.cjs
node --test tests/tools/test_introduction_v4.cjs
node tools/produce_introduction_v4.cjs PLAYWRIGHT_MODULE FFMPEG
```

从仓库根运行，替换本机依赖路径；已有 MP4 时导出器拒绝覆盖。
单浏览器、编码两线程，逐帧直接送入管道，结束或出错均关闭自己的进程。
播放控制、字幕、两桌面尺寸24张预览及视频解码记录见 `checks.json`。
本轮不运行引擎世界，旧 M1 展示服务保持原样。
