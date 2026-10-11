# 声明世界，让行动形成故事

[新版字幕动画](index.html)与[无声 MP4 预演](introduction.mp4)。新配音待定稿后录制。

本轮补足 M1《冰焰解冻之旅》的冰宫目标、有限充能取舍、观察和居民回应，
用两段明确区分的真实记录说明下一步选择如何获得依据。
C0/K0 分工逐句解释，T0 从故事创作动机连接到当前见证检查和后续规则探索。

- [讲稿](../draft-v6/SCRIPT.md)
- [可复制完整口播](../draft-v6/NARRATION.txt)
- [分镜与素材依据](../draft-v6/DIRECTION.md)
- [核对与审阅](REVIEW.md)
- [上一版](../film-v5/README.md)

```bash
node tools/build_introduction_v4.cjs v6
node --test tests/tools/test_introduction_v4.cjs
node tools/produce_introduction_v4.cjs PLAYWRIGHT_MODULE FFMPEG v6
```

从仓库根运行。导出器不覆盖已有冻结MP4；一个浏览器、两编码线程。
预演时间按阅读速度估计，录音后再对齐；没有请求或生成新语音。
完整浏览器、关键M1画面与导出检查见 [checks](checks.json)。
保留原始实验、M1实录、改编署名与字体许可。
