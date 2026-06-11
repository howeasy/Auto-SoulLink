/* SLink companion patch — injected handlers (Thumb, freestanding C).
 *
 * Compiled by arm-none-eabi-gcc and linked at CODE_BASE (0x08378CA8) by slink.ld, so
 * slink_hook() sits exactly where the CallCallbacks hook `bl`s to (build.py writes that
 * 4-byte BL). Runs every frame, all contexts, main-thread. Engine functions are called
 * through fixed-address function pointers (RR preserves base FireRed addresses).
 *
 * Mailbox ABI v1 — see patch/src/ADDRESSES.md.
 */
#include <stdint.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int16_t s16; typedef int32_t s32;

#define MAILBOX_ADDR 0x0203F800u
#define SLNK_SIG     0x4B4E4C53u   /* 'SLNK' */
#define ABI_VER      1

typedef struct {
    volatile u32 signature;    /* 0  */
    volatile u16 abi_version;  /* 4  */
    volatile u16 opcode;       /* 6  */
    volatile u16 seq;          /* 8  */
    volatile u16 status;       /* 10 */
    volatile u16 ack_seq;      /* 12 */
    volatile u16 reason;       /* 14 */
    volatile u8  args[32];     /* 16 */
    volatile u8  result[16];   /* 48 */
} Mailbox;
#define MB ((Mailbox*)MAILBOX_ADDR)

enum { OP_PING = 1, OP_FORCE_FAINT = 2, OP_FORCE_MOVE = 3, OP_CREATE_MON = 4,
       OP_FORCE_MOVE_SLOT = 5, OP_SPAWN_PEER_NPC = 6, OP_DESPAWN_PEER_NPC = 7,
       OP_SHOW_MESSAGE = 8, OP_PLAY_FANFARE = 9,
       /* 10 OP_APPLY_DAMAGE, 11 OP_CURE_STATUS, 12 OP_SET_RULES: REMOVED (RR-redundant /
        * dropped features). Numbers kept RESERVED so opcodes 13+ keep their ABI slot; the
        * mailbox dispatch has no case for them -> default ack(ST_FAIL) (older-patch behavior). */
       OP_ARM_PEER_INTERACT = 13,
       OP_GHOST_SPAWN = 14, OP_GHOST_CLEAR = 15,
       OP_SET_ENEMY_PARTY = 16,
       OP_SHOW_MENU = 17,         /* native yes/no menu; async result -> mailbox result[0] */
       OP_SET_PARTY_MON = 18,     /* faithful 100-byte blob copy into gPlayerParty[slot] (trade) */
       OP_PLAY_SE = 19,           /* native sound effect via PlaySE (retires the m4a RAM-poke) */
       OP_CHOOSE_PARTY_MON = 20,  /* native "Choose a POKeMON" menu; async result[0]=slot(0-5)/7=cancel */
       OP_TRADE_SCENE = 21,       /* native trade animation+evolution: gPlayerParty[slot] <-> gEnemyParty[0] */
       OP_SHOW_CHOICES = 22,      /* native multichoice list (custom options); async result[0]=index/0x7F=cancel */
       OP_SHOW_BATTLE_MESSAGE = 23, /* native IN-BATTLE text (BizHawk-HUD replacement); re-asserted N frames */
       OP_DEPOSIT_MON = 24,       /* party -> PC box (compress): args [0]=partySlot [1]=boxId [2]=boxPos */
       OP_WITHDRAW_MON = 25,      /* PC box -> party (decompress): args [0]=boxId [1]=boxPos [2]=partySlot */
       OP_MEMORIALIZE = 26 };     /* party -> memorial box: args [0]=partySlot [1]=boxId [2]=boxPos.
                                     Deposit conversion, but removal is zero + SWAP-WITH-LAST (not
                                     shift) so survivors keep their slot indices (CFRU deferred
                                     battle writes target slots; mirrors Lua M.memorializeMon). */
enum { ST_BUSY = 1, ST_OK = 2, ST_FAIL = 3 };

/* Armed forced-move state (controller-swap driver), EWRAM scratch past the mailbox. */
typedef struct {
    volatile u8  armed, battler, move_pos, target;
    volatile u16 seq, frames;
} ArmedMove;
#define AM ((ArmedMove *)0x0203F8C0u)

/* Persistent companion-patch state (peer interaction). */
typedef struct {
    volatile u8 _rsvd0;          /* was enforce_rules (OP_SET_RULES, removed); kept to pin pi_* offsets */
    volatile u8 pi_armed;        /* peer-interaction detection on */
    volatile u8 pi_oe;           /* ghost object-event id to watch */
    volatile u8 pi_count;        /* ++ on each interact (Lua polls); also shows the box */
} SlinkState;
#define SS ((SlinkState *)0x0203F8D0u)

/* Pokémon-Center TRADE NPC (presence-OFF trade entry point). When overworld presence is toggled OFF
 * the peer ghost never spawns, so the talk-to-partner trade trigger disappears. This driver spawns a
 * real engine NPC in every Pokémon Center 1F and arms the SAME generic talk detector
 * (check_peer_interact, via SS->pi_oe) on it — so talking to it bumps SS->pi_count, the Lua client
 * emits trade_request, and the server drives the trade exactly as the ghost path does. Mutually
 * exclusive with the ghost: Lua sets `enable` ONLY when presence is OFF (when ON the ghost owns
 * pi_oe). The sentinel localId 0xF1 is distinct from the ghost's 0xF0, so drive_ghost's 0xF0 orphan-GC
 * never touches it. Lives in the free EWRAM gap between SlinkState (ends 0x0203F8D4) and
 * SLINK_SCRIPT_BUF (0x0203F8E0); all u8, 1-aligned. */
typedef struct {
    volatile u8 enable;   /* 0  Lua sets 1 when overworld presence is OFF (PC-NPC trade mode) */
    volatile u8 oeId;     /* 1  spawned object-event id (0xFF = none) */
    volatile u8 mapG;     /* 2  map group the NPC is spawned on (map-change detection) */
    volatile u8 mapN;     /* 3  map num */
} TradeNpcState;
#define TN ((TradeNpcState *)0x0203F8D4u)

/* Battle-Calc display kill switch (one byte right after TradeNpcState, still inside the free gap
 * before SLINK_SCRIPT_BUF 0x0203F8E0). INVERTED semantics: 0 (the EWRAM boot default — i.e. no Lua,
 * no config) = calc SHOWN exactly as today; 1 = the battletext shim skips the calc trampoline, so
 * the damage display never draws. Lua writes it from the server's per-run `battle_calc` toggle. */
#define SLINK_CALC_OFF 0x0203F8D8u
#define TN_LOCALID 0xF1u   /* exclusive sentinel (ghost uses 0xF0) */

/* Engine-driven peer ghost. The peer is ANOTHER real player; we reproduce THEIR avatar + THEIR
 * exact sub-pixel motion + animation. This is the proven Lua-"clone" model ported into the patch
 * (the engine spawns a real object-event for the sprite slot / collision / palette slot; we then
 * NEUTRALIZE its sprite callback and drive pos1 / animNum / palette ourselves each frame). The
 * partner broadcasts a WORLD-PIXEL position (sub-pixel, derived from currentCoords*16 + coordOffset
 * delta) at ~20 Hz; we LERP toward it so the ghost slides continuously and SPEED-AGNOSTICALLY (no
 * tile-quantized "walk-stop-walk-stop"). Placed in the free EWRAM gap between the mailbox (ends
 * 0x0203F840) and AM (0x0203F8C0); u32/s32 fields 4-aligned. */
#define GHOST_LERP_NUM   128           /* 0.5 follow gain toward the sampled target (128/256) */
#define GHOST_SNAP_PX    48            /* >this many px off -> snap (warp/desync), don't slide */
#define GHOST_LEAD_CAP_PX 12           /* max px to extrapolate past a stale target while the
                                        * partner is flagged moving (kills the reach-and-pause
                                        * stutter between ~30 Hz samples; fresh targets absorb) */
typedef struct {
    volatile u8  active;     /* 0  1 = ghost should exist + be driven */
    volatile u8  oeId;       /* 1  object-event id the hook owns (0xFF = not spawned) */
    volatile u8  gfxId;      /* 2  graphicsId to spawn (stand-in; avatar overridden after) */
    volatile u8  curGfx;     /* 3  graphicsId currently spawned */
    volatile u8  localId;    /* 4  sentinel localId (0xF0) */
    volatile u8  flags;      /* 5  bit0 = have C baseline, bit1 = have disp (else snap on first use) */
    volatile s16 wx;         /* 6  partner world-pixel x (sub-pixel target) */
    volatile s16 wy;         /* 8  partner world-pixel y */
    volatile u8  face;       /* 10 partner facing 1=S 2=N 3=W 4=E */
    volatile u8  mv;         /* 11 partner moving (1=walk/run anim, 0=idle) */
    volatile u8  pmapGroup;  /* 12 player's last map group the hook recorded */
    volatile u8  pmapNum;    /* 13 player's last map num */
    volatile u8  snap;       /* 14 Lua sets -> jump disp straight to the target (first/warp/desync) */
    volatile u8  an;         /* 15 partner's live animNum (exact animation) */
    volatile u8  run;        /* 16 partner running/biking (speed: 1 px/frame walk, 2 px/frame run) */
    volatile u8  avatarDirty;/* 17 Lua sets when imgs/anims/palette changed; C applies + clears */
    volatile u8  _pad1[2];   /* 18..19 align the u32 ptrs */
    volatile u32 imgs;       /* 20 partner's live gSprites[sid].images ROM ptr (avatar override) */
    volatile u32 anims;      /* 24 partner's live gSprites[sid].anims  ROM ptr */
    volatile s32 dispx;      /* 28 interpolated x, world-px (PLAIN px — constant-velocity follow) */
    volatile s32 dispy;      /* 32 interpolated y, world-px */
    volatile s16 cx;         /* 36 cached C baseline x (playerSprite.pos1 - playerTile*16) */
    volatile s16 cy;         /* 38 cached C baseline y */
    volatile u8  leadpx;     /* 40 px extrapolated PAST a stale target while the partner is
                              *    still moving (<= GHOST_LEAD_CAP_PX); fresh targets absorb it.
                              *    Boot-zero = no lead = the old reach-and-pause behavior. */
} GhostState;
#define GH ((GhostState *)0x0203F850u)
#define GH_F_HAVE_C    0x01u
#define GH_F_HAVE_DISP 0x02u
/* Partner's live 16-colour OBJ palette (BGR555), decoded by Lua from the `pcol` wire field. Above
 * SLINK_BLOB_BUF (ends 0x0203FC58), below EWRAM end 0x0203FFFF; 2-aligned for u16 colour writes. */
#define GHOST_PAL_BUF 0x0203FC60u

/* Async native-UI state. The talk-to-partner UI ops (yes/no menu, party chooser, trade scene) all run
 * a multi-frame field script; drive_ui polls until each finishes and acks. Above GHOST_PAL_BUF (16
 * colours = ends 0x0203FC80), below EWRAM end 0x0203FFFF — in the SLink scratch. `fieldCb` is captured
 * every frame while the player is WALKING (you can't walk in a menu/battle/scene) and is used to (a)
 * gate the ghost driver off during a menu/scene — it writes sprite memory the engine repurposes there —
 * and (b) detect the trade scene's start (cb2 leaves the field) + return (cb2 comes back). */
typedef struct {
    volatile u8  pending;   /* 0 idle; >0 a UI op is in flight */
    volatile u8  kind;      /* 1 = yes/no menu, 2 = party chooser, 3 = native trade scene */
    volatile u16 seq;       /* mailbox seq to ack when the op resolves */
    volatile u16 frames;    /* startup / run timeout counter */
    volatile u8  phase;     /* yesno: 1=waiting-lock 2=running; trade: 0=waiting-start 1=running */
    volatile u8  _pad;
    volatile u32 fieldCb;   /* captured overworld field callback2 (gMain.callback2) */
} UiState;
#define MENU ((UiState *)0x0203FC80u)

/* In-battle notification state. The native FIELD message box (OP_SHOW_MESSAGE) can't open during a
 * battle, so SLink notifications that fire in battle (a linked mon KO'd, a shiny found mid-battle, ...)
 * fell back to the BizHawk Lua HUD overlay. Instead we draw native ROM text in battle via
 * BattlePutTextOnWindow (the same engine primitive the bundled RR4.1 Battle Calc hooks). The battle
 * engine constantly redraws its windows, so a one-shot write would flash and vanish — drive_battle_notif
 * RE-ASSERTS the staged text (SLINK_TEXT_BUF) every frame for `frames`, then stops (the engine's next
 * battle-text write reclaims the window — clean teardown, nothing allocated). Lives in the free EWRAM
 * gap above SLINK_MENU_BUF (ends 0x0203FCFF), below EWRAM end 0x0203FFFF. */
typedef struct {
    volatile u8  active;    /* 0 idle, 1 showing the notification */
    volatile u8  win;       /* target battle window id (low 6 bits) — the Battle Calc's move-info area (0xD) */
    volatile u8  task;      /* engine task id drawing it each frame via RunTasks (0xFF = none) */
    volatile u8  phase;     /* 0 = not yet drawn, 1 = shown (timer only counts down after this) */
    volatile u16 frames;    /* frames left after first shown (counts down to 0 -> stop) */
    volatile u16 _pad2;
} BattleNotif;
#define BN ((BattleNotif *)0x0203FD00u)

/* Event-push ring (native -> Lua). The frame hook OBSERVES battle state natively and pushes events;
 * Lua drains the ring instead of (eventually: in addition to) re-deriving the same facts with
 * per-frame interpreted polling. First producers: player/foe faint-settled (gBattleResults faint
 * counters — they bump only AFTER Sturdy/Focus Sash/Endure resolve, the authoritative "real faint"
 * signal the Lua fast-path already trusts) and the battle-outcome edge (whiteout/loss detection).
 * The producer's prev-state latches live IN the struct: our ROM blob has no .data/.bss, so mutable
 * statics are impossible — all mutable state must be explicit EWRAM. In the free gap after
 * BattleNotif (ends 0x0203FD08); ev[] is 4-aligned at +8. Lua-side API: lua/mailbox.lua MB.events_*. */
