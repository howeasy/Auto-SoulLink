// Capability resolution — brief §4. Capability is a property of the CARTRIDGE
// (rom_type), not of the generation, and it is resolved PER PLAYER (brief §5).
//
// capabilities.json enumerates every rom_type the client can send, so this is a
// straight lookup: `blue` has its own row, not `red`'s borrowed. No aliasing, no
// inference — a miss here means the client sent something the generator does not
// know about, which is a real unknown and is rendered as one.

// Human label for a cartridge. Per brief §5 the game label lives on the PLAYER chip,
// because the two players can hold different versions of the same generation.
const LABEL = {
  red: 'Red', blue: 'Blue', green: 'Green', yellow: 'Yellow',
  crystal: 'Crystal', gold: 'Gold', silver: 'Silver',
  firered: 'FireRed', leafgreen: 'LeafGreen',
  // No leafgreen_rr: Radical Red is a FireRed hack and has no LeafGreen build.
  firered_rr: 'FireRed · Radical Red',
  heartgold: 'HeartGold', soulsilver: 'SoulSilver',
  pokemon_black: 'Black', pokemon_white: 'White',
};

export function romLabel(romType) {
  if (!romType) return 'unknown cartridge';
  return LABEL[romType] || romType;
}

/**
 * @returns {{found:boolean, key:string|null, caps:object}}
 * `found:false` means we genuinely do not know — render unknown, never false.
 */
export function capsFor(capabilities, romType) {
  const caps = capabilities?.[romType];
  return caps ? { found: true, key: romType, caps } : { found: false, key: null, caps: {} };
}

// Tri-state predicate: true / false / null(unknown). `null means unknown` — brief §4.
export function tri(capsResult, name) {
  if (!capsResult.found) return null;
  const v = capsResult.caps[name];
  return v === undefined || v === null ? null : v;
}

// Held items are deliberately NOT a capability (brief §4). Decide from the data:
// if no mon in this player's payload carries a non-zero held_item_id, the column
// has nothing to show, so it does not exist.
export function hasHeldItems(player) {
  const party = Object.values(player?.party_details || {});
  const boxed = player?.pc_boxes || [];
  return [...party, ...boxed].some((m) => Number(m?.held_item_id || 0) > 0);
}

// Run options and where their availability comes from. Brief §4:
// Explode Mode and Rival Swap are available on Gen 1 with no patch; Overworld
// Presence / Native Messages / Native Sounds / Battle Calc are Gen 3 only.
export const RUN_OPTIONS = [
  { key: 'species_lock', label: 'Species Clause', gate: null },
  { key: 'gender_lock', label: 'Gender Clause', gate: null },
  { key: 'type_lock', label: 'Type Clause', gate: null },
  { key: 'explode_mode', label: 'Explode Mode', gate: 'explode_mode' },
  { key: 'rival_team_swap', label: 'Rival Swap', gate: 'explode_mode' },
  { key: 'overworld_presence', label: 'Overworld Presence', gate: 'info_panel' },
  { key: 'native_messages', label: 'Native Messages', gate: 'info_panel' },
  { key: 'native_sounds', label: 'Native Sounds', gate: 'info_panel' },
  { key: 'battle_calc', label: 'Battle Calc', gate: 'info_panel' },
  { key: 'pc_trade_npc', label: 'PC Trade NPC', gate: null },
];
