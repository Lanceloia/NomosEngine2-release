const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {bind}=require('../../tools/bind_introduction_narration.cjs');
const root=path.resolve(__dirname,'../..');
const script=fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v6/SCRIPT.md'),'utf8');
const narration=fs.readFileSync(path.join(root,'docs/showcase/introduction/draft-v6/NARRATION.txt'),'utf8');
const directory=path.join(root,'docs/showcase/introduction/film-v7');
const alignment=JSON.parse(fs.readFileSync(path.join(directory,'alignment.json'),'utf8'));
const intervals=[];let cursor=0;
for(const pause of alignment.pauses){if(pause.start-cursor>.2)intervals.push({start:cursor,end:pause.start});cursor=pause.end;}
if(alignment.duration-cursor>.2)intervals.push({start:cursor,end:alignment.duration});

test('supplied audio preserves continuous sentence and M1 evidence cues',()=>{
  const {film}=bind(script,narration,intervals,alignment.duration);
  let cursor=0;
  for(const scene of film.scenes) {
    assert.equal(scene.start,cursor);
    for(const line of scene.lines){assert.equal(line.start,cursor);assert.ok(line.end>cursor);cursor=line.end;}
    assert.equal(scene.end,cursor);
  }
  assert.equal(cursor,319.44);
  assert.equal(film.scenes.find(s=>s.id==='adventure').lines.length,6);
  assert.equal(film.scenes.find(s=>s.id==='rescue').lines.length,10);
  assert.match(film.scenes.find(s=>s.id==='rescue').lines[5].text,/另一段记录/);
});
test('mismatched manuscript and invalid audio intervals fail',()=>{
  assert.throws(()=>bind(script,narration+'extra',intervals,319.44),/differ/);
  assert.throws(()=>bind(script,narration,[{start:4,end:2}],319.44),/intervals/);
  assert.throws(()=>bind(script,narration,[],NaN),/audio/);
});
test('timeline and supplied audio content hashes agree',()=>{
  const window={};vm.runInNewContext(fs.readFileSync(path.join(directory,'timeline.js'),'utf8'),{window});
  const {createHash}=require('node:crypto');
  for(const [key,bytes] of [['script_sha256',script],['narration_sha256',narration],['audio_sha256',fs.readFileSync(path.join(directory,'narration.mp3'))]]) {
    assert.equal(window.NOMOS_FILM[key],createHash('sha256').update(bytes).digest('hex'));
  }
  assert.equal(window.NOMOS_FILM.duration,alignment.duration);
});
test('browser uses the actual audio clock and all public dependencies exist',()=>{
  const renderer=fs.readFileSync(path.join(directory,'film.js'),'utf8');
  assert.match(renderer,/audio.currentTime/);assert.doesNotMatch(renderer,/performance.now\(/);
  assert.match(renderer,/await audio.play\(\)/);assert.match(renderer,/audio.pause\(\)/);
  assert.match(fs.readFileSync(path.join(directory,'index.html'),'utf8'),/id="audio" src="narration.mp3"/);
  const dependencies=JSON.parse(fs.readFileSync(path.join(directory,'dependencies.json'),'utf8'));
  for(const name of dependencies)assert.ok(fs.existsSync(path.join(directory,name)),name);
  assert.ok(!dependencies.some(s=>s.includes('manifest.json')));
});