typedef struct {
    volatile u8  wr;        /* 0 writer index (native), free-running u8; slot = wr & 7 */
    volatile u8  rd;        /* 1 reader index (Lua); ring empty iff rd == wr */
    volatile u8  overflow;  /* 2 set when a push found the ring full (event dropped); Lua clears */
    volatile u8  inb;       /* 3 producer latch: previous in-battle state */
    volatile u8  pfc;       /* 4 producer latch: previous playerFaintCounter */
    volatile u8  ofc;       /* 5 producer latch: previous foeFaintCounter */
    volatile u8  _pad[2];
    volatile u32 ev[8];     /* 8.. packed events: type | (a << 8) | (b << 16) */
} EvRing;
#define EV ((EvRing *)0x0203FD10u)
#define EV_PLAYER_FAINT 1u  /* a = playerFaintCounter after the bump */
#define EV_FOE_FAINT    2u  /* a = foeFaintCounter after the bump */
#define EV_OUTCOME      3u  /* a = gBattleOutcome on its end-of-battle edge (1 won, 2 lost/whiteout, ...) */

/* Authoritative borrowed-party ("Party Freeze") signal. RR/CFRU temporarily replaces gPlayerParty
 * with a borrowed/preset party for Battle-Tower-style preset battles, Poke Dude tutorials, and
 * partner/mock battles. The engine first BACKS UP the real party to REAL_PARTY_BACKUP via a memcpy
 * loop (BackupParty @ ~0x0804C200), installs the borrowed party, then RESTORES from the backup when
 * the battle ends (RestoreParty @ 0x0804C230). We catch the BEGIN authoritatively by redirecting the
 * backup memcpy's BL (build.py rewrites the 0x0804C10C/0x0804C212 sites -> slink_backup_wrap) and the
 * END per-frame, when gPlayerParty matches the backup again after having diverged. Lua reads this and
 * freezes party-diffing while active=1 — replacing its fragile >=3-PID-change overworld heuristic.
 * Published struct (GhostState-style) in the free EWRAM gap between the mailbox (ends 0x0203F840) and
 * GhostState (0x0203F850); real_pid is 4-aligned at +4. Discovered live via
 * lua/tests/probe_party_backup_writer.lua. */
#define REAL_PARTY_BACKUP 0x02025564u
typedef struct {
    volatile u8  active;    /* 1 while a borrowed party is installed (begin -> restore) */
    volatile u8  seq;       /* ++ on each begin edge; Lua triggers the freeze on the edge */
    volatile u8  diverged;  /* internal: gPlayerParty has differed from the backup since begin */
    volatile u8  _pad;
    volatile u32 real_pid;  /* gPlayerParty[0] PID snapshot at begin (real party; Lua cross-check) */
} SwapState;
#define SW ((SwapState *)0x0203F840u)

#define gMain          0x030030F0u   /* newKeys @ +0x2E (A = 0x0001) */
#define KEY_A          0x0001u
/* gSaveBlock2Ptr 0x0300500Cu + OPT_BATTLE_STYLE_SET 0x0200u removed with OP_SET_RULES */

/* ---- battle-controller plumbing (RR build-specific, runtime-discovered) ---- */
#define gBattlerControllerFuncs 0x03004FE0u   /* u32[4] */
/* action-select controller cycles HandleChooseActionAfterDma3 -> HandleInputChooseAction;
 * MOVE thunk = HandleInputChooseMove slot. Discovered by reading gBattlerControllerFuncs
 * at the live menus (see patch/src/ADDRESSES.md). */
#define ACTION_CTRL_A           0x0802E439u
#define ACTION_CTRL_B           0x0802E3B5u
#define MOVE_CTRL_THUNK         0x0802EA11u

/* ---- engine globals (validated: SLink RR profile <-> BPRE.ld <-> binary) ---- */
#define gBattleMons          0x02023BE4u
#define BATTLE_MON_SIZE      0x58u
#define gBattleOutcome       0x02023E8Au   /* RR: in-battle iff gBattleMons[0].maxHP>0 && outcome==0 */
#define gBattleResults       0x03004F90u   /* IWRAM (RR/CFRU): playerFaintCounter @ +0, foeFaintCounter
                                            * @ +1 — bumped by Cmd_tryfaintmon AFTER protection
                                            * (Sturdy/Sash/Endure) resolves; engine resets on battle
                                            * start. Same address the Lua fast-path polls
                                            * (lua/games/gen3_frlge.lua BATTLE_RESULTS_ADDR). */
#define CB2_OVERWORLD        0x080565B5u   /* RR field main callback (gMain.callback2, thumb bit set).
                                            * Stable while walking AND during field dialogues; ANY menu
                                            * (party/bag/start), battle, or scene sets a different cb2 and
                                            * REUSES gSprites, so the ghost must suspend unless cb2==this. */
#define gChosenActionByBank  0x02023D7Cu
#define gChosenMovesByBanks  0x02023DC4u
#define gBattleCommunication 0x02023E82u
#define gBattleStruct        0x02023FE8u   /* pointer */
#define gBattleExecBuffer    0x02023BC8u   /* gBattleControllerExecFlags */
#define gPlayerParty         0x02024284u
#define gPlayerPartyCount    0x02024029u
#define gEnemyParty          0x0202402Cu
#define gEnemyPartyCount     0x0202402Au
#define MON_SIZE             100u

/* CFRU compressed PC-box storage (OP_DEPOSIT_MON / OP_WITHDRAW_MON). RE'd via the sPokemonBoxPtrs
 * pointer table — see patch/src/ADDRESSES.md "PC storage / box migration reference".
 * sPokemonBoxPtrs[boxId] = EWRAM base of box `boxId`; a slot = base + boxPos * COMPRESSED_MON_SIZE.
 * The conversion fns run the engine's real BoxMonToMon/CalculatePPWithBonus/CalculateMonStats, so a
 * withdrawn mon comes out fully-formed (level/stats/PP) — no server-cached stats needed. */
#define sPokemonBoxPtrs      0x09148930u   /* const u32[25] table of per-box compressed-mon bases */
#define COMPRESSED_MON_SIZE  0x3Au          /* 58-byte CFRU CompressedPokemon */
#define IN_BOX_COUNT         30u
#define TOTAL_BOXES_COUNT    25u
typedef void (*CompressedMonToMon_t)(void *comp, void *dst);            /* box(compressed) -> party Pokemon */
#define CompressedMonToMon ((CompressedMonToMon_t)0x090B6A25u)
typedef void (*CreateCompressedMonFromBoxMon_t)(void *boxMon, void *comp); /* party(BoxPokemon) -> box */
#define CreateCompressedMonFromBoxMon ((CreateCompressedMonFromBoxMon_t)0x090B6B79u)

#define R8(a)   (*(volatile u8 *)(a))
#define R16(a)  (*(volatile u16*)(a))
#define R32(a)  (*(volatile u32*)(a))

/* CFRU's party-backup memcpy: memcpy(dst, src, n) @ 0x081E5E78 (the BL target the backup loop
 * originally called). build.py redirects the two backup-writer BL sites to slink_backup_wrap, which
 * performs the real copy then flags swap-begin ONCE — idempotent, and guarded on dst being the
 * dedicated backup buffer so an unrelated memcpy through this site can never trip it. */
typedef void *(*Memcpy_t)(void *dst, const void *src, u32 n);
#define real_memcpy ((Memcpy_t)0x081E5E79u)
__attribute__((used)) void *slink_backup_wrap(void *dst, const void *src, u32 n)
{
    void *r = real_memcpy(dst, src, n);
    if ((u32)dst == REAL_PARTY_BACKUP && !SW->active) {
        SW->active   = 1;
        SW->diverged = 0;
        SW->real_pid = R32(gPlayerParty);
        SW->seq++;
    }
    return r;
}

/* Per-frame: end the swap once gPlayerParty matches the backup again, after the borrowed party was
 * actually installed (the `diverged` latch). `active=0` therefore tracks "the real party is live"
 * exactly: it clears on a post-battle restore AND on a cancelled/backed-out selector (party put back
 * with no battle). The engine always backs up BEFORE installing a borrowed party, so active=1 is
 * structurally guaranteed whenever the party is borrowed — any 0 window genuinely is the real party.
 * The cancelled-selector edge with no divergence at all falls to Lua's freeze-timeout backstop. */
static void drive_swap_state(void)
{
    if (!SW->active) return;
    u8 match = 1;
    for (u32 i = 0; i < 6; i++) {
        if (R32(gPlayerParty + i * MON_SIZE) != R32(REAL_PARTY_BACKUP + i * MON_SIZE)) {
            match = 0; break;
        }
    }
    if (!match) SW->diverged = 1;
    else if (SW->diverged) SW->active = 0;   /* real party restored (post-battle or backed out) */
}

/* CreateMon(mon, species, level, fixedIV, hasFixedPersonality, fixedPersonality,
 *           otIdType, otId)  @ 0x0803DA54 (Thumb) */
typedef void (*CreateMon_t)(void *mon, u16 species, u8 level, u8 fixedIV,
                            u8 hasFixedPersonality, u32 fixedPersonality,
                            u8 otIdType, u32 otId);
#define CreateMon ((CreateMon_t)0x0803DA55u)

/* int SpawnSpecialObjectEventParameterized(u8 gfxId, u8 movementBehavior, u8 localId,
 *      s16 x, s16 y, u8 elevation)  @ 0x0805E830 — spawns a real overworld NPC
 *      (engine owns its sprite/palette/VRAM/callback). x,y are camera-offset coords. */
typedef int (*SpawnNpc_t)(u8 gfxId, u8 movement, u8 localId, s16 x, s16 y, u8 elevation);
#define SpawnSpecialObjectEventParameterized ((SpawnNpc_t)0x0805E831u)
typedef void (*DestroySprite_t)(void *sprite);
#define DestroySprite ((DestroySprite_t)0x08007281u)
/* bool8 ShowFieldMessage(const u8 *str) @0x0806943C — native field message box.
 * Copies str (FR-charmap, 0xFF-terminated) to gStringVar4, starts the printer, and
 * creates a task the overworld's RunTasks drives. Returns FALSE if a box is already up. */
typedef u8 (*ShowMsg_t)(const u8 *str);
#define ShowFieldMessage ((ShowMsg_t)0x0806943Du)
typedef void (*PlayFanfare_t)(u16 songId);
#define PlayFanfare ((PlayFanfare_t)0x08071C61u)
/* void PlaySE(u16 songId) @0x080722CC (BPRE.ld) — the m4a SE player. The server's play_sound IDs
 * (SE_SUCCESS 25 / SE_FAILURE 26 / SE_FAINT 16 / SE_SHINY 95 / SE_BOO 22) are sound EFFECTS, played
 * here natively instead of via the fragile Lua m4a SE1 RAM-poke (M.playSE / SE_SONG_HEADERS). */
typedef void (*PlaySE_t)(u16 songId);
#define PlaySE ((PlaySE_t)0x080722CDu)
/* gSpecialVar_Result (VAR_RESULT / Var800D) — yesnobox/multichoice write the chosen index here.
 * CFRU event_data.h gives 0x020370D0; corroborated by the live RR profile's gSpecialVar_MonBoxId
 * @0x020370D6 sitting just past it. (OP_SHOW_MENU live test re-confirms: YES -> 1, NO/B -> 0.) */
#define gSpecialVar_Result 0x020370D0u
/* gSpecialVar_0x8004 @ 0x020370C0 (party-chooser result slot), 0x8005 @ 0x020370C2 (trade player slot)
 * — CFRU event_data.h. We invoke the native PARTY MENU + IN-GAME TRADE SCENE by their FireRed `special`
 * indices via a field script (`special <idx>`), the same ScriptContext1_SetupScript path the msgbox uses.
 * DoInGameTradeScene trades gPlayerParty[Var8005] <-> gEnemyParty[0] (TradeMons) and runs trade-evolution
 * on the received mon — it does NOT read the ROM trade table (only CreateInGameTradePokemon does), so we
 * stage gEnemyParty[0] ourselves (OP_SET_ENEMY_PARTY). Indices are FireRed's; validated live on RR. */
#define gSpecialVar_0x8004   0x020370C0u
/* The FireRed `special` INDICES are WRONG on RR — CFRU/RR reordered gSpecials (the live spike proved
 * `special 170` was a no-op: the party menu never opened). So we invoke the native menus by ADDRESS via
 * CFRU's `callnative` (callasm, script-cmd 0x23 + a 4-byte fn ptr). The party-menu internals ARE
 * symbol-mapped in BPRE.ld; a tiny trampoline replicates ChoosePartyMon's InitPartyMenu call. */
typedef void (*InitPartyMenu_t)(u8 menuType, u8 layout, u8 action, u8 keepCursor, u8 msgId,
                                void *task, void *callback);
#define InitPartyMenu          ((InitPartyMenu_t)0x0811EA45u)
#define TASK_HANDLE_CHOOSE_MON 0x0811FB29u   /* Task_HandleChooseMonInput (sets Var8004) */
#define CB2_RETURN_TO_FIELD    0x080567DDu   /* CB2_ReturnToField (menu exit -> resume the field script) */
/* DoInGameTradeScene (RR) — RE'd via patch/tools/find_trade_scene.py (the FR `special` index is
 * reordered on RR, so we call it by ADDRESS via callnative). It's the tiny fn
 *   LockPlayerFieldControls(); CreateTask(Task_InGameTrade,10);
 *   BeginNormalPaletteFade(PALETTES_ALL,0,0,16,RGB_BLACK); HelpSystem_Disable(0x812B478);
 * whose task installs CB2 0x080505CC — which references gSelectedTradeMonPositions + Var8005 +
 * gEnemyParty, i.e. the in-game NPC trade. Trades gPlayerParty[Var8005] <-> gEnemyParty[0] and runs
 * trade-evolution on the received mon. (A near-identical twin @0x08046FD4 installs a Var8004 scene —
 * NOT the trade; do not use it.) */
