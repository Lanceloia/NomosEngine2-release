/* Preserve sentence cues while binding a finalized storyboard to supplied audio. */
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {createHash} = require('node:crypto');
const {build} = require('./build_introduction_v4.cjs');
const {align} = require('./introduction_speech_timing.cjs');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

function bind(script, narration, intervals, duration) {
  const film = build(script);
  const normalize = text => text.replace(/\s+/g, '');
  if (normalize(film.scenes.map(s=>s.narration).join('')) !== normalize(narration)) throw Error('Script and narration differ.');
  if (!Number.isFinite(duration) || duration<=0 || !intervals.length) throw Error('Invalid decoded audio.');
  let end=0;
  for (const interval of intervals) {
    if (interval.start<end || interval.end<=interval.start || interval.end>duration) throw Error('Invalid speech intervals.');
    end=interval.end;
  }
  const timings=align(film.scenes.flatMap(s=>s.lines.map(l=>normalize(l.text))),intervals);
  const boundaries=timings.map((s,i)=>i?(s.start+timings[i-1].end)/2:0);
  boundaries.push(duration);
  let cursor=0;
  const scenes=film.scenes.map(scene=>{
    const first=cursor;
    const lines=scene.lines.map(()=>{
      const index=cursor++;
      return {text:timings[index].text,start:boundaries[index],end:boundaries[index+1]};
    });
    return {...scene,start:boundaries[first],end:boundaries[cursor],lines};
  });
  return {film:{...film,kind:'Narrated project introduction',duration,scenes},timings};
}

function main() {
  const [draft,output,voice,ffmpeg]=process.argv.slice(2);
  if (!ffmpeg) throw Error('Usage: node tools/bind_introduction_narration.cjs DRAFT OUTPUT VOICE_MP3 FFMPEG');
  if (fs.existsSync(path.join(output,'timeline.js'))) throw Error('Timeline exists; choose a new candidate.');
  const script=fs.readFileSync(path.join(draft,'SCRIPT.md'),'utf8');
  const narration=fs.readFileSync(path.join(draft,'NARRATION.txt'),'utf8');
  const audio=fs.readFileSync(voice);
  const decoded=spawnSync(ffmpeg,['-hide_banner','-nostdin','-threads','2','-i',voice,
    '-af','silencedetect=noise=-34dB:duration=0.35','-ac','1','-ar','44100','-f','s16le','pipe:1'],
    {timeout:30000,maxBuffer:64*1024*1024});
  if(decoded.status!==0) throw Error(decoded.stderr?.toString()||String(decoded.error));
  const duration=decoded.stdout.length/(44100*2);
  const pauses=[...decoded.stderr.toString().matchAll(/silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)/g)]
    .map(m=>({start:Number(m[1]),end:Number(m[2])}));
  const intervals=[];let cursor=0;
  for(const pause of pauses) {
    if(pause.start-cursor>.2)intervals.push({start:cursor,end:pause.start});
    cursor=pause.end;
  }
  if(duration-cursor>.2)intervals.push({start:cursor,end:duration});
  const {film,timings}=bind(script,narration,intervals,duration);
  const hashes={script_sha256:digest(script),narration_sha256:digest(narration),audio_sha256:digest(audio)};
  Object.assign(film,hashes);
  fs.mkdirSync(output,{recursive:true});
  fs.writeFileSync(path.join(output,'narration.mp3'),audio);
  fs.writeFileSync(path.join(output,'alignment.json'),JSON.stringify({
    method:'Monotone duration-weighted speech-pause partition; not speech recognition. Listening verification pending.',
    ...hashes,duration,pauses,sentenceTiming:timings},null,2)+'\n');
  fs.writeFileSync(path.join(output,'timeline.js'),'window.NOMOS_FILM = '+JSON.stringify(film,null,2).replaceAll('<','\\u003c')+';\n');
  console.log(JSON.stringify({duration,sentences:timings.length,speech_intervals:intervals.length,
    scenes:film.scenes.map(s=>({id:s.id,start:s.start,end:s.end}))},null,2));
}
if(require.main===module)main();
module.exports={bind};
