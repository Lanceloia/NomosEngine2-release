"use strict";

window.NomosPlayback = class {
  constructor({frame, group, lock, finish}) {
    Object.assign(this, {frame, group, lock, finish});
    this.seen = new Set(); this.speed = 1; this.paused = false; this.running = false;
  }
  async wait(milliseconds, signal) {
    const end = performance.now() + milliseconds;
    while (!signal.aborted && (this.paused || performance.now() < end)) {
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  }
  open(batch) {
    if (this.running) throw new Error("PlaybackAlreadyRunning");
    this.seen.add(batch.id); this.batch = batch; this.running = true; this.paused = false;
    this.complete = false;
    const controller = new AbortController(); this.controller = controller;
    this.lock(true);
    this.task = this.drain(batch, controller.signal);
    this.task.catch(() => {});
  }
  push(group) {
    this.batch.groups.push(group);
    this.wake?.();
  }
  async end(final) {
    this.batch.final = final;
    this.complete = true; this.wake?.();
    await this.task;
  }
  async fail() {
    if (this.batch) this.seen.delete(this.batch.id);
    if (!this.running) return;
    this.skip();
    await this.end(this.batch.groups.at(-1)?.state || this.batch.base);
  }
  async play(batch, replay = false) {
    if (this.running || (!replay && this.seen.has(batch.id))) return;
    this.open({...batch, groups: []});
    for (const group of batch.groups) this.push(group);
    await this.end(batch.final);
  }
  async drain(batch, signal) {
    try {
      this.frame(batch.base);
      let index = 0;
      while (true) {
        if (index === batch.groups.length) {
          if (this.complete) break;
          await new Promise(resolve => {this.wake = resolve;});
          this.wake = null;
          continue;
        }
        const group = batch.groups[index++];
        if (signal.aborted) {if (!this.complete) this.frame(group.state); continue;}
        while (this.paused && !signal.aborted) await this.wait(0, signal);
        if (signal.aborted) {if (!this.complete) this.frame(group.state); continue;}
        await this.group(group, index - 1, this.complete ? batch.groups.length : null, this.speed, signal);
        await this.wait(180 / this.speed, signal);
      }
    } finally {
      this.running = false; this.paused = false;
      try {this.lock(false); this.frame(batch.final || batch.groups.at(-1)?.state || batch.base);}
      finally {this.finish(batch);}
    }
  }
  skip() {this.controller?.abort();}
  toggle() {
    if (!this.running) return false;
    this.paused = !this.paused;
    for (const animation of this.animations || []) this.paused ? animation.pause() : animation.play();
    return this.paused;
  }
  reset() {this.skip(); this.seen.clear(); this.batch = null;}
};