#define DO_INGAME_TRADE      0x08054440u
/* ---- custom multichoice (a PROPER list menu: TRADE / WAVE / ...) ----
 * RR's gMultichoiceLists is ROM-index-bound, so we replicate DrawVerticalMultichoiceMenu in C with our
 * OWN option list (Lua stages FR-encoded strings in SLINK_MENU_BUF: [u8 count][str 0xFF-term]...). All
 * primitives are BPRE.ld-mapped; the engine's Task_MultichoiceMenu_HandleInput drives input, writes the
 * chosen index to gSpecialVar_Result, closes the window, and ScriptContext_Enable()s (resumes waitstate).
 * A benign mcId (0) in the task skips MultiChoicePrintHelpDescription's cable-club-only help. */
#define FONT_NORMAL 2u
#define gTasks 0x03005090u                  /* struct Task[]; stride 0x28, s16 data[16] @ +8 */
#define TASK_MULTICHOICE_INPUT 0x0809CC98u   /* Task_MultichoiceMenu_HandleInput */
typedef u16  (*GetStringWidth_t)(u8 font, const u8 *str, s16 letterSpacing);
#define GetStringWidth               ((GetStringWidth_t)0x08005ED5u)
typedef u8   (*CreateWindowFromRect_t)(u8 left, u8 top, u8 width, u8 height);
#define CreateWindowFromRect         ((CreateWindowFromRect_t)0x0809D655u)
typedef void (*SetStdBorder_t)(u8 win, u8 copyToVram);
#define SetStandardWindowBorderStyle ((SetStdBorder_t)0x080F7751u)
typedef void (*AddTextPrinter_t)(u8 win, u8 font, const u8 *str, u8 x, u8 y, u8 speed, void *cb);
#define AddTextPrinterParameterized  ((AddTextPrinter_t)0x08002C49u)
typedef void (*CopyWinVram_t)(u8 win, u8 mode);
#define CopyWindowToVram             ((CopyWinVram_t)0x08003F21u)
typedef void (*MenuInitCursor_t)(u8 win, u8 font, u8 left, u8 top, u8 lineH, u8 count, u8 init);
#define Menu_InitCursor              ((MenuInitCursor_t)0x0810F7D9u)
typedef u8   (*CreateTask_t)(void *func, u8 priority);
#define CreateTask                   ((CreateTask_t)0x0807741Du)
typedef void (*DestroyTask_t)(u8 taskId);
#define DestroyTask                  ((DestroyTask_t)0x08077509u)   /* BPRE.ld 0x8077508 (Thumb) */
typedef void (*SchedBg_t)(u8 bgId);
#define ScheduleBgCopyTilemapToVram  ((SchedBg_t)0x080F67A5u)
#define SLINK_MENU_BUF 0x0203FC90u           /* [u8 count][FR str 0xFF-term]... staged for OP_SHOW_CHOICES */
/* void BattlePutTextOnWindow(const u8 *frText, u8 windowId) @0x080D87BE — the engine's IN-BATTLE text
 * draw (the bundled RR4.1 Battle Calc detours its prologue to inject damage numbers). General primitive:
 * the engine uses it for the bottom message window AND the move-select window. windowId low 6 bits =
 * window; bit7 (0x80) = don't clear the window's tile background first. We call it each frame from
 * drive_battle_notif to keep a SLink notification visible during battle. */
typedef void (*BattlePutText_t)(const u8 *frText, u8 windowId);
/* REAL callable entry = the function prologue `push {r4-r7,lr}` @ 0x080D87BC (Thumb 0x080D87BD). NOT
 * 0x080D87BE — that's the calc's detour (2nd instruction), so entering there skips the prologue. We call
 * this REENTRANTLY from our own hook (slink_battle_inject) to draw the notification window in-context. */
#define BattlePutTextOnWindow ((BattlePutText_t)0x080D87BDu)
/* void ScriptContext1_SetupScript(const u8 *ptr) @0x08069AE4 — queues a field script the
 * overworld runs NATIVELY: lockall -> message -> waitmessage -> waitbuttonpress -> releaseall.
 * Unlike a bare ShowFieldMessage (draws a box nothing ever closes), this is a real, navigable,
 * A-to-dismiss conversation. We hand it a tiny EWRAM script that points at our text buffer. */
typedef void (*SetupScript_t)(const u8 *ptr);
#define ScriptContext1_SetupScript ((SetupScript_t)0x08069AE5u)
#define sScriptContext2Enabled 0x03000F9Cu   /* u8 != 0 while a field script/dialogue is active */
#define SLINK_TEXT_BUF   0x0203F900u   /* Lua writes FR-encoded text here before SHOW_MESSAGE */
#define SLINK_SCRIPT_BUF 0x0203F8E0u   /* EWRAM scratch for our field-script bytecode (largest user:
                                          run_choices with_text = 18 B; 0x20 free to SLINK_TEXT_BUF) */
#define SLINK_BLOB_BUF   0x0203FA00u   /* 600 bytes (6x100): Lua stages the partner's raw party-mon
                                          blobs here before OP_SET_ENEMY_PARTY (Rival Team Swap).
                                          Above SLINK_TEXT_BUF (short field text) and below EWRAM
                                          end 0x0203FFFF (leaves >=0x100 for text, ends 0x0203FC58). */
#define gObjectEvents 0x02036E38u   /* stride 0x24 */
#define OE_STRIDE     0x24u
#define OE_SPRITE_ID  0x04u         /* u8 spriteId inside an object-event */
#define gSprites      0x0202063Cu   /* stride 0x44 */
#define SPR_STRIDE    0x44u
#define SPR_COUNT     64u           /* gSprites slots; any spriteId >= 64 is garbage, never index with it */
#define SPR_ANIMS     0x08u         /* const union AnimCmd **anims */
#define SPR_IMAGES    0x0Cu         /* const struct SpriteFrameImage *images */
#define gPlayerAvatar 0x02037078u   /* CFRU; objectEventId @ +0x05 (the player's gObjectEvents slot) */
/* OBJ palette EWRAM shadow buffers (the engine DMAs Faded -> OBJ palette RAM 0x05000200 each frame).
 * Slot 0 base; per-slot = base + slot*0x20. Cross-validated vs the clone's radical_red profile. */
#define gPlttBufferUnfaded_OBJ 0x020373F8u
#define gPlttBufferFaded_OBJ   0x020377F8u
#define gSpriteCoordOffsetX    0x02021BC8u   /* s16; screen = sprite.pos1 + coordOffset */
#define gSpriteCoordOffsetY    0x02021BCAu

/* The player is NOT always object-event slot 0 — its slot is gPlayerAvatar.objectEventId. Reading
 * slot 0 blindly broke spawning when the player lived elsewhere (the spawn grabbed the free slot 0). */
static u32 player_oe(void)
{
    u8 id = R8(gPlayerAvatar + 0x05);
    if (id >= 16) id = 0;
    return gObjectEvents + (u32)id * OE_STRIDE;
}

/* True only on the walkable field (gMain.callback2 == CB2_Overworld). Menu / bag / party / battle /
 * trade-scene CB2s repurpose gSprites + the window system, so launching a field script (yes/no box,
 * multichoice, party picker, trade scene) there overwrites their tiles -> visual corruption / freeze.
 * sScriptContext2Enabled alone is NOT a sufficient gate: it's 0 inside those menu CB2s too. */
static u8 on_field(void) { return R32(gMain + 0x04) == CB2_OVERWORLD; }

/* ---- engine object-event movement API (CFRU follower model; see ADDRESSES.md). The "EventObject"
 * names are CFRU's; identical to pokefirered "ObjectEvent". All take a struct EventObject *. ---- */
typedef u8   (*OeSetMove_t)(void *oe, u8 movementActionId);   /* returns bool8 */
typedef u8   (*OeStatus_t)(void *oe);                         /* 0=finished 16=not-active else=busy */
typedef void (*OeVoid_t)(void *oe);
typedef u8   (*DirAction_t)(u32 dir);                         /* dir (1-4) -> movement-action id */
typedef void (*OeMoveCoords_t)(void *oe, s16 x, s16 y);
typedef void (*OeTurn_t)(void *oe, u8 dir);
#define EventObjectSetHeldMovement             ((OeSetMove_t)  0x8063CA5u)
#define EventObjectClearHeldMovementIfFinished ((OeStatus_t)   0x8063D7Du)
#define EventObjectClearHeldMovementIfActive   ((OeVoid_t)     0x8063D1Du)
#define GetFaceDirectionMovementAction         ((DirAction_t)  0x8063EB9u)
#define GetWalkNormalMovementAction            ((DirAction_t)  0x8063F2Du)
#define GetWalkFastMovementAction              ((DirAction_t)  0x8063FB1u)
#define RemoveEventObject                      ((OeVoid_t)     0x805E4B5u)  /* sprite + OE clean remove */
#define MoveEventObjectToMapCoords             ((OeMoveCoords_t)0x805F725u) /* hard re-place (snap) */
#define EventObjectTurn                        ((OeTurn_t)     0x805F219u)
#define DIR_SOUTH 1u
#define DIR_NORTH 2u
#define DIR_WEST  3u
#define DIR_EAST  4u
#define GHOST_SNAP_TILES 10  /* >this many tiles off -> snap instead of walking there */

static void ghost_remove(void);   /* defined below; drive_ui tears the ghost down when the trade scene starts */

static void ack(u16 st, u16 reason)
{
    MB->reason  = reason;
    MB->status  = st;
    MB->ack_seq = MB->seq;
    MB->opcode  = 0;        /* consumed */
}

/* Runs in place of the menu controller (we swapped gBattlerControllerFuncs[b] to here),
 * so it's the authoritative writer at the right point in the frame. It sets the
 * chosen-move state the action+move menus would have produced and jumps straight to
 * STATE_WAIT_ACTION_CONFIRMED_STANDBY (4) — the engine then executes the forced move.
 * The two-stage menu emit was abandoned: the buffer-transfer round-trip never completed
 * under repeated calls, and CFRU's move buffer carries a Z-move byte (a stale value made
 * Scratch fire as "Breakneck Blitz"). Jumping to CONFIRMED sidesteps both. */
static void slink_force_controller(void)
{
    if (!AM->armed) return;       /* fire once; later calls (same turn) are no-ops */
    u8 b = AM->battler;
    u16 move = R16(gBattleMons + (u32)b * BATTLE_MON_SIZE + 0x0C + (u32)AM->move_pos * 2);
    R8 (gChosenActionByBank  + b)     = 0;            /* USE_MOVE */
    R16(gChosenMovesByBanks  + b * 2) = move;
    u32 bs = R32(gBattleStruct);
    if (bs) { R8(bs + 0x80 + b) = AM->move_pos; R8(bs + 0x0C + b) = AM->target; }
    R8(gBattleCommunication + b) = 4;                /* CONFIRMED_STANDBY */
    u32 mask = (1u << b) | (1u << (b + 4)) | (1u << (b + 8)) | (1u << (b + 12)) | 0xF0000000u;
    R32(gBattleExecBuffer) &= ~mask;
    AM->armed = 0;
    MB->status = ST_OK; MB->reason = 0; MB->ack_seq = AM->seq; MB->opcode = 0;
}

/* Every frame while armed: when the player's action/move menu is up, swap its
 * controller pointer to ours so the engine drives our forced choice natively. */
static void drive_force_move(void)
{
    if (!AM->armed) return;
    u32 b = AM->battler;
    volatile u32 *cf = (volatile u32 *)(gBattlerControllerFuncs + b * 4);
    u8 comm = R8(gBattleCommunication + b);
    if ((comm == 2 && (*cf == ACTION_CTRL_A || *cf == ACTION_CTRL_B)) ||
        (comm == 3 && *cf == MOVE_CTRL_THUNK)) {
        *cf = ((u32)&slink_force_controller) | 1u;   /* Thumb */
    }
    if (++AM->frames > 600) {
        AM->armed = 0;
        MB->status = ST_FAIL; MB->reason = 10; MB->ack_seq = AM->seq; MB->opcode = 0;
    }
}


/* callnative target: build a vertical multichoice window from the options Lua staged in SLINK_MENU_BUF
 * ([u8 count][FR str 0xFF-term]...), mirroring DrawVerticalMultichoiceMenu, then hand input to the
 * engine's Task_MultichoiceMenu_HandleInput (it sets gSpecialVar_Result = chosen index / SCR_MENU_CANCEL,
 * closes the window, and resumes the script). */
static const u8 sMcHeight[9] = { 1, 2, 4, 6, 7, 9, 11, 13, 14 };
static void show_choices_entry(void)
{
    volatile u8 *buf = (volatile u8 *)SLINK_MENU_BUF;
    u8 count = buf[0];
    if (count == 0 || count > 8) return;   /* >8 = malformed/uninitialized stage -> reject, don't clamp */
    const u8 *opts[8];
    const u8 *p   = (const u8 *)(SLINK_MENU_BUF + 1);
    const u8 *end = (const u8 *)0x02040000u;   /* EWRAM end — never scan past it (malformed stage guard) */
    for (u8 i = 0; i < count; i++) {
        opts[i] = p;
        while (p < end && *p != 0xFF) p++;
        if (p >= end) return;                  /* unterminated option -> abort the menu, don't run off EWRAM */
        p++;
    }
    s32 sw = 0;
    for (u8 i = 0; i < count; i++) { s32 t = GetStringWidth(FONT_NORMAL, opts[i], 0); if (t > sw) sw = t; }
    u8 width = (u8)((sw + 9) / 8 + 1);
    u8 left = 1; if (left + width > 28) left = (u8)(28 - width);
    u8 win = CreateWindowFromRect(left, 1, width, sMcHeight[count]);
    SetStandardWindowBorderStyle(win, 0);
    for (u8 i = 0; i < count; i++)
        AddTextPrinterParameterized(win, FONT_NORMAL, opts[i], 8, (u8)(14 * i + 2), 0xFF, 0);
    CopyWindowToVram(win, 2 /*COPYWIN_GFX*/);
    Menu_InitCursor(win, FONT_NORMAL, 0, 2, 14, count, 0);
    u8 tid = CreateTask((void *)(TASK_MULTICHOICE_INPUT | 1u), 80);
    volatile s16 *d = (volatile s16 *)(gTasks + (u32)tid * 0x28u + 8u);
    d[4] = 0;                     /* tIgnoreBPress (0 = B cancels) */
    d[5] = (count > 3) ? 1 : 0;   /* tWrapAround */
    d[6] = win;                   /* tWindowId */
    d[7] = 0;                     /* tMultichoiceId: benign id (no help description) */
    ScheduleBgCopyTilemapToVram(0);
}

