# P3 — server-side literal census for the pureRGB adapter (tree ddafb83)

Scope: the vanilla-bound facts in `server/adapters/gen1_rby.py`, `gen1_codec.py`, `gen1_rom_scan.py`, `adapters/__init__.py`, `server/data/items/gen1.py`, and the places `server/server.py`, `server/manager.py`, `server/upr_pipeline.py`, `server/patcher.py`, `tools/make_release.py`, `tools/gen_ui_capabilities.py` name `gen1_rby` / a Gen 1 rom_type. Every `file:line` below was opened at the current tree (`ddafb83`); every literal cell is the verbatim first 80 characters of that line, re-read by script, not transcribed.

**The pure pack already exists** (`data/games/gen1_purergb/`): `profile.json` (titles `purered`/`pureblue`/`puregreen`, each with `variant`, `rom_sha1`, `sym`, `ram` (178 symbols), `rom` (62 symbols), `sram_bank`, `derived`), `engine_signals.json`, `write_checkpoint.json` (keys `purered`/`pureblue`/`puregreen`), `admission.json` (sha1 → `{kind, title, header_title, header_crc, md5, crc32, size, profile_id}`). The **vanilla** `data/games/gen1_rby/profile.json` also has a `derived` block, but only the nine geometry fields (`party_struct_size`, `box_struct_size`, `box_capacity`, `party_capacity`, `name_length`, `battle_struct_size`, `sram_box_stride`, `sram_boxes_per_bank`, `sram_box_banks`); the fields pureRGB actually needs (`bag_capacity` 30, `ball_items` `[1,2,3,4,5,8]`, `base_stats_stride` 35, `dex_count` 152, `opp_id_offset` 197, `species_count` 190, `rival_trainer_ids` `[221,237,238]`, `hardware` `cgb`, `wram_bank_gate` true) exist **only** in the pure pack. Either the pure adapter reads them from there, or M1 must emit Python constants of the same shape; this file names the option it takes.

## 1. Literals and their replacements

