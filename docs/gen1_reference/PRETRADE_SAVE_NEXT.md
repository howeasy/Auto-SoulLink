# Full pre-trade save: remaining integration boundary

The subsequent [receptionist/save runtime](RECEPTIONIST_SAVE_RUNTIME.md) implements
this boundary with source-derived full copies under the owned hold, actual file
verification before COMMIT and24 original-engine comparisons. The source notes
below explain the requirement; they are no longer an unimplemented save task.

The pinned R/B and Yellow receptionist paths call the original `SaveGameData`
after their save confirmation, before proceeding into Cable Club. The relevant
source is `.cache/pret/pokered/engine/link/cable_club_npc.asm:67` and
`.cache/pret/pokeyellow/engine/link/cable_club_npc.asm:70`, under the existing
`data/pret_sources.lock.json` pins.

`SaveGameData` sets `wSaveFileStatus`, calls `SaveMainData`, calls
`SaveCurrentBoxData`, and then enters `SavePartyAndDexData`. Definitions are in
R/B `engine/menus/save.asm:290` and Yellow `engine/menus/save.asm:274`.
The current SLink native trade calls only `SavePartyAndDexData`: R/B line266,
Yellow line248. Yellow also saves its Pikachu happiness/state there. A verified
file flush of this result does not establish current world/current-box freshness.

The remaining production sequence must qualify a full original save before
COMMIT, bind its complete file evidence to the same participants and physical
contexts, and preserve it through interruption. It needs original-engine
differentials with changed world/current-box data and immediate reset/reload,
including Yellow/Yellow and approved randomized cartridges. Calling the save
routine alone is not sufficient evidence for the complete recovery lifecycle.

Reuse the shared command journal/executor, frame windows and owned SaveRAM
provider. Keep save spans, native routine entry, WRAM/SRAM correspondence and
Pikachu behavior in RBY adapters. A new shared module is warranted only for a
concrete orchestration mechanism that otherwise duplicates those foundations.

The complete native command service now includes full-save preparation. Ordinary
gameplay/default-launcher activation and full release completion remain separate.