/* Field script: lockall ; [msgbox] ; callnative show_choices_entry ; waitstate ; [closemessage] ;
 * releaseall ; end. Brackets like the yes/no menu (lockall sets sScriptContext2Enabled), so drive_ui
 * kind 1 publishes the result (gSpecialVar_Result = chosen option index, or SCR_MENU_CANCEL 0x7F on
 * B). `with_text` shows the FR text Lua staged in SLINK_TEXT_BUF via callstd MSGBOX_DEFAULT (4 =
 * message + waitmessage, box STAYS OPEN under the floating multichoice — the vending-machine /
 * elevator pattern), closed after the pick. The talk-NPC speaks this way ("OAK: ..." + Trade/Say hey).
 * Max script = 18 B; SLINK_SCRIPT_BUF has 0x20 before SLINK_TEXT_BUF (0x0203F900). Caller guards on
 * sScriptContext2Enabled. */
static void run_choices(u8 with_text)
{
    volatile u8 *s = (volatile u8 *)SLINK_SCRIPT_BUF;
    u32 fn = ((u32)&show_choices_entry) | 1u;
    u32 i = 0;
    s[i++] = 0x69;                                               /* lockall */
    if (with_text) {
        s[i++] = 0x0F; s[i++] = 0x00;                            /* loadword dest 0, <text ptr> */
        s[i++] = (u8)(SLINK_TEXT_BUF);       s[i++] = (u8)(SLINK_TEXT_BUF >> 8);
        s[i++] = (u8)(SLINK_TEXT_BUF >> 16); s[i++] = (u8)(SLINK_TEXT_BUF >> 24);
        s[i++] = 0x09; s[i++] = 0x04;                            /* callstd MSGBOX_DEFAULT (stays open) */
    }
    s[i++] = 0x23;                                               /* callnative */
    s[i++] = (u8)fn; s[i++] = (u8)(fn >> 8); s[i++] = (u8)(fn >> 16); s[i++] = (u8)(fn >> 24);
    s[i++] = 0x27;                                               /* waitstate */
    if (with_text) s[i++] = 0x68;                                /* closemessage (drop the speech box) */
    s[i++] = 0x6B;                                               /* releaseall */
    s[i++] = 0x02;                                               /* end */
    ScriptContext1_SetupScript((const u8 *)SLINK_SCRIPT_BUF);
}

/* Show the FR-encoded text already in SLINK_TEXT_BUF as a NATIVE, A-dismissable dialogue. Builds
 * a 9-byte field script "loadword 0, SLINK_TEXT_BUF ; callstd MSGBOX_SIGN(3) ; end" and runs it via
 * ScriptContext1_SetupScript (the std sign msgbox = lockall/message/waitmessage/waitbuttonpress/
 * releaseall). A bare ShowFieldMessage draws a box that never closes; this one the player closes
 * with A. Caller must guard on sScriptContext2Enabled (don't fire while a script/box is already up). */
static void run_sign_msgbox(void)
{
    volatile u8 *s = (volatile u8 *)SLINK_SCRIPT_BUF;
    s[0] = 0x0F; s[1] = 0x00;                         /* loadword dest 0, <text ptr> */
    s[2] = (u8)(SLINK_TEXT_BUF);        s[3] = (u8)(SLINK_TEXT_BUF >> 8);
    s[4] = (u8)(SLINK_TEXT_BUF >> 16);  s[5] = (u8)(SLINK_TEXT_BUF >> 24);
    s[6] = 0x09; s[7] = 0x03;                         /* callstd MSGBOX_SIGN */
    s[8] = 0x02;                                      /* end */
    ScriptContext1_SetupScript((const u8 *)SLINK_SCRIPT_BUF);
}

/* Like run_sign_msgbox but a YES/NO CHOICE — the menuing foundation for talk-to-partner actions.
 * Builds "lockall ; loadword 0,SLINK_TEXT_BUF ; callstd MSGBOX_YESNO(5) ; releaseall ; end" and runs
 * it via ScriptContext1_SetupScript. Std_MsgboxYesNo = message/waitmessage/yesnobox (it does NOT lock
 * on its own, so we wrap lockall/releaseall). The choice lands in gSpecialVar_Result (1=YES, 0=NO/B);
 * drive_menu() publishes it back to Lua. Script-cmd bytes: lockall 0x69, loadword 0x0F, callstd 0x09,
 * releaseall 0x6B, end 0x02 (pokefirered data/script_cmd_table.inc). Shares SLINK_SCRIPT_BUF with
 * run_sign_msgbox (only one dialogue is ever up). Caller guards on sScriptContext2Enabled. */
static void run_yesno_msgbox(void)
{
    volatile u8 *s = (volatile u8 *)SLINK_SCRIPT_BUF;
    s[0]  = 0x69;                                     /* lockall */
    s[1]  = 0x0F; s[2] = 0x00;                        /* loadword dest 0, <text ptr> */
    s[3]  = (u8)(SLINK_TEXT_BUF);        s[4] = (u8)(SLINK_TEXT_BUF >> 8);
    s[5]  = (u8)(SLINK_TEXT_BUF >> 16);  s[6] = (u8)(SLINK_TEXT_BUF >> 24);
    s[7]  = 0x09; s[8] = 0x05;                        /* callstd MSGBOX_YESNO */
    s[9]  = 0x6B;                                     /* releaseall */
    s[10] = 0x02;                                     /* end */
    ScriptContext1_SetupScript((const u8 *)SLINK_SCRIPT_BUF);
}

/* callnative target: open the native "Choose a POKeMON" menu by replicating ChoosePartyMon's
 * InitPartyMenu call (CHOOSE_SINGLE_MON / CHOOSE_AND_CLOSE). The chosen slot lands in Var8004 (0-5),
 * or SLOT_CANCEL (7) on B; Task_HandleChooseMonInput writes it and exits via CB2_ReturnToField, which
 * resumes our field script's waitstate. */
__attribute__((used))
static void slink_open_party_menu(void)
{
    InitPartyMenu(3, 0, 11, 0, 0, (void *)TASK_HANDLE_CHOOSE_MON, (void *)CB2_RETURN_TO_FIELD);
}

/* Field script: `callnative slink_open_party_menu ; waitstate ; end` (callasm = 0x23 + fn ptr). The FR
 * `special` index path is dead on RR (see the defines above), so we call InitPartyMenu by address. */
static void run_party_chooser(void)
{
    volatile u8 *s = (volatile u8 *)SLINK_SCRIPT_BUF;
    u32 fn = ((u32)&slink_open_party_menu) | 1u;                 /* Thumb */
    s[0] = 0x23;                                                 /* callnative */
    s[1] = (u8)fn; s[2] = (u8)(fn >> 8); s[3] = (u8)(fn >> 16); s[4] = (u8)(fn >> 24);
    s[5] = 0x27;                                                 /* waitstate */
    s[6] = 0x02;                                                 /* end */
    ScriptContext1_SetupScript((const u8 *)SLINK_SCRIPT_BUF);
}

/* Run the native in-game TRADE scene on gPlayerParty[slot] against the mon we pre-staged in
 * gEnemyParty[0] (animation + trade-evolution, the real thing). Field script:
 * `setvar 0x8005, slot ; callnative DoInGameTradeScene ; waitstate ; end` (callasm = 0x23 + fn ptr;
 * the scene's CB2 sets gSelectedTradeMonPositions[player] from Var8005 and trades against gEnemyParty[0]). */
static void run_trade_scene(u8 slot)
{
    volatile u8 *s = (volatile u8 *)SLINK_SCRIPT_BUF;
    u32 fn = DO_INGAME_TRADE | 1u;                                     /* Thumb */
    s[0] = 0x16; s[1] = 0x05; s[2] = 0x80; s[3] = slot; s[4] = 0x00;   /* setvar VAR_0x8005, slot */
    s[5] = 0x23;                                                       /* callnative DoInGameTradeScene */
    s[6] = (u8)fn; s[7] = (u8)(fn >> 8); s[8] = (u8)(fn >> 16); s[9] = (u8)(fn >> 24);
    s[10] = 0x27;                                                      /* waitstate */
    s[11] = 0x02;                                                      /* end */
    ScriptContext1_SetupScript((const u8 *)SLINK_SCRIPT_BUF);
}

static void ui_done(u16 st, u8 result0)
{
    MENU->pending = 0;
    MB->result[0] = result0;
    MB->status = st; MB->reason = (st == ST_OK) ? 0 : 12;
    MB->ack_seq = MENU->seq; MB->opcode = 0;
}

/* Poll whichever async native-UI op OP_SHOW_MENU / OP_CHOOSE_PARTY_MON / OP_TRADE_SCENE set up, and
 * ack when it resolves. Each kind has its own start/done signal (the field script starts a frame or
 * two after SetupScript). All time out so a lost UI can't wedge the mailbox. */
static void drive_ui(void)
{
    if (!MENU->pending) return;

    if (MENU->kind == 1) {                         /* yes/no menu: lockall sets sScriptContext2Enabled */
        u8 active = R8(sScriptContext2Enabled);
        if (MENU->phase == 1) {                    /* waiting for the script to lock the field */
            if (active) { MENU->phase = 2; MENU->frames = 0; }
            else if (++MENU->frames > 60) ui_done(ST_FAIL, 0);
            return;
        }
        if (active) { if (++MENU->frames > 1800) ui_done(ST_FAIL, 0); return; }
        ui_done(ST_OK, (u8)R16(gSpecialVar_Result));   /* 1=YES 0=NO/B */
        return;
    }

    if (MENU->kind == 2) {                         /* party chooser: Var8004 sentinel 0xFF -> 0-7 */
        u16 v = R16(gSpecialVar_0x8004);
        if (v <= 7) ui_done(ST_OK, (u8)v);         /* 0-5 chosen, 7 = cancel */
        else if (++MENU->frames > 1800) ui_done(ST_FAIL, 0);
        return;
    }

    /* kind == 3: native trade scene — the CB2 leaves the field, runs, then returns. */
    {
        u32 cb = R32(gMain + 0x04);
        if (MENU->phase == 0) {                    /* waiting for the scene to take over the screen */
            if (MENU->fieldCb && cb != MENU->fieldCb) { MENU->phase = 1; MENU->frames = 0; }
            else if (++MENU->frames > 180) ui_done(ST_FAIL, 0);   /* never started */
            return;
        }
        /* The in-game-trade text reads the RECEIVED-mon name + OT from sInGameTrades[Var8004] (our stale
         * chooser slot -> a default like "Rukia"). Override gStringVar3 (received nickname) + gStringVar1
         * (OT) from the mon we actually staged in gEnemyParty[0], each frame, so "X sent over Y" names the
         * real traded mon. (gStringVar2 = the sent mon is already correct.) Party-mon plaintext (NO_ENCRYPT):
         * nickname @ +0x08 (11 b), otName @ +0x14 (8 b). gStringVar1=0x02021CD0, gStringVar3=0x02021D04. */
        { volatile u8 *nk = (volatile u8 *)(gEnemyParty + 0x08), *ot = (volatile u8 *)(gEnemyParty + 0x14);
          volatile u8 *v3 = (volatile u8 *)0x02021D04u, *v1 = (volatile u8 *)0x02021CD0u;
          for (u32 i = 0; i < 11; i++) v3[i] = nk[i];
          for (u32 i = 0; i < 8;  i++) v1[i] = ot[i]; }
        if (cb == MENU->fieldCb) ui_done(ST_OK, 0);               /* back on the field -> done */
        else if (++MENU->frames > 5400) ui_done(ST_FAIL, 0);      /* ~90 s safety */
    }
}

/* Peer interaction: when the player presses A facing the ghost NPC, bump a counter the Lua client
 * polls. The client then emits trade_request and the SERVER drives the talk-to-partner UI (a native
 * trade menu via OP_SHOW_MENU, or a "waved" message). We deliberately do NOT open a box here: a local
 * box would set sScriptContext2Enabled and make the server's OP_SHOW_MENU bounce (it guards on that),
 * so the menu would never appear. (Earlier this called run_sign_msgbox for a standalone "hello" box;
 * that's superseded by the server-driven menu.) */