| file:line | literal / assumption (first 80 chars, verbatim) | what replaces it for `gen1_purergb` | consumer(s) |
|---|---|---|---|
| `server/adapters/gen1_rby.py:21` | `_DATA = Path(__file__).resolve().parents[2] / "data" / "games" / "gen1_rby"` | `data/games/gen1_purergb/` — the subclass sets its own `_DATA` (or `_json` takes a foundation root) | every module-level table below; `_json` |
| `server/adapters/gen1_rby.py:29` | `_AREAS = _json("area_map.json")` | data/games/gen1_purergb/area_map.json (M1/W1: 248 maps, 69 areas, ids renumbered) | `_AREA_BY_MAP`, `area_display_name`, `ingest_rom_content` |
| `server/adapters/gen1_rby.py:34` | `_INDEX_JSON = {int(key): int(value)` | data/games/gen1_purergb/species_index.json (A13: 190 entries, 13 non-dex, `MISSINGNO $B5`) | `ingest_rom_content` → `build_encounter_tables` |
| `server/adapters/gen1_rby.py:36` | `_FAMILY = {int(key): int(value) for key, value in _json("evolutions.json")["fami` | data/games/gen1_purergb/evolutions.json (vanilla families + the level-37 trade-evo entries + `transform` edges) | `evo_family` |
| `server/adapters/gen1_rby.py:37` | `_ENCOUNTERS = _json("encounter_tables.json")` | data/games/gen1_purergb/encounter_tables.json (W1: grass+water+fishing, dex-0 rows kept) | `encounter_table`, `_GEN1_ENCOUNTERS` |
| `server/adapters/gen1_rby.py:38` | `_MOVES = {int(row["id"]): row for row in _json("moves.json")["moves"]}` | data/games/gen1_purergb/moves.json | `move_name`, `move_data` |
| `server/adapters/gen1_rby.py:39` | `_TRAINERS = _json("trainers.json")` | data/games/gen1_purergb/trainers.json (56 classes, `OPP_ID_OFFSET` 197) | `rival_trainer_ids`, `trainer_info` |
| `server/adapters/gen1_rby.py:42` | `_TYPE_NAMES = {` | data/games/gen1_purergb/types.json — type names change only if pureRGB renames a type (23 species are retyped; verify at M1) | `type_name`, `move_data` (`_TYPE_ID`) |
| `server/adapters/gen1_rby.py:49` | `_SPLIT = {"Physical": 0, "Special": 1, "Status": 2}` | no change — `Physical`/`Special`/`Status` vocabulary is pureRGB's too | `move_data` |
| `server/adapters/gen1_rby.py:55` | `_NATIONAL_TYPES = (` | data/games/gen1_purergb/types.json (default typings + the 13 non-dex records) | `species_types` |
| `server/adapters/gen1_rby.py:214` | `_GIFT_AREAS = frozenset({` | data/games/gen1_purergb/static_encounters.json (+ new maps: `bills_garden`, `secret_lab`, `diamond_mine`, …) | `is_gift_area` |
| `server/adapters/gen1_rby.py:225` | `_FIXED_GIFTS = frozenset({"celadon_mansion_roof", "mt_moon_pokecenter", "silph_c` | same pack file | `is_fixed_species_gift` |
| `server/adapters/gen1_rby.py:239` | `_STATIC_SITES = frozenset({` | data/games/gen1_purergb/static_encounters.json (W2 statics, incl. the double-encoded roof Zapdos) | `is_gift_area`, `is_fixed_species_gift`, `area_display_name` |
| `server/adapters/gen1_rby.py:243` | `_STATIC_ID = re.compile(r"static_(\d+)_(\d+)\Z")` | no change — `static_<map>_<natdex>` is the plan's static namespace (decision 4) and `\d+` admits dex 0 (`MISSINGNO`) | `is_gift_area`, `is_fixed_species_gift`, `area_display_name` |
| `server/adapters/gen1_rby.py:244` | `_KEY = re.compile(r"[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}\Z")` | no change — the key is still `DVs:OTID:internal species` (`FFFF:OTID:SS` after an APEX CHIP) | `is_valid_mon_key`, `parse_ot_id`, `key()` |
| `server/adapters/gen1_rby.py:245` | `_ROM_VARIANT = {"Red": "red", "red": "red", "red_ap": "red",` | registry rows + a fail-closed variant map in the pure adapter (`PureRed`→`purered`, …); see `__init__.py:45-49` | `__init__` (line 262) |
| `server/adapters/gen1_rby.py:261` | `        rom_type = kwargs.get("rom_type") or "red"` | fail closed — an unrecognised `rom_type` must raise, not default to red (PLAN §4 row 2) | `__init__` |
| `server/adapters/gen1_rby.py:262` | `        self._variant = _ROM_VARIANT.get(rom_type, "red")` | same; the `"red"` default is the silent-wrong-adapter bug the registry comment in `__init__.py:57-64` describes for Gen 2 | `__init__` |
| `server/adapters/gen1_rby.py:267` | `    def game_id(self) -> str:` | `"gen1_purergb"` (registry key; `server.py` adapter switch, manager `OPTION_SUPPORT`, `ui_capabilities`) | `server.py:424-425`, `manager.option_support` |
| `server/adapters/gen1_rby.py:318` | `    def rival_trainer_ids(self) -> set[int]:` | `profile.derived.rival_trainer_ids` (already `[221, 237, 238]`) or `trainers.json` | state rival-swap gate (`_handle_trainer_battle_start`) |
| `server/adapters/gen1_rby.py:322` | `    def party_blob_size(self) -> int:` | no change — 44-byte struct + 2×11-byte names = 66 in pureRGB too (PLAN §3.2) | `validate_party_blob`, server blob cache |
| `server/adapters/gen1_rby.py:347` | `    def supports_info_panel(self) -> bool:` | overlay-built titles only — the panel ships in the pure overlay, not in the clean ROM | `ui_capabilities`, status page |
| `server/adapters/gen1_rby.py:351` | `    def native_trade_ui(self) -> bool:` | overlay-built titles only (M3); the clean-ROM pure runs use the Lua trade path | state trade FSM (6 call sites) |
| `server/adapters/gen1_rby.py:355` | `    def info_panel_width(self) -> int:` | no change if 347 holds (20-tile Game Boy width) | presentation |
| `server/adapters/gen1_rby.py:359` | `    def sprite_src(self, species_id: int) -> str:` | needs a per-foundation sprite source: pureRGB's forms/MissingNo have no PokeAPI Generation-I URL; base 151 can stay | `sprite_html`, `area_display_name` |
| `server/adapters/gen1_rby.py:394` | `    def item_name(self, item_id: int) -> str:` | a pureRGB item table (`HYPER_BALL` replaces `TOWN MAP` at `$05`, `APEX_CHIP` at `$32`, 30-slot bag, 60 PC items) | `item_name`, held-item display |
| `server/adapters/gen1_rby.py:397` | `    def area_display_name(self, area_id: str) -> str:` | data/games/gen1_purergb/area_map.json (`name` per area) | status page, encounter table |
| `server/adapters/gen1_rby.py:408` | `    def to_national_dex(self, species_id: int) -> int:` | the pack's dex order (`species_index.json`) | state clauses, presentation |
| `server/adapters/gen1_rby.py:418` | `    def move_name(self, move_id: int) -> str:` | data/games/gen1_purergb/moves.json | `move_data`, presentation |
| `server/adapters/gen1_rby.py:422` | `    def move_data(self, move_id: int) -> dict \| None:` | same pack file + a per-foundation type-id map | presentation, calc payload |
| `server/adapters/gen1_rby.py:431` | `    def encounter_table(self, area_id: str) -> dict[str, list[dict]] \| None:` | data/games/gen1_purergb/encounter_tables.json keyed by `purered`/`pureblue`/`puregreen` (note pureRGB's fishing formats differ: good rod = 4 pairs + `-1,-1` + an ocean list) | `encounter_table`, `ingest_rom_content` |
| `server/adapters/gen1_rby.py:448` | `    def ingest_rom_content(self, payload: dict) -> dict[str, dict[str, list[dict` | a foundation-aware scanner (`build_encounter_tables` needs the pure area map, dex order and names) | rom-content path (`use_rom_encounters`) |
| `server/adapters/gen1_rby.py:456` | `    def rom_content_fingerprint(self, payload: dict) -> str \| None:` | same — `content_fingerprint` walks pureRGB's wild/fishing formats (M5 fingerprint) | UPR admission (`upr_pipeline.py:315`) |
| `server/adapters/gen1_rby.py:470` | `    def mons_per_box(self) -> int:` | no change — 12 boxes × 20 (PLAN §3.2) | `mons_per_box` |
| `server/adapters/gen1_rby.py:475` | `    def memorial_box_index(self) -> int:` | no change — 12 boxes; the memorial box stays index 11 | memorialize path |
| `server/adapters/gen1_codec.py:35` | `PARTY_MON_SIZE, BOX_MON_SIZE = 44, 33  # constants/pokemon_data_constants.asm:47` | no change — party 44 / box 33 in pureRGB (`P:constants/pokemon_data_constants.asm`) | `decode_party_mon`, `_decode_collection` |
| `server/adapters/gen1_codec.py:36` | `PARTY_CAPACITY, BOX_CAPACITY, BOX_COUNT = 6, 20, 12` | no change — 6 party, 20 per box, 12 boxes | `decode_party`, `decode_box`, `verify_boxes` |
| `server/adapters/gen1_codec.py:38` | `NAME_SIZE = 11  # constants/text_constants.asm:3` | no change — 11-byte names | `decode_name`, `encode_name` |
| `server/adapters/gen1_codec.py:39` | `NAME_END = 0x50  # constants/charmap.asm:12` | `charmap.json` — the `@` terminator must be re-derived from pureRGB's `constants/charmap.asm` | `decode_name`, `encode_name`, boxes |
| `server/adapters/gen1_codec.py:41` | `_TYPES = slice(5, 7)  # constants/pokemon_data_constants.asm:32-35` | no change — the 44-byte party struct offsets are pureRGB's (`+0x0C` OT, `+0x1B` DVs, `+0x21` level) | `decode_party_mon`, `encode_party_mon` |
| `server/adapters/gen1_codec.py:45` | `_LEVEL = 33  # constants/pokemon_data_constants.asm:48` | no change | `decode_party_mon` |
| `server/adapters/gen1_codec.py:50` | `PARTY_LAYOUT = {"count": 0, "species": 1, "mons": 8, "ot_names": 272,` | no change — the 404-byte party block layout (count 0, species 1, mons 8, OT 272, nicks 338) | `decode_party` |
| `server/adapters/gen1_codec.py:52` | `BOX_LAYOUT = {"count": 0, "species": 1, "mons": 22, "ot_names": 682,` | no change — the 1122-byte box block | `decode_box` |
| `server/adapters/gen1_codec.py:54` | `BOX_SIZE = BOX_LAYOUT["size"]` | no change | `verify_boxes` |
| `server/adapters/gen1_codec.py:59` | `WRAM_BASES = {` | `profile.ram` (`wPartyMon1`/`wBoxMons`/`wBoxCount`; pure values are `$D173`/`$DA9E`/`$DA88` vs vanilla `$D16B`/`$DA96`/`$DA80`) — a literal here reads the WRONG WRAM on a pure cart | callers of `decode_party`/`decode_box` that pass a variant base |
| `server/adapters/gen1_codec.py:66` | `SRAM_LAYOUT = {` | `profile.ram` + `profile.sram_bank` (verified equal: pure `sPlayerName $A598` in bank 1 → flat `$2598`, `sBox1 $A000` bank 2 → flat `$4000`, `sBank2AllBoxesChecksum $BA4C` → `$5A4C`) | `verify_bank1`, `verify_boxes`, `tools/e2e_duo.py:842,1697,1968,2084,2086` |
| `server/adapters/gen1_codec.py:73` | `SRAM_SIZE = 0x8000  # layout.link:195-202: four SRAM banks, $a000-$bfff per bank` | no change — 32 KiB SRAM (4 banks), same as vanilla | `decode_bag`, `verify_bank1`, `verify_boxes` |
| `server/adapters/gen1_codec.py:76` | `_CURRENT_BOX = 0x284C` | derive from `profile` (`sMainData + wCurrentBoxNum - wMainDataStart`); pureRGB happens to give the SAME `$284C` (both symbols are +8), so a literal passes silently here | `verify_boxes`, `tools/e2e_duo.py:2600,2654` |
| `server/adapters/gen1_codec.py:84` | `_BAG_COUNT = 0x25C9` | derive the same way — pureRGB gives **`$27E6`**, not `$25C9` (delta `wNumBagItems - wMainDataStart` = `$243` vs vanilla `$26`): the literal reads the wrong byte on a pure save | `decode_bag`, `bag_quantity`, `tools/e2e_duo.py:823` |
| `server/adapters/gen1_codec.py:85` | `BAG_CAPACITY = 20  # constants/item_constants.asm: MAX_ITEMS` | `profile.derived.bag_capacity` (30) | `decode_bag` |
| `server/adapters/gen1_codec.py:86` | `POKE_BALL = 0x04  # constants/item_constants.asm; lua/games/gen2_crystal.lua:44 ` | `profile.derived.ball_items` (`{1,2,3,4,5,8}`) | `tools/gen_gen1_profile.py:158`, `tools/e2e_duo.py:2110-2111` |
| `server/adapters/gen1_codec.py:90` | `_CHARMAP = {` | `charmap.json` (A10: `$9e/$9f` → quotes, `$33-$4d` text shortcuts) | `decode_name`, `encode_name`, `boxes.py` nickname round-trip |
| `server/adapters/gen1_codec.py:247` | `_DEX_ORDER = (` | data/games/gen1_purergb/species_index.json (dex 0 for the 13 non-dex records, `MISSINGNO` = `$B5`) | `internal_to_natdex`, `natdex_to_internal`, `evo_family`, `species_name` |
| `server/adapters/gen1_codec.py:439` | `_NATDEX_TO_INTERNAL = {dex: idx for idx, dex in enumerate(_DEX_ORDER, 1) if dex}` | rebuild from the pack's dex order | `natdex_to_internal` |
| `server/adapters/gen1_codec.py:723` | `GROWTH_RATES = ((1, 1, 0, 0, 0), (3, 4, 10, 0, 30), (3, 4, 20, 0, 70),` | no change — the six growth curves are identical; the per-species curve comes from the ROM scan | `exp_for_level`, `level_from_exp` |
| `server/adapters/gen1_rom_scan.py:59` | `_SYMS_PATH = os.path.join(_REPO, "data", "pret_rom_syms.json")` | a per-foundation symbol source (`data/purergb/*.sym`; the pack's `profile.json` names `sym: pokered.sym`) | `_load_syms`, `identify`, `_syms_for` |
| `server/adapters/gen1_rom_scan.py:64` | `_HEADER_TITLE_TO_SYMS = {` | `admission.json` (sha1 → `{header_title, header_crc, kind, title}`): PureRed/PureBlue carry the SAME header titles as vanilla Red/Blue, so this map alone cannot identify them | `identify` → `upr_pipeline.py:129`, e2e gates |
| `server/adapters/gen1_rom_scan.py:70` | `_SYMS_TO_VARIANT = {"pokered": "red", "pokeblue": "blue", "pokeyellow": "yellow"` | pure variant keys (`purered`/`pureblue`/`puregreen`) | `identify` |
| `server/adapters/gen1_rom_scan.py:72` | `BASE_STATS_RECORD = 28` | `profile.derived.base_stats_stride` (35); the literal raises on pureRGB | `scan_base_stats` |
| `server/adapters/gen1_rom_scan.py:73` | `BASE_STATS_COUNT = 150            # R/B: Bulbasaur..Mewtwo; Mew is stored apart` | `profile.derived.dex_count` (the pack says 152) — and the `"MewBaseStats" in syms` predicate below is a vanilla-title heuristic: pureRGB has NO `MewBaseStats` (verified absent from the pack's `rom` symbols) so it takes the Yellow branch by accident | `scan_base_stats` |
| `server/adapters/gen1_rom_scan.py:74` | `BASE_STATS_COUNT_YELLOW = 151     # Yellow keeps Mew IN the table, at record 150` | same as 73 (the Yellow branch is the one pureRGB lands in) | `scan_base_stats` |
| `server/adapters/gen1_rom_scan.py:75` | `WILD_SLOTS = 10                   # both grass and water always carry exactly te` | no change — 10 slots per block | `_read_slots`, `parse_wild_record` |
| `server/adapters/gen1_rom_scan.py:78` | `_SLOT_RATES = (20, 20, 15, 10, 10, 10, 5, 5, 4, 1)   # data/wild/probabilities.a` | no change — pureRGB keeps vanilla's slot chances (PLAN §3.5) | `slot_rates`, `parse_client_content` |
| `server/adapters/gen1_rom_scan.py:336` | `NUM_POKEMON_INDEXES = 190         # pointer table length; internal indexes, Miss` | `profile.derived.species_count` (190 — same value, still a literal) | `scan_evos_moves` |
| `server/adapters/gen1_rom_scan.py:498` | `MAX_CLIENT_MAPS = 512               # 249 real entries; a payload larger than th` | no change — 248 map pointers (`NUM_MAPS $F8`) | `parse_client_content` |
| `server/adapters/__init__.py:45` | `    "Red": "gen1_rby", "Blue": "gen1_rby", "Yellow": "gen1_rby",` | add `PureRed`/`PureBlue`/`PureGreen` → `gen1_purergb` (the string the client should send comes from the pack's `admission.json.title`/`profile.variant`) | `game_id_for_rom_type` (`server.py:424,1207,1239`, `manager.py:153`, `gen_ui_capabilities.py:49`) |
| `server/adapters/__init__.py:46` | `    "red": "gen1_rby", "blue": "gen1_rby", "yellow": "gen1_rby",` | same (lowercase spellings) — keep both, because `rom_type` is persisted per run | same |
| `server/adapters/__init__.py:49` | `    "red_ap": "gen1_rby", "blue_ap": "gen1_rby",` | no change (AP spellings stay on `gen1_rby`) | same |
| `server/adapters/__init__.py:76` | `    "Red": "Red", "Blue": "Blue", "Yellow": "Yellow",` | add labels for the three pure titles | `variant_label` (`server.py:976,991`) |
| `server/adapters/__init__.py:77` | `    "red": "Red", "blue": "Blue", "yellow": "Yellow",` | same | same |
| `server/adapters/__init__.py:78` | `    "red_ap": "Red (AP)", "blue_ap": "Blue (AP)",` | no change | same |
| `server/adapters/__init__.py:124` | `from .gen1_rby import Gen1Adapter  # noqa: E402` | import the new class (`Gen1PureRGBAdapter`) | registry |
| `server/adapters/__init__.py:126` | `register_adapter("gen1_rby", Gen1Adapter)` | `register_adapter("gen1_purergb", Gen1PureRGBAdapter)` | `available_game_ids`, `get_adapter` |
| `server/data/items/gen1.py:8` | `ITEM_NAMES = {` | a pureRGB item table (`HYPER_BALL $05`, `APEX_CHIP $32`; 150 vanilla entries cannot describe either) | `Gen1Adapter.item_name`, held-item display |
| `server/server.py:423` | `        rom_type = self.connected_players.get(player_id, {}).get("rom_type", "")` | no change — the rom_type→game_id route is generic | adapter resolution |
| `server/server.py:424` | `        game_id = game_id_for_rom_type(rom_type) or self.adapter.game_id` | no change once the registry rows exist (falls back to the running adapter) | same |
| `server/server.py:425` | `        adapter = get_adapter(game_id, is_rr=self.state.is_rr, rom_type=rom_type` | no change | same |
| `server/server.py:1207` | `                    if _rt and not game_id_for_rom_type(_rt):` | no change — unknown rom_types are already refused loudly | hello guard |
| `server/server.py:1239` | `                        new_game_id = game_id_for_rom_type(rom_type)` | no change — the set-once adapter switch | adapter lock |
| `server/manager.py:62` | `    ("gen1", "Red · Blue · Yellow", ["red", "blue", "yellow"]),` | new row: `("gen1_purergb", "PureRed · PureBlue · PureGreen", ["purered","pureblue","puregreen"])` | `new_run_form`, `option_support`, launcher |
| `server/manager.py:100` | `    "gender_lock": {"all": True, "gen1_rby": {"ok": False, "why": "Gen 1 has no ` | `OPTION_SUPPORT` needs a `gen1_purergb` key (gender: no — no gender mechanic) | `option_support` (`manager.py:149`) |
| `server/manager.py:103` | `                     "gen1_rby": {"ok": True, "why": "No patch needed — Explosio` | `gen1_purergb` key (explode: yes — plaintext enemy party) | same |
| `server/manager.py:111` | `                      "gen1_rby": {"ok": False, "why": "The Gen 1 companion patc` | `gen1_purergb` key (native sounds: no) | same |
| `server/manager.py:114` | `                    "gen1_rby": {"ok": False, "why": "The calculator is pinned t` | `gen1_purergb` key (battle calc: no) | same |
| `server/manager.py:177` | `        "gen1_games": [k for k, _, m in GAMES if m and all(rt in ("red", "blue",` | extend the `gen1_games` literal tuple with the pure rom_types, or it silently excludes the pure lanes from the template | `new_run_form` |
| `server/upr_pipeline.py:38` | `from server.adapters.gen1_rom_scan import (` | import a foundation-aware scanner | UPR prepare |
| `server/upr_pipeline.py:129` | `    from server.adapters.gen1_rom_scan import identify` | `identify()` must accept the pure ROMs (admission table, not the header title) | `upr_pipeline.prepare` |
| `server/upr_pipeline.py:187` | `    if info["version"] and info["version"] != SUPPORTED_UPR_VERSION:` | `4.6.1-slink1` at M5 | version gate |
| `server/upr_pipeline.py:315` | `    from server.adapters.gen1_rom_scan import fingerprint_rom, profile_hash` | `fingerprint_rom`/`profile_hash` over pureRGB's wild/fishing/base-stat formats | UPR admission diff |
| `server/patcher.py:48` | `    "rr": {` | no change (RR target) | patcher routes |
| `server/patcher.py:59` | `        "slug":        "rb-red",` | new `pure-red`/`pure-blue`/`pure-green` rows (base = the pure ROM md5/CRC, patch = M3's UPS) | `server/patcher.py` TARGETS page |
| `server/patcher.py:68` | `    "rb-blue": {` | same as 59 | same |
| `tools/make_release.py:130` | `    "gen1_rby": [` | add a `gen1_purergb` row with the pack files the client reads (profile, engine_signals, write_checkpoint, area_map, static_encounters + the rest of the pack) | release zip manifest |
| `tools/make_release.py:131` | `        # Read by lua/gen1/entry.lua: memory profile, engine signal sites, the w` | same | same |
| `tools/gen_ui_capabilities.py:44` | `ROM_TYPES = sorted(_ROM_TYPE_TO_GAME_ID)` | no change — the generator reads the routing table, so the pure rom_types appear once `__init__.py` rows land; the emitted fixture must be regenerated | `tools/gen_ui_capabilities.py` |

## 2. `Gen1Adapter` public method inventory (40 methods defined in `gen1_rby.py`)

**21 data-bound / 19 inherit.** "Inherit" means the body survives unchanged *provided* the codec/registry layer it calls is parametrised; it is not a claim that the method is untouched by the port.

| method (line) | verdict | why |
|---|---|---|
| `__init__` (`gen1_rby.py:260`) | data-bound | `rom_type` → `_variant` with a `"red"` fallback (261-262); must fail closed for an unknown pure variant |
| `game_id` (`gen1_rby.py:267`) | data-bound | returns the literal `"gen1_rby"` |
| `is_gift_area` (`gen1_rby.py:270`) | data-bound | `_GIFT_AREAS` + the `_STATIC_SITES` map-id/dex set |
| `is_fixed_species_gift` (`gen1_rby.py:277`) | data-bound | `_FIXED_GIFTS` + `_STATIC_SITES` |
| `evo_family` (`gen1_rby.py:282`) | data-bound | `_FAMILY` (evolutions.json) + the codec dex order |
| `gender_from_key` (`gen1_rby.py:291`) | inherit | returns `""` — Gen 1 has no gender byte; pureRGB does not add one |
| `species_types` (`gen1_rby.py:295`) | data-bound | `_NATIONAL_TYPES` (the 151-entry tuple); pureRGB retypes 23 species and adds 13 non-dex records |
| `is_shiny` (`gen1_rby.py:299`) | inherit | returns `False` — no shiny predicate in the Gen 1 struct |
| `parse_ot_id` (`gen1_rby.py:303`) | inherit | splits the key on `:` |
| `is_valid_mon_key` (`gen1_rby.py:306`) | inherit | `_KEY` regex; the `DVs:OTID:species` format is unchanged (an APEX CHIP still yields `FFFF:OTID:SS`) |
| `species_name` (`gen1_rby.py:309`) | data-bound | `_natdex` (codec dex order) + `server.pokemon_data.species_name` |
| `type_name` (`gen1_rby.py:315`) | data-bound | `_TYPE_NAMES` (own copy of the type-name map) |
| `rival_trainer_ids` (`gen1_rby.py:318`) | data-bound | scans `_TRAINERS["classes"]` for the class named `Rival`; pureRGB renumbers classes and the id offset (197) |
| `party_blob_size` (`gen1_rby.py:322`) | inherit | `PARTY_MON_SIZE + 2*NAME_SIZE` = 66; geometry unchanged |
| `validate_party_blob` (`gen1_rby.py:326`) | inherit | pure logic over `gen1_codec.decode_party_mon` |
| `supports_abilities` (`gen1_rby.py:337`) | inherit | `False` |
| `supports_explode_mode` (`gen1_rby.py:340`) | inherit | `True` (Gen 1 needs no patch; PLAN/manager row) |
| `status_token` (`gen1_rby.py:343`) | inherit | `gb_status_token`; status bits are unchanged |
| `supports_info_panel` (`gen1_rby.py:347`) | data-bound (variant) | `self._variant != "yellow"` — for pureRGB the capability comes from the *artifact kind* (overlay), not the title |
| `native_trade_ui` (`gen1_rby.py:351`) | data-bound (variant) | `self._variant in ("red", "blue")` — same: overlay-built titles only |
| `info_panel_width` (`gen1_rby.py:355`) | inherit | `20 if self.supports_info_panel() else 0` |
| `sprite_src` (`gen1_rby.py:359`) | data-bound | hardcodes the PokeAPI `generation-i/red-blue/transparent/{dex}.png` URL; pureRGB's 13 non-dex records resolve to a base dex |
| `sprite_html` (`gen1_rby.py:366`) | inherit | markup around `sprite_src` |
| `ability_name` (`gen1_rby.py:380`) | inherit | returns `""` |
| `ability_description` (`gen1_rby.py:383`) | inherit | returns `""` |
| `trainer_info` (`gen1_rby.py:386`) | data-bound | `_TRAINERS["classes"]`/`["named_trainers"]` |
| `item_name` (`gen1_rby.py:394`) | data-bound | `ITEM_NAMES` from `server/data/items/gen1.py` — pureRGB's ids differ (`HYPER_BALL $05`, `APEX_CHIP $32`) |
| `area_display_name` (`gen1_rby.py:397`) | data-bound | `_AREA_NAMES` + `_STATIC_SITES` + `national_species_name` |
| `to_national_dex` (`gen1_rby.py:408`) | data-bound | delegates to the codec dex order |
| `gender_symbol` (`gen1_rby.py:412`) | inherit | returns `""` |
| `form_sprite_id` (`gen1_rby.py:415`) | inherit | returns `None`; pureRGB's forms map to their base dex, so this stays right unless distinct art is wanted |
| `move_name` (`gen1_rby.py:418`) | data-bound | `_MOVES` (moves.json) |
| `move_data` (`gen1_rby.py:422`) | data-bound | `_MOVES` + `_TYPE_ID` + `_SPLIT` for the calc payload |
| `encounter_table` (`gen1_rby.py:431`) | data-bound | `_ENCOUNTERS[self._variant]` or the ROM-scanned tables |
| `ingest_rom_content` (`gen1_rby.py:448`) | data-bound | `build_encounter_tables(content, _AREA_BY_MAP, _INDEX_JSON, national_species_name)` |
| `rom_content_fingerprint` (`gen1_rby.py:456`) | data-bound | `content_fingerprint(variant, wild, fishing)` — pureRGB's walkers differ |
| `use_rom_encounters` (`gen1_rby.py:462`) | inherit | plain setter for `_rom_encounters` |
| `stat_stage_labels` (`gen1_rby.py:465`) | inherit | fixed label list (7 slots, 6 Gen 1 mods) |
| `mons_per_box` (`gen1_rby.py:470`) | inherit | `gen1_codec.BOX_CAPACITY` |
| `memorial_box_index` (`gen1_rby.py:475`) | inherit | `gen1_codec.BOX_COUNT - 1` |

Eight further public methods come from the ABCs and are **not** defined here: `is_daycare_area` (`base.py:84`), `gift_link_area` (`base.py:95`), `is_egg_pickup_area` (`base.py:111`), `form_sprite_url` (`base.py:363`), `trainers_for_area` (`base.py:421`), `trainer_party` (`base.py:429`), `trainer_brief` (`base.py:438`), `gym_badge_slugs` (`base.py:511`). The first three are shared rules logic (no change); the panel/trainer four are inert defaults unless the pure overlay wants them; `gym_badge_slugs` is the badge strip (`ui_capabilities` reads it).
## 3. Traps the port must not walk into (all values read from the tree, not from memory)

1. **`gen1_codec._BAG_COUNT` is wrong for pureRGB by `$21D`.** The literal is `$25C9`, derived as `sMainData + (wNumBagItems - wMainDataStart)`: vanilla's own citation (`gen1_codec.py:80-82`) gives `wMainDataStart=$D2F7`, `wNumBagItems=$D31D`, delta `$26` → `$25A3+$26 = $25C9`. The pure profile gives `wMainDataStart=$D2FF`, `wNumBagItems=$D542` (`profile.json` → `titles.purered.ram`), delta `$243` → **`$27E6`**. A port that keeps the literal reads the wrong SRAM byte and `decode_bag`/`bag_quantity` silently return garbage or nothing. (`tools/e2e_duo.py:823` reads the same private constant.)
2. **`gen1_codec._CURRENT_BOX` survives by coincidence.** Same derivation with `wCurrentBoxNum`: vanilla `$D5A0-$D2F7 = $2A9`, pureRGB `$D5A8-$D2FF = $2A9` — both `$284C`. Derive it anyway; a future pureRGB version that moves one symbol and not the other silently breaks `verify_boxes`.
3. **`gen1_codec.WRAM_BASES` reads the wrong WRAM on a pure cart.** The literal is `red/blue: party $D163, box $DA80` / `yellow: $D162/$DA7F`; the pure profile has `wPartyMon1 $D173`, `wBoxCount $DA88`, `wBoxMons $DA9E`. Only the *base* moves (`wPartyCount $D16B` vs `$D163`).
4. **`gen1_rom_scan.BASE_STATS_RECORD = 28` fails loudly (good) — but fix it to 35, not to 34.** `profile.json` → `derived.base_stats_stride` = 35; the scan raises `the 28-byte stride or the BaseStats symbol is wrong` on the first record, so this one cannot go unnoticed.
5. **`MewBaseStats` does not exist in pureRGB.** Set difference over the two profiles' `rom` symbol tables leaves exactly `MewBaseStats` on the vanilla side and nothing on the pure side. `scan_base_stats`'s `if "MewBaseStats" in syms` predicate therefore takes the *Yellow* branch for pureRGB — the right count (151 inline records, per PLAN §3.3) for the wrong reason. Replace the predicate with `derived.dex_count`/an explicit inline-Mew flag.
6. **`derived.dex_count` is 152 while the code's bound is `151`.** The pure pack's `derived.dex_count = 152` matches `NUM_POKEMON = 152` with `DEX_MISSINGNO = 0` (PLAN §3.3), i.e. dex ids run 0..151; the code's `dex > 151` bound is therefore *right*, but a naive `bounded by derived.dex_count` port becomes an off-by-one that also admits dex 152. Resolve the naming at M1 (count including 0 vs max id).
7. **The ROM header title cannot identify a pure cartridge.** `admission.json` gives `header_title` = `POKEMON RED` / `POKEMON BLUE` for the pure titles — identical to vanilla, and `_HEADER_TITLE_TO_SYMS` maps those to `pokered`/`pokeblue`. Identification must go through the `admission.json` sha1 table (with `header_crc` as a tiebreak), which is also what `_SYMS_PATH`/`_load_syms`'s `clean` flag must be replaced by.
8. **The current adapter never sees a profile.** `Gen1Adapter.__init__` takes only `**kwargs` (`rom_type`) and every table is module-level `_json(...)` off `data/games/gen1_rby`. To consume `profile.derived`, the pure subclass must load the pack itself (or `_json` must take a foundation root) — there is no existing plumbing to pass a profile into the adapter.
9. **`tools/gen_ui_capabilities.py:44` derives its rom_type list from the routing table.** Adding the registry rows without regenerating makes the editor fixture and the server disagree about which rom_types exist; the fixture is a build artefact, not a source of truth.

## 4. Confirmed no-change (verified against the pure pack, not assumed)

- Struct geometry: party 44 / box 33 / 6 / 20 / 12, 11-byte names, 404-byte party block, 1122-byte box block, 32 KiB SRAM — the pure profile's `derived` carries the same values (`party_struct_size` 44, `box_struct_size` 33, `sram_box_stride` 1122, `sram_boxes_per_bank` 6, `sram_box_banks` `[2,3]`).
- SRAM *flattening*: `sPlayerName $A598`@bank1 → flat `$2598`, `sMainData $A5A3` → `$25A3`, `sPartyData $AF2C` → `$2F2C`, `sCurBoxData $B0C0` → `$30C0`, `sMainDataCheckSum $B523` → `$3523`, `sBox1 $A000`@bank2 → `$4000`, `sBox7`@bank3 → `$6000`, `sBank2/3AllBoxesChecksum $BA4C` → `$5A4C`/`$7A4C`: all identical to `SRAM_LAYOUT`, so `verify_bank1`/`verify_boxes` keep working once the table is read from `profile.ram` + `profile.sram_bank`.
- `_KEY` format, `_STATIC_ID` namespace, `WILD_SLOTS` 10, `_SLOT_RATES`, `MAX_CLIENT_MAPS` 512, `GROWTH_RATES`, `party_blob_size` (66), status bits, `mons_per_box`, `memorial_box_index`.

---

Counts: literals 95 across 11 files | methods 40 (21 data-bound, 19 inherit) | traps 9.
