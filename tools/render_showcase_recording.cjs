/* Optional presentation export; Playwright records the already captured outputs. */
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { pathToFileURL } = require('node:url');

async function main() {
  const [directory, playwrightModule = 'playwright', fontFile] = process.argv.slice(2);
  if (!directory) throw Error('Usage: node tools/render_showcase_recording.cjs DIRECTORY [PLAYWRIGHT_MODULE] [FONT_FILE]');
  const root = path.resolve(directory);
  const products = ['demo.webm', 'poster.png', 'video-export.json', '.video',
    ...Array.from({ length: 6 }, (_, index) => `chapter-${index + 1}.png`)];
  if (products.some(name => fs.existsSync(path.join(root, name)))) throw Error('Export artifacts already exist; never overwrite captures.');
  const reservation = path.join(root, '.video-export.lock');
  const lock = fs.openSync(reservation, 'wx');
  const { chromium } = require(playwrightModule);
  let browser;
  try {
    browser = await chromium.launch({ args: ['--allow-file-access-from-files'] });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(pathToFileURL(path.join(root, 'replay.html')).href);
    if (fontFile) {
      const source = pathToFileURL(path.resolve(fontFile)).href;
      await page.addStyleTag({ content: `@font-face { font-family: RecordingChinese; src: url('${source}'); } body { font-family: RecordingChinese, sans-serif; } pre { font-family: Consolas, 'DejaVu Sans Mono', RecordingChinese, monospace; }` });
    }
    await page.evaluate(() => document.fonts.ready);
    const chapters = await page.evaluate(() => window.showcase.recording.chapters);
    for (let index = 0; index < chapters.length; index++) {
      await page.evaluate(time => window.showcase.seek(time), chapters[index].output_at + 0.1);
      await page.screenshot({ path: path.join(root, `chapter-${index + 1}.png`) });
      const geometry = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth > innerWidth,
        clipped: document.querySelector('#output').scrollHeight > document.querySelector('#output').clientHeight,
      }));
      if (geometry.overflow || geometry.clipped) throw Error(`Unreadable chapter ${index + 1}: ${JSON.stringify(geometry)}`);
    }
    await page.evaluate(time => window.showcase.seek(time), chapters[2].output_at + 0.1);
    await page.screenshot({ path: path.join(root, 'poster.png') });
    await context.close();
    const videoContext = await browser.newContext({ viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(root, '.video'), size: { width: 1440, height: 900 } } });
    const videoPage = await videoContext.newPage();
    videoPage.on('pageerror', error => errors.push(String(error)));
    await videoPage.goto(pathToFileURL(path.join(root, 'replay.html')).href);
    if (fontFile) {
      await videoPage.addStyleTag({ content: `@font-face { font-family: RecordingChinese; src: url('${pathToFileURL(path.resolve(fontFile)).href}'); } body { font-family: RecordingChinese, sans-serif; } pre { font-family: Consolas, 'DejaVu Sans Mono', RecordingChinese, monospace; }` });
    }
    await videoPage.evaluate(() => document.fonts.ready);
    await videoPage.evaluate(() => window.showcase.play());
    const duration = await videoPage.evaluate(() => window.showcase.recording.duration);
    const playbackStart = Date.now();
    await videoPage.waitForFunction(() => window.showcase.ended,
                               null, { timeout: (duration + 30) * 1000 });
    if (errors.length) throw Error(errors.join('\n'));
    const video = videoPage.video();
    await videoPage.close();
    await video.saveAs(path.join(root, 'demo.webm'));
    await videoContext.close();
    fs.unlinkSync(await video.path());
    fs.rmdirSync(path.join(root, '.video'));
    const artifacts = fs.readdirSync(root).filter(name => name.endsWith('.png') || name === 'demo.webm');
    fs.writeFileSync(path.join(root, 'video-export.json'), JSON.stringify({
      viewport: { width: 1440, height: 900 }, playback_seconds: (Date.now() - playbackStart) / 1000,
      recording_seconds: duration, page_errors: errors,
      replay_html_sha256: createHash('sha256').update(fs.readFileSync(path.join(root, 'replay.html'))).digest('hex'),
      artifacts_sha256: Object.fromEntries(artifacts.map(name => [name,
        createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')])),
      note: 'Browser records previously captured command outputs; brief page/font setup precedes playback. No audio.',
    }, null, 2) + '\n');
    console.log(`Exported ${path.join(root, 'demo.webm')}`);
  } finally {
    if (browser) await browser.close();
    fs.closeSync(lock);
    fs.unlinkSync(reservation);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