static void check_peer_interact(void)
{
    if (!SS->pi_armed) return;
    if (R32(gMain + 4) != CB2_OVERWORLD) return;         /* WALKABLE FIELD only — an A-press to advance
                                                          * battle/menu text must NOT fire the talk
                                                          * (which would run a field script there). */
    if (R8(sScriptContext2Enabled)) return;              /* a dialogue/script is already up */
    if (!(R16(gMain + 0x2E) & KEY_A)) return;            /* A newly pressed this frame? */
    u32 p = player_oe();                                  /* the player's actual object-event */
    if (!(R8(p) & 0x80)) return;                          /* player IDLE (heldMovementFinished) only —
                                                           * so running/bumping into the ghost can't
                                                           * trigger the dialogue + lock input; talk is a
                                                           * deliberate stationary A-press (waving). */
    u32 g = gObjectEvents + (u32)SS->pi_oe * OE_STRIDE;
    if (!(R8(g) & 1)) return;                             /* ghost active? */
    int px = (s16)R16(p + 0x10), py = (s16)R16(p + 0x12);
    u8  f  = R8(p + 0x18) & 0x0F;
    if      (f == 1) py++;       /* down */
    else if (f == 2) py--;       /* up */
    else if (f == 3) px--;       /* left */
    else if (f == 4) px++;       /* right */
    if (px == (s16)R16(g + 0x10) && py == (s16)R16(g + 0x12)) {
        SS->pi_count++;          /* the client polls this -> trade_request -> server drives the menu */
        /* CONSUME the A-press so the ENGINE doesn't ALSO run the ghost OE's interaction. Our ghost has
         * localId 0xF0 with no map object-event template, so the engine's facing-script lookup yields a
         * garbage pointer -> a random "broken NPC" battle / warp (the user's teleport-to-SS-Anne). The
         * hook runs inside CallCallbacks BEFORE the field callback reads JOY_NEW(A), so clearing the A
         * bit here makes the engine see no press this frame. */
        R16(gMain + 0x2E) &= (u16)~KEY_A;
    }
}

/* Remove our ghost cleanly (sprite + object-event) IF the slot is still ours, then disarm interact.
 * Never RemoveEventObject a slot a real NPC now owns (post-warp the slot is reused). */
static void ghost_remove(void)
{
    if (GH->oeId != 0xFF) {
        u32 g = gObjectEvents + (u32)GH->oeId * OE_STRIDE;
        if ((R8(g) & 1) && R8(g + 0x08) == GH->localId) {
            RemoveEventObject((void *)g);   /* frees the sprite (this build's fn = RemoveObjectEvent
                                             * INTERNAL — it does NOT clear the OE active flag) */
            R8(g) = 0;                      /* so explicitly deactivate the object-event; otherwise the
                                             * collision OE LINGERS as an invisible wall after a clear
                                             * (only masked before because map changes reload all OEs) */
        }
        GH->oeId = 0xFF;
    }
    GH->flags = 0;
    SS->pi_armed = 0;
}

/* Inert sprite callback: we neutralize the ghost OE's movement callback so the engine never moves it
 * (we own pos1). AnimateSprite still advances animation frames independently of the callback. */
static void ghost_cb(void *s) { (void)s; }

/* Make the ghost look like the PARTNER (another real player), not the local player. The OE is
 * spawned with the local player's gfx purely as a guaranteed-16x32 stand-in; we then repoint the
 * sprite at the partner's live images/anims ROM ptrs (identical across copies of the same RR build)
 * and move the sprite to a DEDICATED OBJ palette slot (15) painted with the partner's true colours —
 * so it never touches the player's slot 0 (no corruption) and never contends a live NPC slot. images/
 * anims/paletteNum are set on change; the slot-15 colours are re-stamped each frame so the engine's
 * tint/fade pass can't drop them (v1 shows the partner's true colours — day/night tint on the avatar
 * is a documented follow-up). The partner's on-foot frame is 16x32, matching the stand-in's tiles. */
#define GHOST_PAL_SLOT 15u
static void apply_avatar(u32 g)
{
    if (!GH->imgs) return;                         /* no partner avatar received yet */
    /* The imgs/anims ptrs are PEER-SUPPLIED (broadcast by the partner's client). Only ever write
     * ROM pointers into the sprite struct — a corrupt/hostile value would send AnimateSprite reading
     * arbitrary memory. 32 MB ROM window: [0x08000000, 0x0A000000). */
    if (GH->imgs < 0x08000000u || GH->imgs >= 0x0A000000u) return;
    if (GH->anims && (GH->anims < 0x08000000u || GH->anims >= 0x0A000000u)) return;
    u8 sid = R8(g + OE_SPRITE_ID);
    if (sid >= SPR_COUNT) return;
    u32 spr = gSprites + (u32)sid * SPR_STRIDE;
    R32(spr + SPR_IMAGES) = GH->imgs;              /* sprite.images — re-assert every frame */
    if (GH->anims) R32(spr + SPR_ANIMS) = GH->anims;  /* sprite.anims */
    if (GH->avatarDirty) {
        R8(spr + 0x3F) |= 0x04;                    /* animBeginning -> re-DMA frame0 from new imgs */
        GH->avatarDirty = 0;
    }
    /* keep the sprite on our dedicated palette slot every frame (engine sets paletteNum only at
     * SetGraphicsId, but re-assert defensively against reflection/ground-effect repaints). */
    u16 attr2 = R16(spr + 0x04);
    R16(spr + 0x04) = (u16)((attr2 & (u16)~0xF000u) | (GHOST_PAL_SLOT << 12));
    /* Write only the UNFADED (true) colours here. The day/night-tinted FADED slot is owned by the Lua
     * receiver end-of-frame — if the patch also wrote FADED every frame-top it would overwrite the
     * tint before the engine's Faded->RAM DMA, so the ghost would never tint (the bug). */
    u32 uf = gPlttBufferUnfaded_OBJ + GHOST_PAL_SLOT * 0x20;
    for (u32 i = 0; i < 16; i++)
        R16(uf + i * 2) = R16(GHOST_PAL_BUF + i * 2);
}

/* idle/walk animNum from facing (pret ANIM_STD: idle face = f-1 (0..3 S/N/W/E); walk = f+3 (4..7)). */
static u8 idle_anim(u8 f) { return (f >= 1 && f <= 4) ? (u8)(f - 1) : 0; }
static u8 walk_anim(u8 f) { return (f >= 1 && f <= 4) ? (u8)(f + 3) : 4; }

/* Engine-driven peer ghost (proven Lua-clone model, in C): spawn a real OE for the sprite slot /
 * collision / palette, NEUTRALIZE its callback, then each frame drive pos1 (sub-pixel LERP toward
 * the partner's broadcast world-pixel position) + animNum + the partner's avatar. The engine still
 * adds gSpriteCoordOffset (so the ghost scrolls with the map) and runs AnimateSprite (so the walk
 * cycle plays). Speed-agnostic + continuous => no tile-quantized stutter. Owns map/gfx lifecycle. */
static void drive_ghost(void)
{
    /* SUSPEND during battle. The battle engine REUSES gSprites for battle sprites, so touching the
     * ghost's sprite here would corrupt battle graphics / crash (the reported rival-battle crash).
     * RR in-battle test = gBattleMons[0].maxHP>0 && gBattleOutcome==0. Touch NOTHING — just return.
     * A trainer battle does NOT reload the map, so afterward the engine RESTORES our object-event
     * (reloaded from its graphicsId = the default stand-in); the slot-reassign guard (d) then sees it
     * is still ours and RESUMES driving + re-applies the partner avatar (so sync continues without an
     * area transition). A whiteout DOES reload the map -> the slot is reassigned -> (d) respawns. */
    if (R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0) return;

    /* SUSPEND in any non-field context (party menu / bag / start menu / battle intro / trade scene /
     * map-load transitions). Those screens REUSE gSprites for their own UI, so driving the ghost's
     * sprite slot there corrupts them (the "square in the middle of the party menu" + freeze). Only
     * the walkable field (incl. field dialogues) keeps gMain.callback2 == CB2_OVERWORLD; touch nothing
     * otherwise. The ghost OE is preserved across menus, so the lifecycle below RESUMES on return. */
    if (R32(gMain + 4) != CB2_OVERWORLD) return;

    /* A native trade scene is pending or about to take over: tear the ghost down NOW and DON'T respawn
     * until the scene op finishes. This branch runs while the field is still active (between the client
     * dispatching OP_TRADE_SCENE and the scene CB2 actually grabbing the screen), so RemoveEventObject
     * works in a clean field context — unlike removing it mid-scene, which raced DoInGameTradeScene's own
     * object-event snapshot/restore and left an INVISIBLE-COLLISION orphan (+ corrupted later battle
     * sprites) when the scene reset+reloaded with our OE/palette-slot-15 still live. Once drive_ui clears
     * MENU->pending (scene returned to the field), the normal lifecycle below respawns the ghost cleanly. */
    if (MENU->pending && MENU->kind == 3) {
        if (GH->oeId != 0xFF) ghost_remove();
        return;
    }

    /* GARBAGE-COLLECT stray ghost OEs: any ACTIVE object-event carrying our exclusive sentinel
     * localId (0xF0 — real map NPCs use small localIds) that is NOT our live slot is an ORPHAN left
     * by some teardown path that didn't fully clean up (scripts/cutscenes/slot-reassignment/warps).
     * Free its sprite + deactivate it. This catch-all stops "invisible collision" from accumulating
     * after dialogue and other scripted events, regardless of how the orphan was created. */
    for (u32 i = 0; i < 16; i++) {
        if (i == GH->oeId) continue;
        u32 oo = gObjectEvents + i * OE_STRIDE;
        if ((R8(oo) & 1) && R8(oo + 0x08) == 0xF0u) {
            RemoveEventObject((void *)oo);   /* free the sprite */
            R8(oo) = 0;                       /* + deactivate (this build's RemoveEventObject won't) */
        }
    }

    if (!GH->active) { if (GH->oeId != 0xFF) ghost_remove(); return; }

    u32 player = player_oe();                     /* the player's ACTUAL slot (not always 0) */
    u8 pg = R8(player + 0x0A), pn = R8(player + 0x09);

    /* (a) map change -> the warp rebuilt all OE slots; clean-remove ours and re-spawn on the new map. */
    if (GH->oeId != 0xFF && (pg != GH->pmapGroup || pn != GH->pmapNum)) ghost_remove();
    GH->pmapGroup = pg; GH->pmapNum = pn;

    /* (b) gfx change (partner mounted bike / surfed / fished) -> re-spawn with the new sprite. */
    if (GH->oeId != 0xFF && GH->gfxId != GH->curGfx) ghost_remove();

    /* (c) spawn once, adjacent to the player; neutralize the callback so we own pos1. */
    if (GH->oeId == 0xFF) {
        if (R8(sScriptContext2Enabled)) return;  /* not mid-dialogue/warp fade */
        s16 px = (s16)R16(player + 0x10), py = (s16)R16(player + 0x12);
        /* Spawn the stand-in at a MISMATCHED elevation -> PASS-THROUGH, so the spawn tile (one south of
         * the player) never leaves an invisible wall before the ghost starts tracking. The drive loop
         * makes it solid (matching the player's elevation) only once it's on-screen + actually following. */
        u8  pelev = R8(player + 0x0B) & 0x0F;
        u8  elev  = (u8)(pelev == 0x0F ? 0x0E : 0x0F);
        int oe = SpawnSpecialObjectEventParameterized(GH->gfxId, /*MOVEMENT_TYPE_NONE*/0,
                                                      GH->localId, px, (s16)(py + 1), elev);
        if (oe >= 16) return;                    /* no free slot on this map; retry next frame */
        GH->oeId = (u8)oe; GH->curGfx = GH->gfxId;
        u8 sid = R8(gObjectEvents + (u32)oe * OE_STRIDE + 0x04);
        if (sid < 64) {
            u32 spr = gSprites + (u32)sid * SPR_STRIDE;
            R32(spr + 0x1C) = ((u32)&ghost_cb) | 1u;   /* neutralize the movement callback */
            R8(spr + 0x3E) |= 0x02;                    /* coordOffset-enabled (scroll with the map) */
            R8(spr + 0x3E) |= 0x04;                    /* INVISIBLE until a fresh camera baseline is
                                                        * cached + first proper placement — avoids the
                                                        * "glitch at bad coordinates during the screen
                                                        * transition" before C/disp are valid. */
        }
        GH->flags = 0;                           /* recompute C + disp (snap) on first drive */
        GH->snap = 1;
        GH->avatarDirty = 1;                     /* re-stamp the avatar onto the fresh sprite slot */
        SS->pi_oe = (u8)oe; SS->pi_armed = 1;    /* auto-arm talk-to-ghost on the live slot */
        return;
    }

    u32 g = gObjectEvents + (u32)GH->oeId * OE_STRIDE;

    /* (d) slot freed/reassigned under us -> forget, respawn next frame. */
    if (!(R8(g) & 1) || R8(g + 0x08) != GH->localId) { GH->oeId = 0xFF; return; }
    u8 gsid = R8(g + 0x04);
    if (gsid >= 64) { GH->oeId = 0xFF; return; }
    u32 gspr = gSprites + (u32)gsid * SPR_STRIDE;

    /* render the PARTNER's avatar (their sprite ptrs + true colours), not the local player's. */
    apply_avatar(g);

    /* (C baseline) screen = sprite.pos1 + coordOffset; a sprite at world-px W has pos1 = W + C where
     * C = playerSprite.pos1 - playerTile*16. Cache C while the player is tile-aligned (idle) — the
     * mid-step player carries a sub-tile offset that would skew it. */
    u8 psid = R8(player + 0x04);
    if (psid < 64 && (R8(player) & 0x80)) {       /* player heldMovementFinished => tile-aligned */
        u32 pspr = gSprites + (u32)psid * SPR_STRIDE;
        GH->cx = (s16)((s16)R16(pspr + 0x20) - (s16)(R16(player + 0x10) * 16));
        GH->cy = (s16)((s16)R16(pspr + 0x22) - (s16)(R16(player + 0x12) * 16));
        GH->flags |= GH_F_HAVE_C;
    }
    if (!(GH->flags & GH_F_HAVE_C)) return;       /* need a baseline before we can place the ghost */

    /* (disp) follow the partner's broadcast world-px at a CONSTANT velocity that matches the engine's
     * own NPC speeds — exactly 1 px/frame walking, 2 px/frame running — so the ghost moves with the
     * same uniform cadence as an NPC/the player (no ease-out, no sub-pixel rounding jitter). A small
     * constant follow-lag (<= one sample interval) is invisible; large desync snaps. disp = integer px. */
    s16 tx = GH->wx, ty = GH->wy;
    if (GH->snap) {                               /* explicit snap: jump straight to the target */
        GH->dispx = tx; GH->dispy = ty; GH->snap = 0; GH->flags |= GH_F_HAVE_DISP;
        GH->leadpx = 0;
    } else if (!(GH->flags & GH_F_HAVE_DISP)) {   /* first time: start from the ghost's current pos */
        GH->dispx = (s16)R16(gspr + 0x20) - GH->cx;
        GH->dispy = (s16)R16(gspr + 0x22) - GH->cy;
        GH->flags |= GH_F_HAVE_DISP;
        GH->leadpx = 0;
    } else {
        int dx = tx - GH->dispx, dy = ty - GH->dispy;
        int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
        int spd = GH->run ? 2 : 1;                /* uniform px/frame == engine WALK_NORMAL / FAST_1 */
        if (adx > GHOST_SNAP_PX || ady > GHOST_SNAP_PX) {
            GH->dispx = tx; GH->dispy = ty; GH->leadpx = 0;
        } else if (GH->mv && adx == 0 && ady == 0) {
            /* LEAD EXTRAPOLATION: arrived at a STALE target while the partner is still moving
             * (the ~30 Hz sample hasn't refreshed yet) -> keep walking in their facing instead
             * of the old reach-and-pause stutter. Budgeted: at most GHOST_LEAD_CAP_PX past the
             * sample; the next fresh target absorbs the lead. */
            if (GH->leadpx + spd <= GHOST_LEAD_CAP_PX) {
                GH->leadpx = (u8)(GH->leadpx + spd);
                switch (GH->face) {
                    case 1:  GH->dispy += spd; break;   /* S */
                    case 2:  GH->dispy -= spd; break;   /* N */
                    case 3:  GH->dispx -= spd; break;   /* W */
                    default: GH->dispx += spd; break;   /* E */
                }
            }
        } else {
            /* Converging on a live target. While the partner is MOVING, never step BACKWARD
             * along their facing axis: a lead past the previous sample would otherwise walk
             * back toward it and oscillate — let the next fresh target absorb the overshoot.
             * Once the partner stops (mv==0) we converge unrestricted and settle exactly. */
            int stepx = (adx <= spd) ? dx : (dx > 0 ? spd : -spd);
            int stepy = (ady <= spd) ? dy : (dy > 0 ? spd : -spd);
            if (GH->mv) {
                if      (GH->face == 4 && stepx < 0) stepx = 0;   /* E: no westward step */
                else if (GH->face == 3 && stepx > 0) stepx = 0;   /* W: no eastward step */
                else if (GH->face == 1 && stepy < 0) stepy = 0;   /* S: no northward step */
                else if (GH->face == 2 && stepy > 0) stepy = 0;   /* N: no southward step */
            }
            GH->dispx += stepx; GH->dispy += stepy;
            if (GH->dispx == tx && GH->dispy == ty) GH->leadpx = 0;  /* settled -> budget back */
        }
    }
    s16 wpx = (s16)GH->dispx, wpy = (s16)GH->dispy;

    /* place the sprite (map-relative pos1; the engine adds coordOffset) + keep coordOffset enabled. */
    R16(gspr + 0x20) = (u16)(wpx + GH->cx);
    R16(gspr + 0x22) = (u16)(wpy + GH->cy);
    R8(gspr + 0x3E) |= 0x02;

    /* animation: exact partner anim while moving (their live animNum), else idle facing. */
    u8 want = GH->mv ? ((GH->an <= 23) ? GH->an : walk_anim(GH->face)) : idle_anim(GH->face);
    if (R8(gspr + 0x2A) != want) {
        R8(gspr + 0x2A) = want;          /* animNum */
        R8(gspr + 0x3F) |= 0x04;         /* animBeginning */
        R8(gspr + 0x2C) &= (u8)~0x40u;   /* animPaused = 0 (auto-advance frames) */
    }

    /* Collision + visibility. ON-SCREEN: the ghost is SOLID at exactly the tile it's drawn on
     * (matching the player's elevation) so you bump it and can talk to it (menu/interaction) — and
     * the collision is never "invisible" because it sits under the visible sprite. OFF-SCREEN: hide
     * the sprite (its OAM coord would wrap + paint garbage) AND park the collision tile on the player
     * with a MISMATCHED elevation so it is NOT culled (RemoveObjectEventIfOutsideView culls by
     * currentCoords) yet creates NO phantom wall around the player. The instant it's back on-screen
     * it becomes solid at its own tile again. */
    s16 sx = (s16)(wpx + GH->cx + (s16)R16(gSpriteCoordOffsetX));
    s16 sy = (s16)(wpy + GH->cy + (s16)R16(gSpriteCoordOffsetY));
    int onscreen = (sx >= -16 && sx <= 256 && sy >= -16 && sy <= 176);
    u8 pelev = (u8)(R8(player + 0x0B) & 0x0F);
    if (onscreen) {
        R8(gspr + 0x3E) &= (u8)~0x04u;                /* visible */
        s16 gtx = (s16)((wpx + 8) >> 4), gty = (s16)((wpy + 8) >> 4);
        R16(g + 0x10) = (u16)gtx; R16(g + 0x12) = (u16)gty;   /* collision/interact tile = drawn tile */
        R8(g + 0x0B) = (u8)(pelev | (pelev << 4));    /* match player elevation -> SOLID */
    } else {
        u8 ge = (u8)(pelev == 0x0F ? 0x0E : 0x0F);    /* mismatched, nonzero -> pass-through */
        R8(gspr + 0x3E) |= 0x04;                      /* invisible */
        R16(g + 0x10) = R16(player + 0x10); R16(g + 0x12) = R16(player + 0x12);  /* park (avoid cull) */
        R8(g + 0x0B) = (u8)(ge | (ge << 4));          /* no phantom wall while off-screen */
    }
}

