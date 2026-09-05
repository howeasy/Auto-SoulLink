// Small formatters. Everything here mirrors an existing server-side renderer so the
// mockup does not invent presentation the real app doesn't already have.

// server/html_render.py:150 status_icon_html — the Lua status_cond bitfield.
export function statusChips(cond) {
  const c = Number(cond || 0);
  if (!c) return [];
  if (c & 0x07) return [['SLP', 'sc-slp']];
  if (c & 0x80) return [['TOX', 'sc-tox']];
  if (c & 0x08) return [['PSN', 'sc-psn']];
  if (c & 0x10) return [['BRN', 'sc-brn']];
  if (c & 0x20) return [['FRZ', 'sc-frz']];
  if (c & 0x40) return [['PAR', 'sc-par']];
  return [];
}

export function hpClass(hp, max) {
  const p = max ? hp / max : 0;
  return p > 0.5 ? 'hp-h' : p > 0.2 ? 'hp-m' : 'hp-l';
}

export function ppClass(cur, max) {
  const p = max ? cur / max : 0;
  return p > 0.5 ? 'pp-h' : p > 0.25 ? 'pp-m' : 'pp-l';
}

export function pct(hp, max) {
  return max ? Math.max(0, Math.min(100, (hp / max) * 100)) : 0;
}

export function areaLabel(id) {
  if (!id) return '—';
  return id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// Sprites in the payload are `sprite_html` pointing at raw.githubusercontent.com.
// The mockup must work with no network (brief §8.3), so we deliberately do NOT
// inject that markup — a wall of broken-image icons is a worse mockup than an
// honest offline placeholder. Species id is the identity the payload actually has.
export function spriteInitials(name) {
  return (name || '?').slice(0, 3).toUpperCase();
}
