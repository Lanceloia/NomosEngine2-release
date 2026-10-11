/* Check one local animatic in one browser; close the browser even when a check fails. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createHash } = require('node:crypto');

async function main() {
  const [directory, playwrightModule] = process.argv.slice(2);
  if (!directory || !playwrightModule) throw Error('Usage: node tools/check_introduction_animatic.cjs DIRECTORY PLAYWRIGHT_MODULE');
  const root = path.resolve(directory), { chromium } = require(playwrightModule);
  const browser = await chromium.launch({ args:['--allow-file-access-from-files'] });
  const errors = [], samples = [], mediaAborts = [];
  try {
    const context = await browser.newContext({ viewport:{width:1440,height:900} });
    const page = await context.newPage();
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('requestfailed',request=>{
      const failure=request.failure()?.errorText;
      if (/\.(mp3|webm)$/.test(request.url()) && failure==='net::ERR_ABORTED')mediaAborts.push(path.basename(new URL(request.url()).pathname));
      else errors.push(request.url()+': '+failure);
    });
    await page.goto(pathToFileURL(path.join(root,'index.html')).href);
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>window.animatic);
    await page.waitForFunction(()=>window.animatic.imageReady && document.querySelector('#audio').readyState>=2);
    const film = await page.evaluate(()=>window.animatic.film);
    const seconds = await page.evaluate(()=>document.querySelector('#audio').duration);
    if(Math.abs(seconds-film.duration)>.1)throw Error('Audio and storyboard durations differ.');
    await page.click('#play');
    await page.waitForTimeout(300);
    if (await page.evaluate(()=>window.animatic.time)<=0) throw Error('Play did not advance.');
    await page.click('#play');
    const paused = await page.evaluate(()=>window.animatic.time);
    await page.waitForTimeout(100);
    if (Math.abs(await page.evaluate(()=>window.animatic.time)-paused)>.001) throw Error('Pause did not stop.');
    const pixels = await page.evaluate(()=> {
      const a=window.animatic.film.scenes[0],ctx=document.querySelector('canvas').getContext('2d');
      window.animatic.draw(a.start+(a.end-a.start)*.12);const first=ctx.getImageData(0,0,1440,810).data;
      window.animatic.draw(a.start+(a.end-a.start)*.16);const second=ctx.getImageData(0,0,1440,810).data;
      let changed=0,nonblank=0;
      for(let i=0;i<first.length;i+=4){if(first[i]!==second[i]||first[i+1]!==second[i+1]||first[i+2]!==second[i+2])changed++;if(first[i]>70||first[i+1]>70||first[i+2]>70)nonblank++;}
      return {changed,nonblank};
    });
    if(pixels.changed<100||pixels.nonblank<1000)throw Error('Blank or static scene.');
    const exported=await page.evaluate(async ()=> {
      let minimum=Infinity;
      const ctx=document.querySelector('canvas').getContext('2d');
      for(const scene of window.animatic.film.scenes)for(const line of scene.lines) {
        const t=(line.start+line.end)/2;
        await window.animatic.prepare(t);
        window.animatic.draw(t,false);const before=ctx.getImageData(0,720,1440,90).data;
        window.animatic.draw(t,true);const after=ctx.getImageData(0,720,1440,90).data;
        let changed=0;for(let i=0;i<before.length;i+=4)if(before[i]!==after[i]||before[i+1]!==after[i+1]||before[i+2]!==after[i+2])changed++;
        minimum=Math.min(minimum,changed);
      }
      return {subtitle_minimum_changed_pixels:minimum};
    });
    if(exported.subtitle_minimum_changed_pixels<50)throw Error('Missing export subtitle.');
    fs.mkdirSync(path.join(root,'previews'),{recursive:true});
    for(const viewport of [{width:1280,height:720},{width:1440,height:900},{width:1920,height:1080}]) {
      await page.setViewportSize(viewport);
      for(const scene of film.scenes) {
        const time=scene.start+(scene.end-scene.start)*.82;
        await page.evaluate(async t=>{await window.animatic.seek(t);await window.animatic.prepare(t);window.animatic.draw(t);},time);
        const geometry=await page.evaluate(()=> {
          const stage=document.querySelector('#stage').getBoundingClientRect(),caption=document.querySelector('#subtitle').getBoundingClientRect();
          const lines=document.querySelector('#subtitle');
          return {overflow:document.documentElement.scrollWidth>innerWidth||document.documentElement.scrollHeight>innerHeight,
            subtitle:lines.textContent,captionOverflow:lines.scrollHeight>76,
            captionInside:caption.top>=stage.top&&caption.bottom<=stage.bottom,
            fontReady:document.fonts.check('25px FilmChinese'),chapter:document.querySelector('#chapter').value};
        });
        if(geometry.overflow||geometry.captionOverflow||!geometry.captionInside||!geometry.fontReady||geometry.chapter!==scene.id)throw Error(`${viewport.width}/${scene.id}: ${JSON.stringify(geometry)}`);
        const name=`previews/${viewport.width}-${scene.id}.png`;
        await page.screenshot({path:path.join(root,name)});
        samples.push({viewport,scene:scene.id,time,image:name,...geometry});
      }
      for(const scene of film.scenes.filter(s=>['pipeline','adventure','rescue'].includes(s.id)))for(const [cueIndex,cue] of scene.lines.entries()) {
        const time=(cue.start+cue.end)/2;
        await page.evaluate(async t=>{await window.animatic.seek(t);},time);
        if(!await page.evaluate(t=>window.animatic.mediaStatus(t).ready,time))throw Error('Evidence media not ready.');
        const name=`previews/${viewport.width}-${scene.id}-cue-${cueIndex}.png`;
        await page.screenshot({path:path.join(root,name)});
        samples.push({viewport,scene:scene.id,cue:cueIndex,time,image:name});
      }
    }
    await page.selectOption('#chapter','vote');
    if(Math.abs(await page.evaluate(()=>window.animatic.time)-film.scenes.find(s=>s.id==='vote').start)>.001)throw Error('Chapter jump failed.');
    await page.click('#restart');
    if(await page.evaluate(()=>window.animatic.time)>1)throw Error('Restart failed.');
    await page.click('#play');
    await page.evaluate(()=>window.animatic.seek(window.animatic.duration-.1));
    await page.click('#play');
    await page.waitForFunction(()=>!window.animatic.playing,null,{timeout:3000});
    if(errors.length)throw Error(errors.join('\n'));
    const names=JSON.parse(fs.readFileSync(path.join(root,'dependencies.json'),'utf8'));
    fs.writeFileSync(path.join(root,'checks.json'),JSON.stringify({kind:'Narrated storyboard browser checks; not a new world run or a listening acceptance',
      duration:film.duration,measured_audio_duration:seconds,controls:{play:true,pause:true,restart:true,chapter:true,ending:true},
      canvas:pixels,exported_captions:exported,page_errors:errors,media_preload_aborts:mediaAborts,samples,
      sha256:Object.fromEntries(names.map(name=>[name,createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]))},null,2)+'\n');
    console.log(`PASS: controls, moving canvas, ${samples.length} desktop screenshots.`);
  } finally {await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