/* PER-FRAME in-context notification draw. Runs via the engine's RunTasks (the safe frame point) every
 * battle frame while a notification is active, so our text shows PERSISTENTLY in the target window — even
 * OUTSIDE the FIGHT menu / during a static message (the BattlePutTextOnWindow hook alone only fires when the
 * engine itself redraws something, which is sporadic). Drawing from RunTasks is in-context, so it does NOT
 * white-out the BG the way calling BattlePutTextOnWindow from the slink_hook frame hook does. Self-destructs
 * when the notification ends or the battle does. (The draw re-enters our BattlePutTextOnWindow hook, which
 * swaps in our text for the target window — see slink_battle_inject.) */
static const u8 sEmptyFr[1] = { 0xFF };   /* empty FR string -> BattlePutTextOnWindow blanks the window */
/* The standard in-battle TEXT palette (BG palette slot 6) — what the FC 01 <id> colour codes index:
 * 1=red, 4=gold, 5=green, 0xA=white, ... Captured live at turn resolution (probe_palettes.lua). The
 * engine only loads this palette in SOME battle phases (resolution / FIGHT menu); at the action-select
 * menu and the battle intro slot 6 is ALL ZEROS, so themed text rendered BLACK there (the injected-event
 * E2E caught it). While our notification is showing, slink_notif_task re-stamps these colours into the
 * Faded shadow buffer + palette RAM each frame (the ghost-tint technique), so the theme colours render in
 * EVERY phase. Nothing else renders with slot 6 in the phases where the engine leaves it zeroed. */
static const u16 sBattleTextPal[16] = {
    0x426F, 0x195E, 0x1D54, 0x1B1F, 0x1B9B, 0x2B2F, 0x6F73, 0x7E67,
    0x5114, 0x7ADE, 0x6318, 0x2E97, 0x457F, 0x45EA, 0x18C6, 0x7FFF,
};
#define BG_PAL6_FADED 0x020376B8u   /* gPlttBufferFaded + 6*32 (BG half; engine DMAs Faded->palette RAM) */
#define BG_PAL6_RAM   0x050000C0u   /* BG palette RAM slot 6 (stamp directly too: colour NOW, no 1f lag) */
static void slink_notif_task(u8 taskId)
{
    u8 win = (u8)(BN->win & 0x3F);
    if (!BN->active || !(R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0)) {
        /* CLEAR our text from the window on the way out (our text otherwise LINGERS until the engine next
         * redraws that window — which for the move-info window is only at the FIGHT menu). Only if still in
         * battle (battle teardown frees the windows). Then engine-proper task teardown — poking the struct
         * @+0 corrupts the FUNC ptr and crashes RunTasks. */
        if (R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0)
            BattlePutTextOnWindow(sEmptyFr, win);
        DestroyTask(taskId);
        BN->task = 0xFF;
        return;
    }
    for (u32 i = 0; i < 16; i++) {                 /* keep the text palette loaded in every phase */
        R16(BG_PAL6_FADED + i * 2) = sBattleTextPal[i];
        R16(BG_PAL6_RAM   + i * 2) = sBattleTextPal[i];
    }
    BattlePutTextOnWindow((const u8 *)SLINK_TEXT_BUF, win);
    BN->phase = 1;   /* drawn at least once -> the timer may count down */
}

/* In-battle notification driver (runs from slink_hook). Ensures the per-frame draw task exists and counts
 * the notification down. CreateTask only ALLOCATES a task slot here (no drawing) so it's safe from the frame
 * hook; the slink_notif_task it creates does the actual drawing in-context via RunTasks. */
static void drive_battle_notif(void)
{
    if (!BN->active) return;
    if (!(R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0)) { BN->active = 0; return; }
    if (BN->task >= 16)
        BN->task = CreateTask((void *)((u32)&slink_notif_task | 1u), 1);   /* priority 1 = drawn above most */
    if (BN->phase && (BN->frames == 0 || --BN->frames == 0)) BN->active = 0;
}

/* BattlePutTextOnWindow text-swap (called by the shim, IN-CONTEXT inside the engine's own draw). When a
 * notification is active and the engine (or the Battle Calc) is drawing OUR target window, substitute our
 * text — so the calc can't overwrite our notification at the move menu. Per-frame persistence is handled by
 * slink_notif_task; this just makes the engine's own draws of the target window show our text too. */
__attribute__((used)) const u8 *slink_battle_inject(const u8 *text, u32 windowId)
{
    if (BN->active && (windowId & 0x3F) == (BN->win & 0x3F)) return (const u8 *)SLINK_TEXT_BUF;
    return text;
}

/* IN-CONTEXT hook for the engine's BattlePutTextOnWindow (the safe way to draw native in-battle text).
 * The bundled Battle Calc detours that function's 2nd instruction (0x080D87BE) with `BL 0x08378CA8` (its
 * trampoline). build.py RE-POINTS that detour to THIS shim, so we run FIRST but still inside the engine's
 * own draw call — the correct frame context. On entry r0 = text ptr, r1 = windowId, lr = 0x080D87C2 (the
 * BL's return into the function body). We call slink_battle_inject(r0,r1) -> the text to draw (and it does
 * the reentrant notification draw), then branch into the calc trampoline (lr preserved → it returns into
 * the body as the original BL would). Naked: preserve r1 (windowId) + lr across the C call. */
__attribute__((naked, used)) void slink_battletext_hook(void)
{
    __asm__ volatile(
        ".syntax unified           \n"
        ".thumb                    \n"
        "push {r1, lr}             \n"   /* preserve windowId + the BL return (0x080D87C2) across the C call */
        "bl   slink_battle_inject  \n"   /* r0 = inject(r0=text, r1=windowId) = text to draw */
        "pop  {r1}                 \n"   /* restore windowId */
        "pop  {r3}                 \n"   /* r3 = saved lr (Thumb-1 POP can't target lr directly) */
        "mov  lr, r3               \n"   /* lr = 0x080D87C2 (so the trampoline returns into the body) */
        "ldr  r2, =0x0203F8D8      \n"   /* SLINK_CALC_OFF: 1 = hide the Battle Calc display */
        "ldrb r2, [r2]             \n"
        "cmp  r2, #0               \n"
        "bne  1f                   \n"
        "ldr  r2, =0x08378CA9      \n"   /* calc ON: fall through to the calc trampoline (Thumb); it
                                          * replays the displaced insns and returns into the body */
        "bx   r2                   \n"
        "1:                        \n"   /* calc OFF: replay the two halfwords the calc's BL displaced
                                          * (clean RR @0x080D87BE: mov r7,r8 ; push {r7}) and continue
                                          * the function body directly — as if the calc weren't there */
        "mov  r7, r8               \n"
        "push {r7}                 \n"
        "ldr  r2, =0x080D87C3      \n"   /* body resume (Thumb) */
        "bx   r2                   \n"
        ".ltorg                    \n"
    );
}

/* ---- Pokémon-Center trade NPC driver (presence-OFF mode) -------------------------------------- */
/* Tunables — CONFIRM IN-GAME on RR (see lua/tests/test_live_pcnpc.lua). graphicsId must be a neutral
 * NPC (NOT 0 = the player base). Tile is gObjectEvents currentCoords space (absolute map tile + 7);
 * the FRLG PC 1F interior is a single shared layout, so one tile serves every center. */
#define PCNPC_GFX     0x47u   /* 71 = Prof Oak — user-picked via lua/tests/sprite_gallery.lua */
#define PCNPC_MOVEMENT 0x02u  /* MOVEMENT_TYPE_WANDER_AROUND: engine-driven idle pacing (steps +
                               * facing changes). Range is clamped to +-1 tile post-spawn below. */
#define PCNPC_TILE_X  0x0Au   /* TBD: currentCoords X; verify reachable + clear of the counter/PC */
#define PCNPC_TILE_Y  0x09u   /* TBD: currentCoords Y */

/* Pokémon-Center 1F map IDs as (mapGroup<<8 | mapNum), from
 * data/games/gen3_frlge/gen3_frlge_locations.lua. These are the project's FRLG resolver values; RR is
 * FRLG-based and preserves them in practice, but VERIFY live (a PC may be renumbered/absent on RR).
 * Read-only .rodata is fine in our ROM section (only mutable statics would be a problem). */
