/* Export a narrated educational presentation; never simulate the game world. */
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

function ffmpeg(binary, args) {
  const result = spawnSync(binary, ['-hide_banner', ...args], { encoding: 'utf8', timeout: 120000 });
  if (result.status !== 0) throw Error(`FFmpeg failed: ${result.stderr || result.error}`);
  return result.stderr;
}
function duration(binary, file) {
  const result = spawnSync(binary, ['-hide_banner', '-i', file], { encoding: 'utf8', timeout: 10000 });
  const match = result.stderr?.match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
  if (!match) throw Error(`Cannot inspect duration: ${file}`);
  return Number(match[1])*3600 + Number(match[2])*60 + Number(match[3]);
}
async function main() {
  const [directory, playwrightModule, ffmpegBinary, fontFile] = process.argv.slice(2);
  if (!directory || !playwrightModule || !ffmpegBinary) throw Error('Usage: node tools/render_project_introduction.cjs DIRECTORY PLAYWRIGHT_MODULE FFMPEG [FONT_FILE]');
  const root = path.resolve(directory);
  const productNames = ['introduction.mp4', 'poster.png', 'export.json', '.video'];
  if (productNames.some(name => fs.existsSync(path.join(root,name)))) throw Error('Export artifacts already exist; use a new presentation directory.');
  const reservation = path.join(root, '.export.lock');
  const lock = fs.openSync(reservation,'wx');
  let browser;
  try {
    if (productNames.some(name => fs.existsSync(path.join(root,name)))) throw Error('Artifacts appeared after reservation.');
    const { chromium } = require(playwrightModule);
    browser = await chromium.launch({ args: ['--allow-file-access-from-files', '--autoplay-policy=no-user-gesture-required'] });
    const context = await browser.newContext({ viewport: { width:1440,height:810 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror',error=>errors.push(String(error)));
    async function load(target) {
      await target.goto(pathToFileURL(path.join(root,'index.html')).href);
      if (fontFile) await target.addStyleTag({content:`@font-face{font-family:IntroChinese;src:url('${pathToFileURL(path.resolve(fontFile)).href}');}body{font-family:IntroChinese,sans-serif;}`});
      await target.evaluate(()=>document.fonts.ready);
      await target.waitForFunction(()=>document.querySelector('audio').readyState>=2);
    }
    await load(page);
    const film = await page.evaluate(()=>window.introduction.film);
    await page.click('#begin');
    await page.waitForTimeout(250);
    const initialProgress = await page.evaluate(()=>document.querySelector('audio').currentTime);
    if (initialProgress<=0) throw Error('Narration did not start after click.');
    await page.click('#play');
    const paused = await page.evaluate(()=>document.querySelector('audio').paused);
    if (!paused) throw Error('Pause control did not pause narration.');
    const samples=[];
    for(let i=0;i<film.scenes.length;i++) {
      for(let j=0;j<film.scenes[i].lines.length;j++) {
        const line=film.scenes[i].lines[j];
        await page.evaluate(t=>window.introduction.seek(t),line.start+0.1);
        await page.waitForTimeout(600);
        const geometry=await page.evaluate(()=>({
          overflow:document.documentElement.scrollWidth>innerWidth || document.documentElement.scrollHeight>innerHeight,
          diagramOverlap:document.querySelector('#diagram').getBoundingClientRect().bottom>document.querySelector('#subtitle').getBoundingClientRect().top,
          subtitle:document.querySelector('#subtitle').textContent,
          active:document.querySelector('#diagram .active')!==null,
        }));
        if(geometry.overflow || geometry.diagramOverlap || geometry.subtitle!==line.text || !geometry.active) throw Error(`Unreadable scene ${i}/${j}: ${JSON.stringify(geometry)}`);
        const image=`scene-${String(i+1).padStart(2,'0')}-${j+1}.png`;
        await page.screenshot({path:path.join(root,image)});
        samples.push({scene:film.scenes[i].id,line:j,image,...geometry});
      }
    }
    await page.selectOption('#chapter','7');
    await page.waitForFunction(title=>document.querySelector('#title').textContent===title,film.scenes[7].title,{timeout:5000});
    await page.click('#restart');
    if(await page.evaluate(()=>document.querySelector('audio').currentTime)>1) throw Error('Restart failed.');
    await page.click('#play');
    for(const size of [{width:1280,height:720},{width:1920,height:1080}]) {
      await page.setViewportSize(size);
      for(const index of [3,5,10]) {
        await page.evaluate(t=>window.introduction.seek(t),film.scenes[index].lines[1].start+0.1);
        await page.waitForTimeout(100);
        const bad=await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight||document.documentElement.scrollWidth>innerWidth||document.querySelector('#diagram').getBoundingClientRect().bottom>document.querySelector('#subtitle').getBoundingClientRect().top);
        if(bad) throw Error(`Responsive overlap ${size.width}/${index}`);
      }
    }
    fs.copyFileSync(path.join(root,'scene-01-1.png'),path.join(root,'poster.png'));
    await context.close();
    const videoContext=await browser.newContext({viewport:{width:1440,height:810},recordVideo:{dir:path.join(root,'.video'),size:{width:1440,height:810}}});
    const videoPage=await videoContext.newPage();
    videoPage.on('pageerror',error=>errors.push(String(error)));
    await load(videoPage);
    const start=Date.now();
    await videoPage.click('#begin');
    await videoPage.waitForFunction(()=>window.introduction.ended,null,{timeout:(film.duration+20)*1000});
    await videoPage.waitForTimeout(350);
    const elapsed=(Date.now()-start)/1000;
    const video=videoPage.video();
    await videoPage.close();
    const raw=path.join(root,'.video','silent.webm');
    await video.saveAs(raw);
    await videoContext.close();
    const videoSeconds=duration(ffmpegBinary,raw);
    const lead=Math.max(0,videoSeconds-elapsed);
    ffmpeg(ffmpegBinary,['-i',raw,'-itsoffset',String(lead),'-i',path.join(root,'narration.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','2','-preset','fast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart','-t',String(videoSeconds),path.join(root,'introduction.mp4')]);
    // Decode both streams, not just inspect their headers.
    const decode=ffmpeg(ffmpegBinary,['-i',path.join(root,'introduction.mp4'),'-map','0:v:0','-map','0:a:0','-f','null','-']);
    if(!decode.includes('Audio: aac') || !decode.includes('Video: h264')) throw Error('Missing playable audio/video streams.');
    const volume=ffmpeg(ffmpegBinary,['-i',path.join(root,'introduction.mp4'),'-map','0:a:0','-af','volumedetect','-f','null','-']);
    const maximum=volume.match(/max_volume: ([-\d.]+) dB/);
    if(!maximum || Number(maximum[1]) < -50) throw Error('Narration track is silent or inaudible.');
    if(errors.length)throw Error(errors.join('\n'));
    fs.rmSync(path.join(root,'.video'),{recursive:true});
    const artifacts=['index.html','narration.wav','subtitles.srt','timeline.json','introduction.mp4','poster.png',...samples.map(sample=>sample.image)];
    fs.writeFileSync(path.join(root,'export.json'),JSON.stringify({
      kind:'Narrated educational summary, not a game execution recording',viewport:{width:1440,height:810},
      video_seconds:videoSeconds,timeline_seconds:film.duration,measured_video_lead_seconds:lead,
      sync_note:'Video includes browser setup before playback; PCM is delayed by measured setup duration. Alignment is approximate at video-frame precision.',
      voice:'Local synthetic Mandarin narration, not the project owner speaking',page_errors:errors,
      audio_max_volume_db:Number(maximum[1]),
      controls:{started:true,paused:true,restarted:true,chapter_navigation:true},samples,
      artifacts_sha256:Object.fromEntries(artifacts.map(name=>[name,createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')])),
    },null,2)+'\n');
    console.log(`Exported narrated ${path.join(root,'introduction.mp4')} (${videoSeconds.toFixed(2)}s)`);
  } finally {
    try{if(browser)await browser.close();}finally{fs.closeSync(lock);fs.unlinkSync(reservation);}
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
