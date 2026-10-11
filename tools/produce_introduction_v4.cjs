/* Validate the captioned preview and optionally export it with one browser and two encoder threads. */
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {spawn,spawnSync} = require('node:child_process');
const {once} = require('node:events');
const {createHash} = require('node:crypto');

async function main() {
  const [playwrightModule,ffmpeg,revision='v4'] = process.argv.slice(2);
  if(!playwrightModule)throw Error('Usage: node tools/produce_introduction_v4.cjs PLAYWRIGHT_MODULE [FFMPEG] [v4|v5|v6]');
  if (!/^v[456]$/.test(revision)) throw Error('Expected presentation revision v4, v5 or v6.');
  const root=path.resolve(__dirname,`../docs/showcase/introduction/film-${revision}`);
  const output=path.join(root,'introduction.mp4'), temporary=path.join(root,'.preview-render.mp4');
  if(ffmpeg && (fs.existsSync(output)||fs.existsSync(temporary)))throw Error('Preview exists; do not overwrite a frozen export.');
  const {chromium}=require(playwrightModule);
  let browser,encoder,closed,published=false,complete=false;
  const errors=[],mediaAborts=[],samples=[],evidenceSamples=[];
  try {
    browser=await chromium.launch({args:['--allow-file-access-from-files']});
    const page=await browser.newPage({viewport:{width:1440,height:900}});
    page.on('pageerror',error=>errors.push(String(error)));
    page.on('requestfailed',request=> {
      if(request.url().endsWith('.webm') && request.failure()?.errorText==='net::ERR_ABORTED')mediaAborts.push(new URL(request.url()).pathname.split('/').at(-1));
      else errors.push(request.url()+': '+request.failure()?.errorText);
    });
    await page.goto(pathToFileURL(path.join(root,'index.html')).href);
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>window.animatic?.imageReady);
    const film=await page.evaluate(()=>window.animatic.film);
    await page.click('#play'); await page.waitForTimeout(300);
    if(await page.evaluate(()=>window.animatic.time)<=0)throw Error('Playback did not advance.');
    await page.click('#play'); const paused=await page.evaluate(()=>window.animatic.time);
    await page.waitForTimeout(100);
    if(await page.evaluate(()=>window.animatic.time)!==paused)throw Error('Pause failed.');
    const pixels=await page.evaluate(()=> {
      const ctx=document.querySelector('canvas').getContext('2d'),d=window.animatic.film.scenes[0].end;
      window.animatic.draw(d*.2);const a=ctx.getImageData(0,0,1440,810).data;
      window.animatic.draw(d*.8);const b=ctx.getImageData(0,0,1440,810).data;
      let changed=0,nonblank=0;
      for(let i=0;i<a.length;i+=4){if(a[i]!==b[i]||a[i+1]!==b[i+1]||a[i+2]!==b[i+2])changed++;if(b[i]>70||b[i+1]>70||b[i+2]>70)nonblank++;}
      return {changed,nonblank};
    });
    if(pixels.changed<100 || pixels.nonblank<1000)throw Error('Blank or static animation.');
    fs.mkdirSync(path.join(root,'previews'),{recursive:true});
    for(const viewport of [{width:1280,height:720},{width:1440,height:900}]) {
      await page.setViewportSize(viewport);
      for(const scene of film.scenes) {
        const t=scene.start+(scene.end-scene.start)*.82;
        await page.evaluate(async t=>{await window.animatic.seek(t);await window.animatic.prepare(t);window.animatic.draw(t);},t);
        const geometry=await page.evaluate(()=>({
          overflow:document.documentElement.scrollWidth>innerWidth||document.documentElement.scrollHeight>innerHeight,
          captionOverflow:document.querySelector('#subtitle').scrollHeight>76,
          fontReady:document.fonts.check('25px FilmChinese'),chapter:document.querySelector('#chapter').value
        }));
        if(geometry.overflow||geometry.captionOverflow||!geometry.fontReady||geometry.chapter!==scene.id)throw Error(JSON.stringify(geometry));
        const image=`previews/${viewport.width}-${scene.id}.png`;
        await page.screenshot({path:path.join(root,image)});samples.push({viewport,scene:scene.id,image,...geometry});
      }
      if(await page.evaluate(()=>typeof window.animatic.mediaStatus==='function')) {
        const scenes=film.scenes.filter(s=>['adventure','rescue'].includes(s.id));
        for(const scene of scenes)for(const [index,caption] of scene.lines.entries()) {
          const t=(caption.start+caption.end)/2;
          const evidence=await page.evaluate(async t=> {
            await window.animatic.seek(t);await window.animatic.prepare(t);window.animatic.draw(t);
            const status=window.animatic.mediaStatus(t);
            const {data}=document.querySelector('canvas').getContext('2d').getImageData(90,270,1260,400);
            let nonblank=0;for(let i=0;i<data.length;i+=4)if(data[i]>70||data[i+1]>70||data[i+2]>70)nonblank++;
            return {status,nonblank,subtitle:document.querySelector('#subtitle').textContent};
          },t);
          if(!evidence.status.ready||evidence.nonblank<3000||evidence.subtitle!==caption.text)throw Error('M1 cue not ready: '+JSON.stringify(evidence));
          const image=`previews/${viewport.width}-${scene.id}-cue-${index}.png`;
          await page.screenshot({path:path.join(root,image)});
          evidenceSamples.push({viewport,scene:scene.id,cue:index,time:t,image,...evidence});
        }
        const rescue=film.scenes.find(s=>s.id==='rescue');
        const target=(rescue.lines[5].start+rescue.lines[5].end)/2;
        for(let repeat=0;repeat<3;repeat++) {
          await page.evaluate(async t=>{await window.animatic.seek(t);if(!window.animatic.mediaStatus(t).ready)throw Error('Repeated seek left undecoded media');},target);
        }
      }
    }
    await page.selectOption('#chapter','vote');
    if(await page.evaluate(()=>window.animatic.time)!==film.scenes.find(s=>s.id==='vote').start)throw Error('Chapter jump failed.');
    await page.click('#restart'); await page.waitForTimeout(100);
    if(await page.evaluate(()=>window.animatic.time)>1)throw Error('Restart failed.');
    await page.click('#play');
    await page.evaluate(()=>window.animatic.seek(window.animatic.duration-.1));
    await page.click('#play'); await page.waitForFunction(()=>!window.animatic.playing,null,{timeout:3000});
    const minimum=await page.evaluate(async ()=> {
      let minimum=Infinity;const ctx=document.querySelector('canvas').getContext('2d');
      for(const scene of window.animatic.film.scenes)for(const caption of scene.lines) {
        const t=(caption.start+caption.end)/2;await window.animatic.prepare(t);
        window.animatic.draw(t);const a=ctx.getImageData(0,720,1440,90).data;
        window.animatic.draw(t,true);const b=ctx.getImageData(0,720,1440,90).data;
        let changed=0;for(let i=0;i<a.length;i+=4)if(a[i]!==b[i]||a[i+1]!==b[i+1]||a[i+2]!==b[i+2])changed++;
        minimum=Math.min(minimum,changed);
      }return minimum;
    });
    if(minimum<50)throw Error('Missing exported subtitle.');
    await page.evaluate(async()=>{await window.animatic.prepare(15);window.animatic.draw(15);});
    await page.locator('#canvas').screenshot({path:path.join(root,'poster.png')});
    if(ffmpeg) {
      await page.setViewportSize({width:1280,height:720});
      const fps=12,count=Math.ceil(film.duration*fps);
      await page.evaluate(()=>{window.exportCanvas=document.createElement('canvas');window.exportCanvas.width=1280;window.exportCanvas.height=720;});
      encoder=spawn(ffmpeg,['-hide_banner','-nostdin','-loglevel','error','-f','image2pipe','-framerate',String(fps),'-vcodec','mjpeg','-i','pipe:0',
        '-an','-c:v','libx264','-threads','2','-filter_threads','1','-preset','fast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',temporary],{stdio:['pipe','ignore','pipe']});
      let error=null,log='';encoder.on('error',e=>{error=e;});encoder.stdin.on('error',e=>{error=e;});
      encoder.stderr.on('data',data=>{log=(log+data).slice(-8000);});
      closed=new Promise(resolve=>encoder.once('close',(code,signal)=>resolve({code,signal})));
      for(let frame=0;frame<count;frame++) {
        if(error||encoder.exitCode!==null)throw error||Error(log);
        const jpeg=await page.evaluate(async t=> {
          await window.animatic.prepare(t);window.animatic.draw(t,true);
          window.exportCanvas.getContext('2d').drawImage(document.querySelector('#canvas'),0,0,1280,720);
          return window.exportCanvas.toDataURL('image/jpeg',.88).split(',')[1];
        },frame/fps);
        if(!encoder.stdin.write(Buffer.from(jpeg,'base64')))await once(encoder.stdin,'drain');
        if(frame%1000===0)console.log(`Frame ${frame}/${count}`);
      }
      encoder.stdin.end();const status=await closed;encoder=null;
      if(status.code!==0||error)throw error||Error(log);
      const decoded=spawnSync(ffmpeg,['-hide_banner','-nostdin','-threads','2','-i',temporary,'-threads','2','-f','null','-'],{encoding:'utf8',timeout:120000});
      if(decoded.status!==0||!decoded.stderr.includes('Video: h264')||decoded.stderr.includes('Audio:'))throw Error('Invalid silent preview: '+decoded.stderr);
      fs.renameSync(temporary,output);published=true;
    }
    if(errors.length)throw Error(errors.join('\n'));
    const names=['index.html','film.js','timeline.js','font/chinese.woff','font/site-chinese.woff','poster.png'];
    if(ffmpeg)names.push('introduction.mp4');
    fs.writeFileSync(path.join(root,'checks.json'),JSON.stringify({kind:'Captioned positioning preview; original experiment and M1 evidence reused',
      narration:'pending',duration_seconds:film.duration,controls:{play:true,pause:true,restart:true,chapter:true,ending:true},
      canvas:pixels,exported_subtitle_minimum_pixels:minimum,page_errors:errors,media_preload_aborts:mediaAborts,samples,evidenceSamples,
      video:ffmpeg?{width:1280,height:720,fps:12,codec:'H.264',audio:false,encoder_threads:2,decoded:true}:null,
      sha256:Object.fromEntries(names.map(name=>[name,createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]))},null,2)+'\n');
    complete=true;console.log('PASS: captioned preview controls, desktop geometry, moving canvas and subtitles.');
  } finally {
    if(encoder){encoder.kill('SIGTERM');await closed;}
    if(browser)await browser.close();
    if(!complete&&fs.existsSync(temporary))fs.rmSync(temporary);
    if(!complete&&published&&fs.existsSync(output))fs.rmSync(output);
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