static const u16 kPokecenter1F[] = {
    0x0504, 0x0605, 0x0703, 0x0800, 0x0901, 0x0A0C, 0x0B05, 0x0C05, 0x0D00, 0x0E06,
    0x1000, 0x1500, 0x1F03, 0x2000, 0x2102, 0x2201, 0x2301, 0x2400, 0x2500,
};
static u8 is_pokecenter(u8 g, u8 n)
{
    u16 key = (u16)(((u16)g << 8) | n);
    for (u32 i = 0; i < sizeof(kPokecenter1F) / sizeof(kPokecenter1F[0]); i++)
        if (kPokecenter1F[i] == key) return 1;
    return 0;
}

/* Remove our trade NPC cleanly IF the slot is still ours, and disarm talk. Mirrors ghost_remove.
 * Only ever called when TN->oeId != 0xFF (every call site guards on that), so clearing pi_armed here
 * can't stomp the ghost's arm (the ON-presence path never spawns this NPC). */
static void tn_remove(void)
{
    u8 oe = TN->oeId;
    if (oe == 0xFF) return;
    u32 g = gObjectEvents + (u32)oe * OE_STRIDE;
    if ((R8(g) & 1) && R8(g + 0x08) == TN_LOCALID) {
        RemoveEventObject((void *)g);   /* free sprite */
        R8(g) = 0;                       /* + deactivate (this build's RemoveEventObject won't) */
    }
    /* Only disarm if the talk slot is still OURS — never stomp the ghost's arm (the ghost arms once,
     * at spawn; clearing it here would permanently kill talk-to-ghost on a presence ON transition). */
    if (SS->pi_oe == oe) SS->pi_armed = 0;
    TN->oeId = 0xFF;
}

static void drive_trade_npc(void)
{
    /* Same suspends as drive_ghost: never touch sprites in battle or outside the walkable field. */
    if (R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0) return;
    if (R32(gMain + 4) != CB2_OVERWORLD) return;

    /* A native trade scene is about to take over (it reloads map OEs): tear down NOW in a clean field
     * context and respawn after the scene returns — mirrors drive_ghost's MENU kind-3 branch. */
    if (MENU->pending && MENU->kind == 3) {
        if (TN->oeId != 0xFF) tn_remove();
        return;
    }

    /* Presence ON (or not yet configured): the ghost owns talk; stay out of pi_oe entirely. */
    if (!TN->enable) { if (TN->oeId != 0xFF) tn_remove(); return; }

    u32 player = player_oe();
    u8 pg = R8(player + 0x0A), pn = R8(player + 0x09);

    /* Map change -> the warp rebuilt all OE slots; clean-remove ours so we re-spawn on the new map. */
    if (TN->oeId != 0xFF && (pg != TN->mapG || pn != TN->mapN)) tn_remove();

    if (!is_pokecenter(pg, pn)) { if (TN->oeId != 0xFF) tn_remove(); return; }
    TN->mapG = pg; TN->mapN = pn;

    /* Spawn once at the fixed counter tile (solid, elev 3) and arm talk on the live slot. */
    if (TN->oeId == 0xFF) {
        if (R8(sScriptContext2Enabled)) return;   /* not mid-dialogue / warp fade */
        int oe = SpawnSpecialObjectEventParameterized(PCNPC_GFX, PCNPC_MOVEMENT,
                                                      TN_LOCALID, PCNPC_TILE_X, PCNPC_TILE_Y, /*elev*/3);
        if (oe >= 16) return;                      /* no free slot on this map; retry next frame */
        TN->oeId  = (u8)oe;
        /* Confine the wander. rangeX/rangeY are the 4-bit fields in the HIGH byte of the u16 at OE
         * +0x18 (facing/movementDirection occupy the low byte — same word check_peer_interact reads
         * facing from). The parameterized spawn hardcodes range 0 = UNLIMITED, which would let the
         * NPC roam the whole center and block the door/counter; 0x11 = pace within +-1 tile of the
         * spawn point (the engine's wander handler respects initialCoords +- range). */
        R8(gObjectEvents + (u32)oe * OE_STRIDE + 0x19) = 0x11;
        SS->pi_oe = (u8)oe; SS->pi_armed = 1;
        return;
    }

    /* Slot freed/reassigned under us (post-scene reload, scripted event) -> forget, respawn next frame. */
    u32 g = gObjectEvents + (u32)TN->oeId * OE_STRIDE;
    if (!(R8(g) & 1) || R8(g + 0x08) != TN_LOCALID) {
        if (SS->pi_oe == TN->oeId) SS->pi_armed = 0;
        TN->oeId = 0xFF;
        return;
    }

    /* Keep talk armed on our slot (defensive: another driver may have touched pi_*). */
    if (SS->pi_oe != TN->oeId || !SS->pi_armed) { SS->pi_oe = TN->oeId; SS->pi_armed = 1; }
}

/* ---- event-push producers (EvRing — see the struct comment) ----------------------------------- */
static void ev_push(u8 type, u8 a, u16 b)
{
    if ((u8)(EV->wr - EV->rd) >= 8) { EV->overflow = 1; return; }   /* full: drop + flag, never stall */
    EV->ev[EV->wr & 7] = (u32)type | ((u32)a << 8) | ((u32)b << 16);
    EV->wr++;                                                       /* publish AFTER the payload write */
}

/* Observe battle state natively each frame and push edges as events. Frame-granular counter polling
 * is deliberately chosen over a BL hook into Cmd_tryfaintmon: same settle semantics (the counters
 * only move after protection resolves), zero new detour points, zero battle-engine reentrancy. A
 * multi-faint frame shows as a counter delta > 1 and pushes one event per faint. */
static void drive_events(void)
{
    u8 in_battle = (R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0);
    if (in_battle && !EV->inb) {            /* battle start: latch counter baselines (engine resets them) */
        EV->pfc = R8(gBattleResults);
        EV->ofc = R8(gBattleResults + 1);
    }
    if (in_battle) {
        u8 pfc = R8(gBattleResults), ofc = R8(gBattleResults + 1);
        while (EV->pfc != pfc) { EV->pfc++; ev_push(EV_PLAYER_FAINT, EV->pfc, 0); }
        while (EV->ofc != ofc) { EV->ofc++; ev_push(EV_FOE_FAINT, EV->ofc, 0); }
    } else if (EV->inb) {                   /* battle just ended: push the outcome edge once */
        u8 oc = R8(gBattleOutcome);
        if (oc) ev_push(EV_OUTCOME, oc, 0);
    }
    EV->inb = in_battle;
}

