/* Build a captioned preview from the canonical script; recorded narration is a later input. */
const fs = require('node:fs');
const path = require('node:path');

const IDS = ['origin','history','pipeline','witness','admission','vote','configuration','adventure','rescue','combination','future','credits'];

function build(script) {
  const matches = [...script.matchAll(/^## ([a-z]+) · ([^\n]+)\n+([^#]+?)(?=\n## |$)/gm)];
  if (matches.length !== IDS.length || matches.some((m,i)=>m[1]!==IDS[i])) throw Error('Expected twelve ordered storyboard sections.');
  let cursor = 0;
  const scenes = matches.map(([,id,title,paragraph])=> {
    const narration = paragraph.trim();
    const sentences = narration.match(/[^。！？]+[。！？]?/gu);
    if (!sentences?.length) throw Error('Missing narration: '+id);
    const start = cursor;
    const lines = sentences.map(text=> {
      const start = cursor;
      cursor += Math.max(4, [...text].length/5.5) + .6;
      return {text,start,end:cursor};
    });
    return {id,title,start,end:cursor,lines,narration};
  });
  return {kind:'Captioned positioning preview; narration pending',duration:cursor,scenes};
}

function main() {
  const root = path.resolve(__dirname,'..');
  const revision = process.argv[2] || 'v4';
  if (!/^v[45]$/.test(revision)) throw Error('Expected presentation revision v4 or v5.');
  const draft = path.join(root,`docs/showcase/introduction/draft-${revision}`);
  const target = path.join(root,`docs/showcase/introduction/film-${revision}`);
  const film = build(fs.readFileSync(path.join(draft,'SCRIPT.md'),'utf8'));
  fs.mkdirSync(target,{recursive:true});
  fs.writeFileSync(path.join(target,'timeline.js'),'window.NOMOS_FILM = '+JSON.stringify(film,null,2).replaceAll('<','\\u003c')+';\n');
  fs.writeFileSync(path.join(draft,'NARRATION.txt'),film.scenes.map(s=>s.narration).join('\n\n')+'\n');
  console.log(`Built ${film.scenes.length} chapters, ${film.duration.toFixed(1)} seconds; narration pending.`);
}
if (require.main===module) main();
module.exports = {build,IDS};
