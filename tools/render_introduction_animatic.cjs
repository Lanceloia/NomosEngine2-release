/* Export deterministic browser frames; keep one browser, a bounded pipe and two encoder threads. */
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { spawn, spawnSync } = require('node:child_process');
const { once } = require('node:events');
const { createHash } = require('node:crypto');

async function main() {
  const [directory, playwrightModule, ffmpeg] = process.argv.slice(2);
  if (!directory || !playwrightModule || !ffmpeg) throw Error('Usage: node tools/render_introduction_animatic.cjs DIRECTORY PLAYWRIGHT_MODULE FFMPEG');
  const root = path.resolve(directory), output = path.join(root, 'introduction.mp4');
  const temporary = path.join(root, '.introduction-render.mp4');
  if (fs.existsSync(output) || fs.existsSync(temporary)) throw Error('Output exists; choose a new candidate directory.');
  const { chromium } = require(playwrightModule);
  let browser, encoder, encoderClosed, completed = false, published = false;
  const errors = [], mediaAborts = [];
  try {
    browser = await chromium.launch({args:['--allow-file-access-from-files']});
    const page = await browser.newPage({viewport:{width:1280,height:720}});
    page.on('pageerror',error=>errors.push(String(error)));
    const audioURL=pathToFileURL(path.join(root,'narration.mp3')).href;
    page.on('requestfailed',request=>{
      const failure=request.failure()?.errorText;
      if((request.url()===audioURL || request.url().endsWith('.webm')) && failure==='net::ERR_ABORTED')mediaAborts.push(path.basename(new URL(request.url()).pathname));
      else errors.push(request.url()+': '+failure);
    });
    await page.goto(pathToFileURL(path.join(root,'index.html')).href+'?export');
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>window.animatic?.imageReady && document.querySelector('#audio').readyState>=2);
    const timing = await page.evaluate(()=>({audio:document.querySelector('#audio').duration,film:window.animatic.film.duration}));
    if (!Number.isFinite(timing.audio) || timing.audio<=0 || Math.abs(timing.audio-timing.film)>.1) throw Error('Invalid audio timing.');
    const fps = 20, count = Math.ceil(timing.audio*fps);
    await page.evaluate(()=> {
      window.exportCanvas=document.createElement('canvas');
      window.exportCanvas.width=1280;window.exportCanvas.height=720;
    });
    encoder = spawn(ffmpeg, ['-hide_banner','-nostdin','-loglevel','error',
      '-f','image2pipe','-framerate',String(fps),'-vcodec','mjpeg','-i','pipe:0',
      '-i',path.join(root,'narration.mp3'),'-map','0:v:0','-map','1:a:0',
      '-c:v','libx264','-threads','2','-filter_threads','1','-preset','fast','-crf','21',
      '-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',
      '-t',String(timing.audio),temporary], {stdio:['pipe','ignore','pipe']});
    let encoderError = null, log = '';
    encoder.on('error',error=>{encoderError=error;});
    encoder.stdin.on('error',error=>{encoderError=error;});
    encoder.stderr.on('data',data=>{log=(log+data).slice(-12000);});
    encoderClosed = new Promise(resolve=>encoder.once('close',(code,signal)=>resolve({code,signal})));
    for(let frame=0;frame<count;frame++) {
      if(encoderError || encoder.exitCode!==null) throw encoderError||Error(log||'Encoder exited early.');
      const t=frame/fps/timing.audio*timing.film;
      const encoded=await page.evaluate(async t=> {
        await window.animatic.prepare(t);
        window.animatic.draw(t,true);
        window.exportCanvas.getContext('2d').drawImage(document.querySelector('#canvas'),0,0,1280,720);
        return window.exportCanvas.toDataURL('image/jpeg',.9).split(',')[1];
      },t);
      const picture=Buffer.from(encoded,'base64');
      if(!encoder.stdin.write(picture))await once(encoder.stdin,'drain');
      if(frame%1000===0)process.stdout.write(`Frame ${frame}/${count}\n`);
    }
    encoder.stdin.end();
    const status=await encoderClosed;
    if(status.code!==0 || encoderError)throw encoderError||Error(log||JSON.stringify(status));
    encoder=null;
    const decode=spawnSync(ffmpeg,['-hide_banner','-nostdin','-threads','2','-i',temporary,
      '-map','0:v:0','-map','0:a:0','-threads','2','-f','null','-'],{encoding:'utf8',timeout:120000});
    if(decode.status!==0 || !decode.stderr.includes('Video: h264') || !decode.stderr.includes('Audio: aac')) throw Error(decode.stderr||'Invalid export streams.');
    if(errors.length)throw Error(errors.join('\n'));
    fs.renameSync(temporary,output);
    published=true;
    const names=[...JSON.parse(fs.readFileSync(path.join(root,'dependencies.json'),'utf8')),'introduction.mp4'];
    fs.writeFileSync(path.join(root,'export.json'),JSON.stringify({
      kind:'Narrated project introduction; saved experiment diagrams and previously recorded real M1 browser interactions',
      voice:'Provided narration MP3',duration_seconds:timing.audio,
      video:{width:1280,height:720,fps,frames:count,codec:'H.264',encoder_threads:2,audio:'AAC'},
      synchronization:'Deterministic frame timestamps share the audio clock; sentence alignment remains a speech-pause estimate. Listening acceptance pending.',
      page_errors:errors,media_preload_aborts:mediaAborts,decoded_both_streams:true,
      sha256:Object.fromEntries(names.map(name=>[name,createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]))
    },null,2)+'\n');
    completed=true;
    console.log(`Rendered ${output}`);
  } finally {
    try {
      if(encoder){encoder.kill('SIGTERM');await encoderClosed;}
    } finally {
      try {
        if(browser)await browser.close();
      } finally {
        if(!completed && fs.existsSync(temporary))fs.rmSync(temporary);
        if(!completed && published && fs.existsSync(output))fs.rmSync(output);
      }
    }
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
