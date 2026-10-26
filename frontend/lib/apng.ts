// An animated PNG (backend/app/engine/chart_render.py `apng`) cut into one standalone PNG per frame, so a canvas can
// show any frame on its own: a browser plays an animated image but cannot seek it. The backend writes every frame
// whole (full size, no offsets), so each frame is the file's header and palette plus that frame's image data.

const SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const IEND = new Uint8Array([0, 0, 0, 0, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82]);

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(parts: Uint8Array[]): number {
  let c = 0xffffffff;
  for (const part of parts) for (let i = 0; i < part.length; i++) c = CRC_TABLE[(c ^ part[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function idat(data: Uint8Array): Uint8Array {
  const type = new Uint8Array([0x49, 0x44, 0x41, 0x54]);
  const out = new Uint8Array(12 + data.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, data.length);
  out.set(type, 4);
  out.set(data, 8);
  view.setUint32(8 + data.length, crc32([type, data]));
  return out;
}

/** Each frame of an APNG as a PNG blob, in order. Throws on a file that is not a PNG. */
export function apngFrames(buffer: ArrayBuffer): Blob[] {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 8 || SIGNATURE.some((b, i) => bytes[i] !== b)) throw new Error("Not a PNG.");
  const view = new DataView(buffer);
  const head: Uint8Array[] = [];
  const frames: Uint8Array[][] = [];
  let pos = 8;
  while (pos + 12 <= bytes.length) {
    const length = view.getUint32(pos);
    const type = String.fromCharCode(...bytes.subarray(pos + 4, pos + 8));
    const end = pos + 12 + length;
    if (end > bytes.length) throw new Error("The clip is cut short.");
    const data = bytes.subarray(pos + 8, pos + 8 + length);
    if (type === "IHDR" || type === "PLTE" || type === "tRNS") head.push(bytes.slice(pos, end));
    else if (type === "fcTL") frames.push([]);
    else if (type === "IDAT" && frames.length) frames[frames.length - 1].push(data.slice());
    else if (type === "fdAT" && frames.length) frames[frames.length - 1].push(data.slice(4));
    else if (type === "IEND") break;
    pos = end;
  }
  if (!frames.length) throw new Error("The clip has no frames.");
  return frames.map(parts => new Blob([SIGNATURE, ...head, ...parts.map(idat), IEND] as BlobPart[], { type: "image/png" }));
}
