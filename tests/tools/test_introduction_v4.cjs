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