__attribute__((section(".text.entry"), used))
void slink_hook(void)
{
    MB->signature   = SLNK_SIG;   /* presence beacon, every frame */
    MB->abi_version = ABI_VER;

    /* Capture the overworld FIELD callback while the player is walking (you can't walk in a menu /
     * battle / trade scene), then gate the sprite-touching drivers off when we're NOT on the field —
     * so the native party menu / trade scene CB2 (which repurpose gSprites) aren't corrupted by the
     * ghost driver. The async pollers (drive_ui) only read state + the mailbox, so they always run. */
    { u32 p = player_oe();
      if ((R8(p) & 1) && !(R8(p) & 0x80)) MENU->fieldCb = R32(gMain + 0x04); }
    u8 field_active = (MENU->fieldCb == 0) || (R32(gMain + 0x04) == MENU->fieldCb);

    drive_force_move();           /* runs the armed controller-swap each frame */
    drive_swap_state();           /* ends the borrowed-party "Party Freeze" window (begin is a BL hook) */
    drive_battle_notif();         /* re-assert native in-battle notification text (self-guards on battle) */
    drive_events();               /* push faint-settled / battle-outcome edges into the EvRing */
    if (field_active) {
        drive_ghost();            /* engine-driven peer ghost (spawn/walk/despawn lifecycle) */
        drive_trade_npc();        /* Pokémon-Center trade NPC (presence-OFF trade entry point) */
        check_peer_interact();    /* talk-to-ghost / talk-to-NPC detection (generic on SS->pi_oe) */
    } else if (GH->oeId != 0xFF && GH->oeId < 16) {
        /* In a menu/scene CB2 (party picker / trade scene), the engine repurposes gSprites — hide our
         * ghost sprite so its tiles can't bleed into the menu (the initiator's "sprite glitch"). It's
         * re-shown by drive_ghost when the field is active again. */
        u32 g = gObjectEvents + (u32)GH->oeId * OE_STRIDE;
        if ((R8(g) & 1) && R8(g + 0x08) == GH->localId) {
            u8 sid = R8(g + 0x04);
            if (sid < 64) R8(gSprites + (u32)sid * SPR_STRIDE + 0x3E) |= 0x04;   /* invisible */
        }
    }
    drive_ui();                   /* async native UI (menu / party chooser / trade scene) publisher */

    u16 op = MB->opcode;
    if (op == 0) return;          /* idle */

    switch (op) {
    case OP_PING:
        break;

    case OP_FORCE_FAINT: {
        u8 b = MB->args[0];
        R16(gBattleMons + b * BATTLE_MON_SIZE + 0x28) = 0;   /* hp = 0 */
        break;
    }

    case OP_FORCE_MOVE: {        /* commit (live exec needs the controller hook) */
        u8  b      = MB->args[0];
        u8  target = MB->args[1];
        u8  pos    = MB->args[2];
        u16 mid    = (u16)(MB->args[4] | (MB->args[5] << 8));
        if (b > 3 || pos > 3) { ack(ST_FAIL, 2); return; }   /* bound battler/move slot (no OOB read) */
        R8 (gChosenActionByBank  + b)     = 0;     /* USE_MOVE */
        R16(gChosenMovesByBanks  + b * 2) = mid;
        R8 (gBattleCommunication + b)     = 3;
        u32 bs = R32(gBattleStruct);
        if (bs) { R8(bs + 0x80 + b) = pos; R8(bs + 0x0C + b) = target; }
        break;
    }

    case OP_CREATE_MON: {        /* args: [0]=slot [1]=party(0=player,1=enemy) [2..3]=species [4]=level [5]=bump_count */
        u8  slot    = MB->args[0];
        u8  party   = MB->args[1];
        u16 species = (u16)(MB->args[2] | (MB->args[3] << 8));
        u8  level   = MB->args[4];
        u8  bump    = MB->args[5];
        if (slot > 5) { ack(ST_FAIL, 2); return; }
        u32 base = party ? gEnemyParty : gPlayerParty;
        CreateMon((void *)(base + slot * MON_SIZE), species, level,
                  /*fixedIV*/0, /*hasFixedPers*/0, /*fixedPers*/0,
                  /*otIdType*/0, /*otId*/0);
        if (bump) {                          /* GIVE_MON: make it a real party member */
            u32 cnt_addr = party ? gEnemyPartyCount : gPlayerPartyCount;
            if (R8(cnt_addr) < slot + 1) R8(cnt_addr) = slot + 1;
        }
        break;
    }

    case OP_SET_ENEMY_PARTY: {   /* args: [0]=count. Lua staged count*100 raw party-mon bytes in
                                    SLINK_BLOB_BUF. Faithful byte-copy into gEnemyParty (preserves the
                                    partner's EXACT mons: moves/IVs/EVs/PID/item) — NOT CreateMon, which
                                    would lose all of that. The active-foe gBattleMons refresh stays in
                                    Lua (refreshActiveEnemyBattlers): CFRU substruct decrypt has no clean
                                    engine fn. RR/CFRU party-mon layout == enemy-mon layout (NO_ENCRYPT),
                                    so a raw memcpy is sufficient — same basis as M.writeEnemyParty. */
        u8 count = MB->args[0];
        if (count == 0 || count > 6) { ack(ST_FAIL, 2); return; }
        for (u8 i = 0; i < count; i++) {
            volatile u8 *src = (volatile u8 *)(SLINK_BLOB_BUF + (u32)i * MON_SIZE);
            volatile u8 *dst = (volatile u8 *)(gEnemyParty   + (u32)i * MON_SIZE);
            for (u32 j = 0; j < MON_SIZE; j++) dst[j] = src[j];
        }
        /* Zero maxHP (+0x58) on unused slots so CFRU's scan-until-maxHP==0 terminates. */
        for (u8 s = count; s < 6; s++)
            R16(gEnemyParty + (u32)s * MON_SIZE + 0x58) = 0;
        R8(gEnemyPartyCount) = count;
        break;
    }

    case OP_SET_PARTY_MON: {     /* TRADE: faithful 100-byte blob copy into gPlayerParty[slot].
                                    args: [0]=slot [1]=bump (1 = ensure party count covers the slot).
                                    Lua staged ONE complete party-mon (the partner's traded half) in
                                    SLINK_BLOB_BUF. Same basis as OP_SET_ENEMY_PARTY (RR NO_ENCRYPT ->
                                    raw memcpy preserves species/moves/IVs/EVs/PID/item exactly), but
                                    into the PLAYER party. A trade replaces an existing slot, so the
                                    count is unchanged unless `bump` is set (defensive). */
        u8 slot = MB->args[0];
        u8 bump = MB->args[1];
        if (slot > 5) { ack(ST_FAIL, 2); return; }
        volatile u8 *src = (volatile u8 *)SLINK_BLOB_BUF;
        volatile u8 *dst = (volatile u8 *)(gPlayerParty + (u32)slot * MON_SIZE);
        for (u32 j = 0; j < MON_SIZE; j++) dst[j] = src[j];
        if (bump && R8(gPlayerPartyCount) < slot + 1) R8(gPlayerPartyCount) = slot + 1;
        break;
    }

    case OP_SPAWN_PEER_NPC: {     /* args: [0]=gfxId [1]=localId [2..3]=x [4..5]=y [6]=movement */
        u8  gfx     = MB->args[0];
        u8  localId = MB->args[1];
        s16 x       = (s16)(MB->args[2] | (MB->args[3] << 8));
        s16 y       = (s16)(MB->args[4] | (MB->args[5] << 8));
        u8  movement = MB->args[6];
        int oe = SpawnSpecialObjectEventParameterized(gfx, movement, localId, x, y, /*elev*/3);
        MB->result[0] = (u8)oe;   /* object-event id (>=16 = failed) */
        break;
    }

    case OP_SHOW_MESSAGE: {       /* text (FR-encoded, 0xFF-term) already in SLINK_TEXT_BUF */
        if (R8(sScriptContext2Enabled)) { MB->result[0] = 0; break; }  /* a box/script is already up */
        run_sign_msgbox();        /* DISMISSABLE native dialogue (not bare ShowFieldMessage) */
        MB->result[0] = 1;
        break;
    }

    case OP_PLAY_FANFARE: {       /* args: [0..1] = songId (jingle: link-formed / trade-complete) */
        PlayFanfare((u16)(MB->args[0] | (MB->args[1] << 8)));
        break;
    }

    case OP_PLAY_SE: {            /* args: [0..1] = songId — native sound effect (PlaySE) */
        PlaySE((u16)(MB->args[0] | (MB->args[1] << 8)));
        break;
    }

    case OP_SHOW_MENU: {          /* text (FR-encoded) in SLINK_TEXT_BUF -> native YES/NO menu. ASYNC:
                                     ack ST_BUSY now; drive_ui publishes the choice (result[0]) when
                                     the field script resolves. The menuing foundation for talk-to-
                                     partner actions (Trade / status / ...). */
        if (R8(sScriptContext2Enabled)) { ack(ST_FAIL, 1); return; }  /* a box/script already up */
        if (!on_field()) { ack(ST_FAIL, 3); return; }                 /* menu/battle CB2 -> corruption */
        run_yesno_msgbox();
        MENU->kind = 1; MENU->phase = 1; MENU->seq = MB->seq; MENU->frames = 0; MENU->pending = 1;
        MB->status = ST_BUSY; MB->opcode = 0;
        return;
    }

    case OP_SHOW_CHOICES: {       /* options (FR-encoded) staged in SLINK_MENU_BUF -> native multichoice
                                     list. args[0]=1: also speak the SLINK_TEXT_BUF text in a message box
                                     that stays open under the list (the talk-NPC's line). ASYNC;
                                     lockall-bracketed like OP_SHOW_MENU, so drive_ui kind 1 publishes
                                     the chosen index (result[0]; 0x7F = cancel). */
        if (R8(sScriptContext2Enabled)) { ack(ST_FAIL, 1); return; }
        if (!on_field()) { ack(ST_FAIL, 3); return; }
        run_choices(MB->args[0]);
        MENU->kind = 1; MENU->phase = 1; MENU->seq = MB->seq; MENU->frames = 0; MENU->pending = 1;
        MB->status = ST_BUSY; MB->opcode = 0;
        return;
    }

    case OP_CHOOSE_PARTY_MON: {   /* native "Choose a POKeMON" party menu. ASYNC: ack ST_BUSY; drive_ui
                                     publishes the chosen slot (result[0]=0-5, or 7=cancel) once the menu
                                     closes (Var8004). Used to pick WHICH linked mon to trade. */
        if (R8(sScriptContext2Enabled)) { ack(ST_FAIL, 1); return; }
        if (!on_field()) { ack(ST_FAIL, 3); return; }
        R16(gSpecialVar_0x8004) = 0x00FF;    /* sentinel -> the menu overwrites it with 0-5 / 7 */
        run_party_chooser();
        MENU->kind = 2; MENU->seq = MB->seq; MENU->frames = 0; MENU->pending = 1;
        MB->status = ST_BUSY; MB->opcode = 0;
        return;
    }

    case OP_TRADE_SCENE: {        /* args[0]=slot. Run the NATIVE trade animation+evolution: trades
                                     gPlayerParty[slot] with the mon staged in gEnemyParty[0] (caller
                                     must OP_SET_ENEMY_PARTY count=1 first). ASYNC: ack ST_BUSY; drive_ui
                                     acks ST_OK when the scene returns to the field. */
        if (R8(sScriptContext2Enabled)) { ack(ST_FAIL, 1); return; }
        if (MB->args[0] > 5) { ack(ST_FAIL, 2); return; }
        if (!on_field()) { ack(ST_FAIL, 3); return; }            /* also keeps fieldCb from caching a
                                                                  * transient menu CB2 (stale-cb hang) */
        if (!MENU->fieldCb) MENU->fieldCb = R32(gMain + 0x04);   /* dispatched from the field */
        run_trade_scene(MB->args[0]);
        MENU->kind = 3; MENU->phase = 0; MENU->seq = MB->seq; MENU->frames = 0; MENU->pending = 1;
        MB->status = ST_BUSY; MB->opcode = 0;
        return;
    }

    /* opcodes 10 OP_APPLY_DAMAGE, 11 OP_CURE_STATUS, 12 OP_SET_RULES REMOVED — no case here, so
     * they fall through to default: ack(ST_FAIL, 1), the same as any unknown/older opcode. */

    case OP_ARM_PEER_INTERACT:    /* talk-to-ghost: args [0]=ghost oeId [1]=armed (1=on) */
        SS->pi_oe = MB->args[0];
        SS->pi_armed = MB->args[1];
        if (MB->args[1]) SS->pi_count = 0;
        break;

    case OP_DESPAWN_PEER_NPC: {   /* args: [0]=objectEventId */
        u8 oe = MB->args[0];
        if (oe >= 16) { ack(ST_FAIL, 2); return; }
        u32 oebase = gObjectEvents + (u32)oe * OE_STRIDE;
        if (!(R8(oebase) & 1)) { ack(ST_FAIL, 3); return; }   /* OE not active: spriteId is garbage */
        u8 spriteId = R8(oebase + OE_SPRITE_ID);
        if (spriteId >= SPR_COUNT) { ack(ST_FAIL, 4); return; }  /* never index gSprites OOB */
        DestroySprite((void *)(gSprites + (u32)spriteId * SPR_STRIDE));
        R8(oebase + 0x00) = 0;    /* clear active flag (RemoveObjectEventInternal) */
        break;
    }

    case OP_GHOST_SPAWN:          /* engine-driven ghost: args [0]=gfxId [1]=localId. The frame */
        ghost_remove();           /* CLEAN UP any existing ghost FIRST. A re-spawn (client reconnect / */
                                  /* Lua reload re-inits the receiver -> re-sends OP_GHOST_SPAWN) used */
                                  /* to just set oeId=0xFF, ORPHANING the live OE as a permanent */
                                  /* invisible wall "where the player was at connection". Now removed. */
        GH->gfxId  = MB->args[0]; /* hook (drive_ghost) spawns + drives it; Lua then posts the */
        GH->localId = MB->args[1];/* partner's world-px position + avatar into GhostState. */
        GH->oeId   = 0xFF;
        GH->curGfx = 0xFF;        /* force a spawn next frame */
        GH->flags = 0;            /* recompute C + disp on first drive */
        GH->snap = 0;             /* the spawn branch arms the first snap once the OE exists */
        GH->avatarDirty = 0; GH->imgs = 0; GH->anims = 0;  /* no partner avatar until Lua posts one */
        GH->pmapGroup = R8(player_oe() + 0x0A);     /* seed map so frame 1 doesn't false-trigger */
        GH->pmapNum   = R8(player_oe() + 0x09);
        GH->active = 1;
        break;

    case OP_GHOST_CLEAR:          /* drive_ghost does the clean RemoveEventObject next frame */
        GH->active = 0;
        break;

    case OP_FORCE_MOVE_SLOT:      /* args: [0]=battler [1]=target [2]=move_pos */
        if (MB->args[0] > 3 || MB->args[2] > 3) { ack(ST_FAIL, 2); return; }  /* bound: slink_force_controller reads gBattleMons[battler].moves[move_pos] */
        AM->battler  = MB->args[0];
        AM->target   = MB->args[1];
        AM->move_pos = MB->args[2];
        AM->seq      = MB->seq;
        AM->frames   = 0;
        AM->armed    = 1;
        MB->status   = ST_BUSY;   /* the controller acks when the move fires */
        MB->opcode   = 0;
        return;

    case OP_SHOW_BATTLE_MESSAGE: {  /* native IN-BATTLE text (the BizHawk-HUD-in-battle replacement).
                                       args: [0..1]=duration frames, [2]=window id (0 -> 0xD). Text staged
                                       FR-encoded in SLINK_TEXT_BUF. ARM only: drive_battle_notif spawns a
                                       RunTasks draw task (slink_notif_task) that renders it each frame. */
        if (!(R16(gBattleMons + 0x2C) > 0 && R8(gBattleOutcome) == 0)) { ack(ST_FAIL, 1); return; }  /* not in battle */
        BN->frames  = (u16)(MB->args[0] | (MB->args[1] << 8));
        if (BN->frames == 0) BN->frames = 240;
        BN->win     = MB->args[2] ? MB->args[2] : 0x0D;   /* target window (default 0xD = the calc's move-info area) */
        BN->task    = 0xFF;                               /* no draw task yet (drive_battle_notif creates it) */
        BN->phase   = 0;
        BN->active  = 1;
        break;                                            /* -> ack(ST_OK, 0) */
    }

    case OP_WITHDRAW_MON: {       /* PC box (compressed) -> party. args [0]=boxId [1]=boxPos [2]=partySlot.
                                     Lua scans the box for the key (a READ) and passes the located slot +
                                     the target party slot (= current count). The engine conversion runs
                                     the real BoxMonToMon/PP/stats math, so the mon comes out fully formed. */
        u8 box = MB->args[0], pos = MB->args[1], ps = MB->args[2];
        if (box >= TOTAL_BOXES_COUNT || pos >= IN_BOX_COUNT || ps > 5) { ack(ST_FAIL, 2); return; }
        u32 comp = R32(sPokemonBoxPtrs + (u32)box * 4) + (u32)pos * COMPRESSED_MON_SIZE;
        CompressedMonToMon((void *)comp, (void *)(gPlayerParty + (u32)ps * MON_SIZE));
        if (R8(gPlayerPartyCount) <= ps) R8(gPlayerPartyCount) = (u8)(ps + 1);   /* extend count to cover the new slot */
        for (u32 i = 0; i < COMPRESSED_MON_SIZE; i++) R8(comp + i) = 0;          /* free the box slot (the mon moved) */
        break;
    }

    case OP_DEPOSIT_MON: {        /* party -> PC box (compressed). args [0]=partySlot [1]=boxId [2]=boxPos.
                                     A party Pokemon's first 80 bytes ARE a BoxPokemon, so compress straight
                                     from it; then remove the mon from the party (shift-compact + count--),
                                     mirroring the Lua depositPartyMon exactly. */
        u8 ps = MB->args[0], box = MB->args[1], pos = MB->args[2];
        if (ps > 5 || box >= TOTAL_BOXES_COUNT || pos >= IN_BOX_COUNT) { ack(ST_FAIL, 2); return; }
        u8 count = R8(gPlayerPartyCount);
        if (ps >= count) { ack(ST_FAIL, 3); return; }                           /* slot must hold a real mon */
        u32 comp = R32(sPokemonBoxPtrs + (u32)box * 4) + (u32)pos * COMPRESSED_MON_SIZE;
        CreateCompressedMonFromBoxMon((void *)(gPlayerParty + (u32)ps * MON_SIZE), (void *)comp);
        for (u8 s = ps; (u8)(s + 1) < count; s++)                               /* shift [ps+1..] down one slot */
            real_memcpy((void *)(gPlayerParty + (u32)s * MON_SIZE),
                        (void *)(gPlayerParty + (u32)(s + 1) * MON_SIZE), MON_SIZE);
        { u32 last = gPlayerParty + (u32)(count - 1) * MON_SIZE;                /* zero the vacated last slot */
          for (u32 i = 0; i < MON_SIZE; i++) R8(last + i) = 0; }
        R8(gPlayerPartyCount) = (u8)(count - 1);
        break;
    }

    case OP_MEMORIALIZE: {        /* party -> memorial box. args [0]=partySlot [1]=boxId [2]=boxPos.
                                     Same compress as OP_DEPOSIT_MON, but removal is ZERO + SWAP-WITH-
                                     LAST (not shift): surviving mons KEEP their slot indices, so
                                     CFRU's deferred battle writes can't land on the wrong mon —
                                     mirrors Lua M.memorializeMon exactly. Lua picks the free memorial
                                     slot + does the box rename (one-time, non-critical RAM writes). */
        u8 ps = MB->args[0], box = MB->args[1], pos = MB->args[2];
        if (ps > 5 || box >= TOTAL_BOXES_COUNT || pos >= IN_BOX_COUNT) { ack(ST_FAIL, 2); return; }
        u8 count = R8(gPlayerPartyCount);
        if (ps >= count) { ack(ST_FAIL, 3); return; }
        u32 comp = R32(sPokemonBoxPtrs + (u32)box * 4) + (u32)pos * COMPRESSED_MON_SIZE;
        CreateCompressedMonFromBoxMon((void *)(gPlayerParty + (u32)ps * MON_SIZE), (void *)comp);
        u32 base = gPlayerParty + (u32)ps * MON_SIZE;
        for (u32 i = 0; i < MON_SIZE; i++) R8(base + i) = 0;
        if ((u8)(ps + 1) < count) {                                             /* swap last into the hole */
            u32 last = gPlayerParty + (u32)(count - 1) * MON_SIZE;
            real_memcpy((void *)base, (void *)last, MON_SIZE);
            for (u32 i = 0; i < MON_SIZE; i++) R8(last + i) = 0;
        }
        R8(gPlayerPartyCount) = (u8)(count - 1);
        break;
    }

    default:
        ack(ST_FAIL, 1);          /* unknown opcode */
        return;
    }

    ack(ST_OK, 0);
}
