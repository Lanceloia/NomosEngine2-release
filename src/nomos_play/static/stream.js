"use strict";

window.NomosStream = async function(response, receive) {
  if (!response.ok) {
    let body;
    try {body = await response.json();} catch {throw new Error("InvalidResponse");}
    throw new Error(body.code || "RequestFailed");
  }
  const failure = code => Object.assign(new Error(code), {sync: true});
  if (!response.headers.get("Content-Type")?.startsWith("application/x-ndjson") || !response.body) {
    throw failure("InvalidResponse");
  }
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", result, accepted = false, begun = false, final = false, ended = false;
  const ids = new Set();
  try {
    while (true) {
      let chunk;
      try {chunk = await reader.read();} catch {throw failure("ConnectionLost");}
      buffer += decoder.decode(chunk.value, {stream: !chunk.done});
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1);
        let frame;
        try {frame = JSON.parse(line);} catch {throw failure("InvalidResponse");}
        if (final || !frame || typeof frame !== "object") throw failure("InvalidResponse");
        if (frame.type === "error") throw failure(frame.code || "SettlementError");
        if (frame.type === "accepted" && !accepted && !begun && typeof frame.action === "string") accepted = true;
        else if (frame.type === "begin" && !begun && typeof frame.id === "string" && frame.base) begun = true;
        else if (frame.type === "group" && begun && frame.group?.state && typeof frame.group.id === "string" && !ids.has(frame.group.id)) ids.add(frame.group.id);
        else if (frame.type === "final" && frame.view) {final = true; result = frame.view;}
        else throw failure("InvalidResponse");
        receive(frame);
      }
      if (chunk.done) {ended = true; break;}
    }
    if (buffer || !final) throw failure("InvalidResponse");
    return result;
  } finally {
    if (!ended) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
};
