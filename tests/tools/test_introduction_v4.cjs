const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {build,IDS} = require('../../tools/build_introduction_v4.cjs');
const root = path.resolve(__dirname,'../..');
const script = fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v4/SCRIPT.md'),'utf8');

test('positioning precedes tools and concrete consumers',()=> {
  const film=build(script);
  assert.deepEqual(film.scenes.map(s=>s.id),IDS);
  assert.match(film.scenes[0].narration,/剧情之外/);
  assert.match(film.scenes[1].narration,/主持人的判断与玩家即兴/);
  assert.match(film.scenes[2].narration,/C0.*编译器/);
  assert.match(film.scenes.at(-1).narration,/作者创作世界允许发生什么/);
});
test('every caption has continuous positive preview timing',()=> {
  const film=build(script); let cursor=0;
  for(const scene of film.scenes) {
    assert.equal(scene.start,cursor);
    for(const line of scene.lines) {
      assert.equal(line.start,cursor); assert.ok(line.end>line.start); cursor=line.end;
    }
    assert.equal(scene.end,cursor);
  }
  assert.equal(film.duration,cursor);
});
test('renderer has exactly the declared scenes and no stale audio',()=> {
  const page=fs.readFileSync(path.join(root,'docs/showcase/introduction/film-v4/index.html'),'utf8');
  const renderer=fs.readFileSync(path.join(root,'docs/showcase/introduction/film-v4/film.js'),'utf8');
  for(const id of IDS)assert.ok(renderer.includes(`function ${id}(p)`));
  assert.ok(!page.includes('narration.mp3')); assert.ok(!renderer.includes('audio.currentTime'));
  assert.match(page,/新配音待录制/);
});
test('missing or reordered chapter fails',()=> {
  assert.throws(()=>build(script.replace('## history','## wrong')),/ordered storyboard/);
});

test('story-first revision distinguishes rule exploration from current witness checking',()=> {
  const script=fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v5/SCRIPT.md'),'utf8');
  const film=build(script), witness=film.scenes.find(s=>s.id==='witness');
  assert.match(witness.narration,/先写出一个精彩的故事/);
  assert.match(witness.narration,/目前.*行动见证检查/);
  assert.match(witness.narration,/规则推导.*接下来/);
  assert.match(witness.narration,/玩家仍能/);
  const renderer=fs.readFileSync(path.join(root,'docs/showcase/introduction/film-v5/film.js'),'utf8');
  for(const id of IDS)assert.ok(renderer.includes(`function ${id}(p)`));
  assert.match(renderer,/规则探索.*后续方向/);
  assert.match(renderer,/行动见证检查.*当前能力/);
});

test('recording candidate gives M1 a complete situation and separate real records',()=> {
  const script=fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v6/SCRIPT.md'),'utf8');
  const film=build(script), before=build(fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v5/SCRIPT.md'),'utf8'));
  const m1=film.scenes.filter(s=>['adventure','rescue'].includes(s.id));
  const m1Time=m1.reduce((n,s)=>n+s.end-s.start,0);
  const oldTime=before.scenes.filter(s=>['adventure','rescue'].includes(s.id)).reduce((n,s)=>n+s.end-s.start,0);
  assert.ok(m1Time>oldTime*1.8);assert.ok(m1Time>90&&m1Time<130);
  assert.match(m1[0].narration,/中断仪式.*帮助居民离开.*外岸/);
  assert.match(m1[0].narration,/充能有限/);
  assert.match(m1[1].narration,/另一段记录/);
  assert.match(m1[1].narration,/实际听到.*准备好/);
  assert.match(m1[1].narration,/察觉.*舞厅入口/);
  assert.doesNotMatch(m1[1].narration,/已经获救|成功营救/);
  assert.match(film.scenes.find(s=>s.id==='witness').narration,/现阶段.*同一份 C0 产物/);
});

test('recording candidate keys media to captions and waits for seek completion',()=> {
  const renderer=fs.readFileSync(path.join(root,'docs/showcase/introduction/film-v6/film.js'),'utf8');
  const producer=fs.readFileSync(path.join(root,'tools/produce_introduction_v4.cjs'),'utf8');
  for(const id of IDS)assert.ok(renderer.includes(`function ${id}(p`));
  assert.match(renderer,/cueAt\(sceneAt\(t\),t\)/);
  assert.match(renderer,/async function jump/);
  assert.match(renderer,/prepared\.then\(\(\)=>prepareFrame\(t\)\)/);
  assert.match(renderer,/同一组投票/);
  assert.match(producer,/await window.animatic.seek\(t\)/);
  assert.match(producer,/evidenceSamples/);
  assert.ok(!fs.readFileSync(path.join(root,'docs/showcase/introduction/film-v6/index.html'),'utf8').includes('narration.mp3'));
});
