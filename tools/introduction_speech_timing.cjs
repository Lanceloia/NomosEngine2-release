/* Monotone pause partitioning shared by narrated storyboard producers. */
function weight(text) {
  return [...text.replace(/NomosEngine2/g, '诺莫斯引擎').replace(/TRPG/g, '桌上角色扮演')
    .replace(/NPC/g, '角色').replace(/Program/g, '程序').replace(/Assets/g, '资产')
    .replace(/Python/g, '派森').replace(/Codex/g, '科德克斯').replace(/Lanceloia/g, '兰瑟洛亚')
    .replace(/[CKT]0/g, '工具').replace(/[^\p{L}\p{N}]/gu, '')].length;
}
function align(sentences, intervals) {
  const totalWeight = sentences.reduce((sum, s) => sum + weight(s), 0);
  const totalSpeech = intervals.reduce((sum, s) => sum + s.end - s.start, 0);
  const rate = totalSpeech / totalWeight, n = sentences.length, m = intervals.length;
  const cost = Array.from({ length: n + 1 }, () => Array(m + 1).fill(Infinity));
  const previous = Array.from({ length: n + 1 }, () => Array(m + 1));
  cost[0][0] = 0;
  for (let i = 0; i < n; i++) for (let j = i; j < m; j++) {
    if (!Number.isFinite(cost[i][j])) continue;
    for (let count = 1; count <= 3 && j + count <= m; count++) {
      const speech = intervals.slice(j, j + count).reduce((sum, s) => sum + s.end - s.start, 0);
      const ratio = speech / Math.max(.1, rate * weight(sentences[i]));
      const next = cost[i][j] + Math.log(ratio) ** 2 + (count - 1) * .04;
      if (next < cost[i + 1][j + count]) {
        cost[i + 1][j + count] = next; previous[i + 1][j + count] = j;
      }
    }
  }
  if (!Number.isFinite(cost[n][m])) throw Error('Voice pauses cannot be aligned to this script.');
  const result = Array(n); let j = m;
  for (let i = n; i > 0; i--) {
    const start = previous[i][j];
    result[i - 1] = { text: sentences[i - 1], start: intervals[start].start,
      end: intervals[j - 1].end, speech_intervals: j - start };
    j = start;
  }
  return result;
}
module.exports = {align, weight};
