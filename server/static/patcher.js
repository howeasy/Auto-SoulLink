/* patcher.js — in-browser SLink companion-ROM patcher.
 *
 * A 1:1 port of patch/tools/make_ups.py (ups_apply + helpers). The UPS format
 * embeds CRC32 of the source ROM, the target ROM, and the patch itself, so the
 * apply step IS the validation: a wrong base ROM fails the source-CRC check and
 * a corrupt result fails the target-CRC check — same gate the Python tool uses.
 * MD5 is computed only to echo the friendly fingerprints from patch/README.md.
 *
 * Everything runs client-side; the ROM never leaves the browser.
 */
(function () {
  "use strict";

  // ── CRC32 (zlib polynomial, table-based) ─────────────────────────────────
  const CRC_TABLE = (function () {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) {
      c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    }
    return (c ^ 0xffffffff) >>> 0;
  }

  function readU32LE(bytes, pos) {
    return (
      (bytes[pos] |
        (bytes[pos + 1] << 8) |
        (bytes[pos + 2] << 16) |
        (bytes[pos + 3] << 24)) >>>
      0
    );
  }

  // ── UPS variable-length decode — mirrors _ups_decode() ───────────────────
  function upsDecode(data, pos, end = data.length) {
    let value = 0;
    let shift = 1;
    for (let count = 0; count < 8; count++) {
      if (!Number.isSafeInteger(pos) || pos < 0 || pos >= end) throw new Error("Truncated UPS integer.");
      const x = data[pos];
      pos += 1;
      value += (x & 0x7f) * shift;
      if (!Number.isSafeInteger(value)) throw new Error("UPS integer exceeds its supported range.");
      if (x & 0x80) return [value, pos];
      shift *= 128;
      value += shift;
      if (!Number.isSafeInteger(value) || !Number.isSafeInteger(shift)) throw new Error("UPS integer exceeds its supported range.");
    }
    throw new Error("UPS integer is too long.");
  }

  // ── UPS apply — mirrors ups_apply() ──────────────────────────────────────
  function upsApply(source, patch) {
    if (!(source instanceof Uint8Array) || !(patch instanceof Uint8Array) ||
        source.length > 64 * 1024 * 1024 || patch.length > 64 * 1024 * 1024) {
      throw new Error("Unsupported ROM or patch size.");
    }
    if (
      patch.length < 18 ||
      patch[0] !== 0x55 || // 'U'
      patch[1] !== 0x50 || // 'P'
      patch[2] !== 0x53 || // 'S'
      patch[3] !== 0x31 //  '1'
    ) {
      throw new Error("That patch file isn't a UPS1 patch.");
    }
    // Patch integrity: CRC covers everything but the trailing patch-CRC field.
    const wantPatchCrc = readU32LE(patch, patch.length - 4);
    const gotPatchCrc = crc32(patch.subarray(0, patch.length - 4));
    if (wantPatchCrc !== gotPatchCrc) {
      throw new Error("The patch file is corrupt (CRC mismatch). Re-download it.");
    }
    const srcCrc = readU32LE(patch, patch.length - 12);
    if (crc32(source) !== srcCrc) {
      throw new Error("This ROM does not match the patch's required input.");
    }
    const bodyEnd = patch.length - 12;
    let pos = 4;
    let dec = upsDecode(patch, pos, bodyEnd);
    if (dec[0] !== source.length) throw new Error("UPS source size differs from the ROM.");
    pos = dec[1];
    dec = upsDecode(patch, pos, bodyEnd);
    const dstSize = dec[0];
    if (dstSize > 64 * 1024 * 1024) throw new Error("UPS output size exceeds the supported limit.");
    pos = dec[1];

    const out = new Uint8Array(dstSize);
    out.set(source.subarray(0, Math.min(source.length, dstSize)));

    let i = 0;
    while (pos < bodyEnd) {
      dec = upsDecode(patch, pos, bodyEnd);
      i += dec[0];
      if (!Number.isSafeInteger(i) || i > dstSize) throw new Error("UPS span starts outside the output.");
      pos = dec[1];
      let terminated = false;
      while (pos < bodyEnd) {
        const x = patch[pos];
        pos += 1;
        if (i > dstSize || (i === dstSize && x !== 0)) throw new Error("UPS span writes outside the output.");
        if (i < dstSize) out[i] ^= x;
        i += 1;
        if (x === 0) { terminated = true; break; }
      }
      if (!terminated) throw new Error("UPS span has no terminator.");
    }

    const tgtCrc = readU32LE(patch, patch.length - 8);
    if (crc32(out) !== tgtCrc) {
      throw new Error("Patched result failed its checksum — please retry.");
    }
    return out;
  }

  // ── MD5 (compact, for display only) ──────────────────────────────────────
  function md5(bytes) {
    function rl(x, c) {
      return (x << c) | (x >>> (32 - c));
    }
    function add(a, b) {
      return (a + b) | 0;
    }
    const len = bytes.length;
    const nWords = ((len + 8) >> 6) + 1;
    const words = new Int32Array(nWords * 16);
    for (let i = 0; i < len; i++) words[i >> 2] |= bytes[i] << ((i % 4) * 8);
    words[len >> 2] |= 0x80 << ((len % 4) * 8);
    words[nWords * 16 - 2] = len * 8;

    let a = 1732584193,
      b = -271733879,
      c = -1732584194,
      d = 271733878;
    const S = [
      7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20,
      5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4,
      11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6,
      10, 15, 21,
    ];
    const K = [];
    for (let i = 0; i < 64; i++) K[i] = (Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296)) | 0;

    for (let off = 0; off < words.length; off += 16) {
      let A = a,
        B = b,
        C = c,
        D = d;
      for (let i = 0; i < 64; i++) {
        let f, g;
        if (i < 16) {
          f = (B & C) | (~B & D);
          g = i;
        } else if (i < 32) {
          f = (D & B) | (~D & C);
          g = (5 * i + 1) % 16;
        } else if (i < 48) {
          f = B ^ C ^ D;
          g = (3 * i + 5) % 16;
        } else {
          f = C ^ (B | ~D);
          g = (7 * i) % 16;
        }
        const tmp = D;
        D = C;
        C = B;
        B = add(B, rl(add(add(add(A, f), K[i]), words[off + g]), S[i]));
        A = tmp;
      }
      a = add(a, A);
      b = add(b, B);
      c = add(c, C);
      d = add(d, D);
    }
    return [a, b, c, d]
      .map(function (n) {
        let s = "";
        for (let j = 0; j < 4; j++) {
          s += ((n >> (j * 8)) & 0xff).toString(16).padStart(2, "0");
        }
        return s;
      })
      .join("");
  }

  // Expose the pure codec primitives for tests / debugging. Harmless in prod
  // (no DOM/network side effects) and lets the verification harness exercise
  // crc32 / md5 / upsApply directly without going through the file picker.
  window.SLinkPatcher = { crc32: crc32, md5: md5, upsDecode: upsDecode, upsApply: upsApply };

  // ── UI wiring ────────────────────────────────────────────────────────────
  const wrap = document.querySelector(".patcher-wrap");
  if (!wrap) return;
  const cfg = wrap.dataset;

  const input = document.getElementById("rom-input");
  const drop = document.getElementById("drop");
  const romName = document.getElementById("rom-name");
  const applyBtn = document.getElementById("apply");
  const downloadEl = document.getElementById("download");
  const statusEl = document.getElementById("status");
  const fp = document.getElementById("fp");
  const fpIn = document.getElementById("fp-in");
  const fpOut = document.getElementById("fp-out");

  let romFile = null;
  let blobUrl = null;
  let generation = 0;

  async function sha256(bytes) {
    if (!window.crypto || !window.crypto.subtle) throw new Error("Open this patcher on localhost or HTTPS to verify the ROM.");
    const hash = new Uint8Array(await window.crypto.subtle.digest("SHA-256", bytes));
    return Array.from(hash, x => x.toString(16).padStart(2, "0")).join("");
  }

  function setStatus(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = "patcher-status" + (kind ? " is-" + kind : "");
  }

  function resetOutput() {
    downloadEl.hidden = true;
    downloadEl.removeAttribute("href");
    fp.hidden = true;
    if (blobUrl) {
      URL.revokeObjectURL(blobUrl);
      blobUrl = null;
    }
  }

  function chooseFile(file) {
    generation += 1;
    romFile = file || null;
    resetOutput();
    if (romFile) {
      romName.textContent = romFile.name;
      applyBtn.disabled = false;
      setStatus("Ready to patch.", "info");
    } else {
      romName.textContent = "";
      applyBtn.disabled = true;
      setStatus("", "");
    }
  }

  input.addEventListener("change", function () {
    chooseFile(input.files && input.files[0]);
  });

  ["dragenter", "dragover"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      drop.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault();
      drop.classList.remove("is-over");
    });
  });
  drop.addEventListener("drop", function (e) {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) chooseFile(f);
  });

  applyBtn.addEventListener("click", async function () {
    if (!romFile) return;
    const selected = romFile;
    const token = ++generation;
    applyBtn.disabled = true;
    resetOutput();
    try {
      setStatus("Reading ROM…", "working");
      if (selected.size > 64 * 1024 * 1024) throw new Error("Unsupported ROM size.");
      const source = new Uint8Array(await selected.arrayBuffer());
      if (token !== generation) return;
      if (cfg.baseSha256 && await sha256(source) !== cfg.baseSha256) throw new Error("Choose the exact input ROM for this target. Different or already patched ROMs are not accepted here.");
      if (token !== generation) return;

      setStatus("Fetching patch…", "working");
      const resp = await fetch(cfg.patchUrl);
      if (token !== generation) return;
      if (!resp.ok) {
        throw new Error(
          "Couldn't load the verified patch from the server. It may need to be rebuilt."
        );
      }
      const patch = new Uint8Array(await resp.arrayBuffer());
      if (token !== generation) return;
      if (cfg.patchSha256 && await sha256(patch) !== cfg.patchSha256) throw new Error("The downloaded patch differs from its verified fingerprint.");
      if (token !== generation) return;

      setStatus("Applying patch…", "working");
      const inMd5 = md5(source);
      const out = upsApply(source, patch);
      const outMd5 = md5(out);
      if (cfg.patchedSha256 && await sha256(out) !== cfg.patchedSha256) throw new Error("Patched ROM failed final fingerprint verification.");
      const expected = (cfg.patchedMd5 || "").toLowerCase();
      if (expected && outMd5 !== expected) throw new Error("Patched ROM failed final fingerprint verification.");
      if (token !== generation) return;

      blobUrl = URL.createObjectURL(
        new Blob([out], { type: "application/octet-stream" })
      );
      downloadEl.href = blobUrl;
      // The target names its own output. Hardcoding the Radical Red filename meant a
      // patched Pokemon Red downloaded as a .gba called "Radical Red", which is both
      // confusing and the wrong extension for the emulator to associate.
      downloadEl.download = cfg.outName || "Pokemon - Radical Red (SLink companion).gba";
      downloadEl.hidden = false;

      fpIn.textContent = inMd5;
      fpOut.textContent = outMd5;
      fp.hidden = false;

      setStatus("Done — the patched ROM matches its verified fingerprint. Click download.", "ok");
    } catch (err) {
      if (token === generation) setStatus(err && err.message ? err.message : String(err), "error");
    } finally {
      if (token === generation) applyBtn.disabled = !romFile;
    }
  });
})();
