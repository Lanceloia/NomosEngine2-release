/* Follow one change at a time; recorded M1 media supplies all game imagery. */
(() => {
  'use strict';
  const film = window.NOMOS_FILM, media = window.M1_CAPTURE;
  if (new URLSearchParams(location.search).has('export')) document.body.classList.add('export');
  const canvas = document.querySelector('#canvas'), ctx = canvas.getContext('2d');
  const audio = document.querySelector('#audio'), slider = document.querySelector('#seek');
  const chapter = document.querySelector('#chapter'), playButton = document.querySelector('#play');
  const C = { bg:'#111214', text:'#f3f4f5', muted:'#a6afb9', line:'#555e69', green:'#7cdac7', gold:'#efcd7b', pink:'#efa5b9', blue:'#a0bff0', red:'#f39c95' };
  const clamp = n => Math.max(0, Math.min(1, n)), ease = p => p * p * (3 - 2 * p);
  const step = (p, start, width=.14) => ease(clamp((p - start) / width));
  const lerp = (a, b, p) => a + (b - a) * ease(clamp(p));
  const images = {}, videos = {}; let mediaFailure = null;
  const ready = Promise.all(Object.entries(media.images).map(([name, file]) => new Promise((resolve, reject) => {
    const image = new Image(); images[name] = image;
    image.onload = resolve; image.onerror = () => reject(Error('Missing image: ' + file)); image.src = file;
  })).concat(Object.entries(media.videos).map(([name, item]) => new Promise((resolve, reject) => {
    const video = document.createElement('video'); videos[name] = video;
    video.muted = true; video.preload = 'auto'; video.playsInline = true;
    video.onloadeddata = resolve; video.onerror = () => reject(Error('Missing video: ' + item.file)); video.src = item.file;
  }))));
  ready.catch(error => { mediaFailure = String(error); document.querySelector('#status').textContent = mediaFailure; });
  let mediaReady = false, position = 0, playing = false, pending = false, fault = null;
  ready.then(() => { mediaReady = true; update(); }).catch(report);
  const duration = () => Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : film.duration;
  const sceneAt = t => film.scenes.find(s => t >= s.start && t < s.end) || film.scenes.at(-1);
  const phaseAt = (scene, t) => clamp((t - scene.start) / (scene.end - scene.start));
  const clock = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

  function text(value, x, y, size=28, color=C.text, alpha=1, align='center', maxWidth=1280) {
    ctx.save(); ctx.globalAlpha = alpha; ctx.textAlign = align; ctx.textBaseline = 'middle'; ctx.fillStyle = color;
    let fitted = size;
    do { ctx.font = `${size >= 40 ? 600 : 400} ${fitted}px FilmChinese,sans-serif`; if (ctx.measureText(value).width <= maxWidth) break; fitted--; } while (fitted > 16);
    ctx.fillText(value, x, y); ctx.restore();
  }
  function line(x1, y1, x2, y2, color=C.line, alpha=1, dashed=false) {
    ctx.save(); ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash(dashed ? [7, 8] : []);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.restore();
  }
  function circle(x, y, r, color=C.green, alpha=1, filled=false) {
    ctx.save(); ctx.globalAlpha = alpha; ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = filled ? color : C.bg; ctx.fill(); ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
  }
  function node(label, x, y, color=C.green, alpha=1, r=48) {
    circle(x, y, r, color, alpha); text(label, x, y, 25, color, alpha, 'center', r * 1.8);
  }
  function travel(x1, y1, x2, y2, p, color=C.green, alpha=1) {
    line(x1, y1, x2, y2, color, alpha); circle(lerp(x1, x2, p), lerp(y1, y2, p), 6, color, alpha, true);
  }
  function title(value, subtitle='') { text(value, 720, 157, 42); if (subtitle) text(subtitle, 720, 215, 23, C.muted); }
  function sourceNote(value) { text(value, 1376, 703, 18, C.muted, 1, 'right', 1250); }
  function fit(rectangle, destination) {
    const scale=Math.min(destination[2]/rectangle[2], destination[3]/rectangle[3]);
    const width=rectangle[2]*scale, height=rectangle[3]*scale;
    return [destination[0]+(destination[2]-width)/2, destination[1]+(destination[3]-height)/2, width, height];
  }
  function image(name, destination, crop) {
    const source = images[name]; if (!source?.naturalWidth) return;
    const rectangle = crop || [0, 0, source.naturalWidth, source.naturalHeight];
    ctx.drawImage(source, ...rectangle, ...fit(rectangle,destination));
  }
  function video(name, destination, crop) {
    const source = videos[name]; if (!source || source.readyState < 2) return;
    const rectangle=crop || [0, 0, source.videoWidth, source.videoHeight];
    ctx.drawImage(source, ...rectangle, ...fit(rectangle,destination));
  }
  function origin(p) {
    title('NomosEngine2', '游戏规则原型 · 设计与验证');
    node('规则', 480, 407, C.gold, 1, 72);
    travel(555, 407, 905, 407, step(p, .04, .28)); node('原型', 980, 407, C.green, step(p, .13), 72);
    text('写下想法', 480, 520, 27, C.gold); text('试运行 · 检查 · 再修改', 980, 520, 27, C.green, step(p, .18));
    const a = step(p, .50); text('从桌上角色扮演 TRPG 出发', 720, 610, 30, C.blue, a);
    const x = lerp(440, 1000, clamp((p - .6) / .4)); circle(x, 640, 7, C.blue, a, true);
    text('玩家的选择，进入规则世界', 720, 683, 24, C.muted, a);
  }
  function history(p) {
    title('作者改了规则，实际后果能否跟着改变？');
    node('声明', 330, 350, C.gold, 1, 62); node('结果', 1110, 440, C.green, 1, 62);
    travel(400, 350, 1040, 440, step(p, .05, .25), C.gold);
    const a = step(p, .28); node('流程', 330, 550, C.pink, a, 62); travel(400, 550, 1040, 440, step(p, .33, .26), C.pink, a);
    text('规则藏在专用脚本中', 800, 580, 27, C.pink, a); text('把表达、执行与验证的职责分开', 720, 670, 30, C.green, step(p, .72));
  }
  function pipeline(p) {
    title('规则声明，怎样成为可运行的原型？');
    node('声明', 190, 335, C.gold, 1, 55);
    const a = step(p, .15); node('C0', 500, 335, C.gold, a, 58); text('编译器', 500, 425, 28, C.gold, a);
    travel(250, 335, 438, 335, step(p, .12), C.gold, a);
    const b = step(p, .3); node('Program', 835, 335, C.green, b, 70); text('规则程序', 835, 425, 27, C.green, b);
    travel(562, 335, 758, 335, step(p, .25), C.green, b);
    const c = step(p, .4); text('Assets · 人物、位置、资源', 1160, 285, 24, C.blue, c);
    travel(1155, 315, 1085, 493, step(p, .44), C.blue, c);
    const d = step(p, .49); node('K0', 1035, 545, C.green, d, 62); text('结算内核 · 游玩局', 1035, 635, 27, C.green, d);
    travel(835, 405, 982, 492, step(p, .48), C.green, d); text('行动', 650, 545, 26, C.text, d); travel(710, 545, 965, 545, step(p, .57), C.blue, d);
    const e = step(p, .69); text('状态变化', 1280, 505, 26, C.green, e); text('发生记录', 1280, 590, 26, C.green, e);
    travel(1103, 526, 1192, 506, step(p, .69), C.green, e); travel(1103, 564, 1192, 590, step(p, .69), C.green, e);
    if (p > .86) text('当前态核验，结算与记录一起发布', 450, 670, 26, C.muted, step(p, .85));
  }
  function witness(p) {
    title('T0 · 给定路线，另开一局实际检查');
    text('同一 Program + Assets', 720, 282, 28, C.gold);
    const a = step(p, .13); line(720, 316, 360, 400, C.line, a); line(720, 316, 1060, 400, C.blue, a);
    node('K0', 360, 470, C.muted, a, 62); text('游玩局', 360, 580, 27, C.muted, a);
    node('K0', 1060, 470, C.green, a, 62); text('独立验证局', 1060, 580, 27, C.green, a);
    const b = step(p, .25); node('T0', 730, 470, C.blue, b, 58); travel(795, 470, 990, 470, step(p, .38), C.blue, b);
    text('给定行动路线', 650, 365, 24, C.blue, b); travel(660, 395, 705, 410, step(p, .3), C.blue, b);
    const c = step(p, .6); text('检查报告', 730, 625, 30, C.blue, c); line(730, 533, 730, 587, C.blue, c);
    text('在哪一步？  候选 / 准入 / 结算', 730, 680, 24, C.muted, c);
  }
  function admission(p) {
    title('第一组：只增加“女巫不能救自己”');
    text('原规则', 370, 280, 30, C.green); text('新增自救限制', 1060, 280, 30, C.pink, step(p, .22));
    for (const x of [370, 1060]) {
      text('相同开局 · 相同请求', x, 365, 26, C.muted);
      for (let i=0; i<9; i++) circle(x-108+i*27, 435, 5, C.green, step(p, .32+i*.015), true);
    }
    text('第10步 · B 提交救自己', 720, 510, 31, C.text, step(p, .5));
    const a = step(p, .65); text('发布行动与后果', 370, 615, 30, C.green, a);
    text('救人候选仍在', 1060, 562, 25, C.muted, a); text('K0 拒绝 · 本步无写入', 1060, 615, 30, C.red, a);
    sourceNote('保存实验结果图示');
  }
  function vote(p) {
    title('第二组：相同选择，清晨结算不同');
    text('投票者', 175, 305, 23, C.muted);
    const xs = [430, 720, 1010], labels = ['C', 'D', 'F'];
    xs.forEach((x, i) => node(labels[i], x, 305, C.blue, step(p, .07+i*.04), 32));
    text('目标', 175, 423, 23, C.muted); node('F', 575, 423, C.green, step(p, .18), 34); node('E', 1000, 423, C.pink, step(p, .18), 34);
    travel(430, 342, 559, 384, step(p, .19), C.blue, step(p, .19)); travel(720, 342, 592, 384, step(p, .24), C.blue, step(p, .24));
    travel(1010, 342, 1000, 384, step(p, .29), C.pink, step(p, .29));
    const a = step(p, .4); text('全票一致', 370, 514, 28, C.gold, a); text('多数票', 1060, 514, 28, C.gold, a);
    text('两版各10次提交，全部获准', 720, 573, 26, C.green, step(p, .57));
    const b = step(p, .73); text('清晨：无人死亡', 370, 640, 31, C.green, b); text('清晨：F 死亡', 1060, 640, 31, C.red, b);
    sourceNote('保存实验结果图示');
  }
  function configuration(p) {
    title('第三组：已有规则，装配不同人物');
    text('两份开局对照', 720, 250, 24, C.muted);
    node('B', 410, 365, C.pink, 1, 48); node('E', 1030, 365, C.pink, step(p, .12), 48);
    travel(465, 365, 970, 365, step(p, .14, .2), C.pink); text('职业 + 开局药水', 720, 305, 28, C.pink);
    text('通知 · 选项 · 行动来源', 720, 455, 27, C.text, step(p, .28));
    for (let i=0; i<8; i++) node('ABCDEFGH'[i], 335+i*110, 570, i<6?C.blue:C.green, i<6?step(p, .46):step(p, .62), 31);
    text('6席 → 8席', 445, 652, 28, C.blue, step(p, .55)); text('G 的本地视图与真实投票', 985, 652, 27, C.green, step(p, .68));
    sourceNote('保存实验结果图示');
  }
  function adventure(p) {
    title('M1 · 冰焰解冻之旅', '从规则对照，进入冒险原型');
    if (p < .43) {
      image('opening', [175, 265, 1090, 390], media.crops.opening);
    } else image('map', [175, 265, 1090, 390], media.crops.map);
    text('Thawed Through the Everflame · Pepijn / Willem-Jan', 720, 677, 20, C.gold);
    sourceNote('2025 一页地下城竞赛参赛作品 · CC BY-SA 4.0 · Nomos 有限改编');
  }
  function rescue(p) {
    const resource = p < .55;
    title(resource ? '把永焰充能用在哪里？' : '居民如何回应邀请？');
    if (resource) {
      if (p < .35) video('resource', [120, 255, 1200, 420], media.crops.resourceVideo);
      else if (p < .44) image('thawAfter', [120, 280, 1200, 360], media.crops.chargeAfter);
      else image('thawAfter', [120, 280, 1200, 360], media.crops.floorAfter);
      text(media.resourceCaption, 720, 222, 26, C.gold);
    } else {
      if (p < .87) video('reply', [120, 255, 1200, 420], media.crops.replyVideo);
      else image('replyAfter', [120, 255, 1200, 420], media.crops.replyAfter);
      text('发出邀请 → 居民自主答复 → 玩家听见', 720, 222, 25, C.green);
    }
    sourceNote('当前 M1 Web · 实际浏览器交互');
  }
  function combination(p) {
    title('不同世界规则，同一套原型工具');
    node('狼人杀', 300, 360, C.pink, 1, 65); node('M1', 300, 550, C.blue, 1, 65);
    node('C0', 770, 445, C.gold, 1, 62); node('K0', 1160, 445, C.green, step(p, .25), 62);
    travel(375, 360, 700, 425, step(p, .1), C.pink); travel(375, 550, 700, 465, step(p, .2), C.blue);
    travel(840, 445, 1090, 445, step(p, .35), C.green); text('检查组合规则的实际后果', 880, 640, 29, C.green, step(p, .56));
  }
  function future(p) {
    title('让语言模型协助创作与主持', '未来方向');
    [['草拟内容', C.gold], ['提议行动', C.blue], ['讲述经历', C.pink]].forEach(([label, color], i) => {
      const x=320+i*400, a=step(p, .04+i*.22); node(label, x, 365, color, a, 70);
      text(['作者声明', 'K0 核验与结算', '实际发生记录'][i], x, 560, 27, C.green, a);
      if (i === 2) travel(x, 510, x, 445, step(p, .12+i*.22), color, a);
      else travel(x, 445, x, 510, step(p, .12+i*.22), color, a);
    });
    text('围绕同一个规则世界协作', 720, 664, 30, C.green, step(p, .78));
  }
  function credits(p) {
    title('NomosEngine2', '让想法成为可运行、可检查的游戏原型');
    text('Lanceloia', 440, 350, 40, C.gold); text('Codex 协作者', 1000, 350, 40, C.blue, step(p, .18));
    text('愿景 · 语义 · 反例 · 验收', 440, 425, 26, C.gold); text('后期主要代码', 1000, 425, 26, C.blue, step(p, .18));
    travel(350, 545, 1100, 545, step(p, .4, .45)); text('试写规则  →  运行原型  →  检查结果', 720, 600, 30, C.green, step(p, .4));
    text('github.com/Lanceloia/NomosEngine2-release', 720, 670, 26, C.muted, step(p, .69));
  }
  const renderers = { origin, history, pipeline, witness, admission, vote, configuration, adventure, rescue, combination, future, credits };
  function draw(t, captionToCanvas=false) {
    const scene=sceneAt(t), p=phaseAt(scene, t);
    ctx.fillStyle=C.bg; ctx.fillRect(0, 0, 1440, 810);
    text('NomosEngine2', 64, 53, 23, C.text, 1, 'left'); text(scene.title, 1376, 53, 20, C.muted, 1, 'right'); line(64, 91, 1376, 91, '#33383d');
    renderers[scene.id](p);
    const caption=scene.lines.find(l => t>=l.start && t<l.end);
    document.querySelector('#subtitle').textContent=caption?.text || '';
    if (captionToCanvas && caption) {
      ctx.font='28px FilmChinese,sans-serif'; const rows=[]; let row='';
      for (const character of caption.text) { if (row && ctx.measureText(row+character).width>1240) { rows.push(row); row=''; } row+=character; }
      if (row) rows.push(row); if (rows.length>2) throw Error('Export caption exceeds two lines.');
      rows.forEach((value,i) => text(value,720,rows.length===1?754:739+i*38,28));
    }
    chapter.value=scene.id; return { scene:scene.id, progress:p, subtitle:caption?.text || '' };
  }
  async function prepare(t) {
    await ready; const scene=sceneAt(t), p=phaseAt(scene,t);
    if (scene.id !== 'rescue') return;
    const name=p<.55?'resource':'reply', data=media.videos[name], element=videos[name];
    const relative=p<.55?p*(scene.end-scene.start):(p-.55)*(scene.end-scene.start);
    const target=Math.min(data.end, data.start+relative, element.duration-.03);
    if (Math.abs(element.currentTime-target)<.025) return;
    await new Promise((resolve,reject) => {
      const timer=setTimeout(() => { cleanup(); reject(Error('Video seek timed out: '+name)); },5000);
      const done=() => { cleanup(); resolve(); };
      const cleanup=() => { clearTimeout(timer); element.removeEventListener('seeked',done); };
      element.addEventListener('seeked',done,{once:true}); element.currentTime=target;
    });
  }
  function update() {
    draw(position); slider.max=duration(); slider.value=position;
    document.querySelector('#time').textContent=`${clock(position)} / ${clock(duration())}`; playButton.textContent=playing?'暂停':'播放';
  }
  function pause() { playing=false; audio.pause(); update(); }
  async function play() { if (position>=duration()) position=0; audio.currentTime=position; await audio.play(); playing=true; update(); }
  function jump(t) { position=Math.max(0,Math.min(duration(),t)); audio.currentTime=position; prepare(position).then(update).catch(report); update(); }
  function report(error) { fault=String(error); pause(); document.querySelector('#status').textContent=String(error); }
  playButton.onclick=() => playing?pause():play().catch(report); document.querySelector('#restart').onclick=() => { jump(0); play().catch(report); };
  slider.oninput=e => jump(Number(e.target.value)); film.scenes.forEach(s => chapter.add(new Option(s.title,s.id)));
  chapter.onchange=() => jump(film.scenes.find(s=>s.id===chapter.value).start);
  audio.onloadedmetadata=() => { if (Math.abs(duration()-film.duration)>.1) return report(Error('Audio timing differs from this storyboard')); update(); };
  audio.onerror=() => report(Error('无法解码配音')); audio.onended=() => { position=duration(); pause(); };
  async function tick() {
    if (playing && !pending) { pending=true; position=audio.currentTime; try { await prepare(position); update(); } catch(error) { report(error); } finally { pending=false; } }
    requestAnimationFrame(tick);
  }
  window.animatic={film,draw,prepare,play,pause,seek:jump,get duration(){return duration();},get imageReady(){return mediaReady&&!mediaFailure;},get time(){return position;},get playing(){return playing;},get fault(){return fault;}};
  document.fonts.ready.then(() => { update(); requestAnimationFrame(tick); });
  window.addEventListener('pagehide',() => { audio.pause(); Object.values(videos).forEach(v=>v.pause()); });
})();
