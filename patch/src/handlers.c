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
typedef int16_t s16;

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
       OP_APPLY_DAMAGE = 10, OP_CURE_STATUS = 11,
       OP_SET_RULES = 12, OP_ARM_PEER_INTERACT = 13,
       OP_GHOST_SPAWN = 14, OP_GHOST_CLEAR = 15 };
enum { ST_BUSY = 1, ST_OK = 2, ST_FAIL = 3 };

/* Armed forced-move state (controller-swap driver), EWRAM scratch past the mailbox. */
typedef struct {
    volatile u8  armed, battler, move_pos, target;
    volatile u16 seq, frames;
} ArmedMove;
#define AM ((ArmedMove *)0x0203F8C0u)

/* Persistent companion-patch state (nuzlocke enforcement + peer interaction). */
typedef struct {
    volatile u8 enforce_rules;   /* re-assert battle-style SET every frame */
    volatile u8 pi_armed;        /* peer-interaction detection on */
    volatile u8 pi_oe;           /* ghost object-event id to watch */
    volatile u8 pi_count;        /* ++ on each interact (Lua polls); also shows the box */
} SlinkState;
#define SS ((SlinkState *)0x0203F8D0u)

/* Engine-driven peer ghost. Lua writes the target (tile + facing + gfx) into this shared block;
 * the frame hook (drive_ghost) walks a real object-event toward it via the engine's held-movement
 * API — the engine owns animation/sub-pixel/palette/tint/culling/collision. Placed in the free
 * EWRAM gap between the mailbox (ends 0x0203F840) and AM (0x0203F8C0). 14 bytes; tx/ty 2-aligned. */
typedef struct {
    volatile u8  active;     /* 0  1 = ghost should exist + be driven */
    volatile u8  oeId;       /* 1  object-event id the hook owns (0xFF = not spawned) */
    volatile u8  gfxId;      /* 2  graphicsId Lua wants (changes => re-spawn: bike/surf/fish) */
    volatile u8  curGfx;     /* 3  graphicsId currently spawned */
    volatile u8  localId;    /* 4  sentinel localId (0xF0) */
    volatile u8  _pad0;      /* 5  (align tx to offset 6) */
    volatile s16 tx;         /* 6  target tile x (object-event currentCoords space) */
    volatile s16 ty;         /* 8  target tile y */
    volatile u8  tface;      /* 10 target facing 1=S 2=N 3=W 4=E (idle facing on arrival) */
    volatile u8  run;        /* 11 speed hint: 1 = partner dashing -> run to keep up */
    volatile u8  pmapGroup;  /* 12 player's last map group the hook recorded */
    volatile u8  pmapNum;    /* 13 player's last map num */
} GhostState;
#define GH ((GhostState *)0x0203F850u)

#define gSaveBlock2Ptr 0x0300500Cu
#define gMain          0x030030F0u   /* newKeys @ +0x2E (A = 0x0001) */
#define KEY_A          0x0001u
#define OPT_BATTLE_STYLE_SET 0x0200u /* bit 9 of options u16 @ SaveBlock2+0x14 */

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

#define R8(a)   (*(volatile u8 *)(a))
#define R16(a)  (*(volatile u16*)(a))
#define R32(a)  (*(volatile u32*)(a))

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
/* void ScriptContext1_SetupScript(const u8 *ptr) @0x08069AE4 — queues a field script the
 * overworld runs NATIVELY: lockall -> message -> waitmessage -> waitbuttonpress -> releaseall.
 * Unlike a bare ShowFieldMessage (draws a box nothing ever closes), this is a real, navigable,
 * A-to-dismiss conversation. We hand it a tiny EWRAM script that points at our text buffer. */
typedef void (*SetupScript_t)(const u8 *ptr);
#define ScriptContext1_SetupScript ((SetupScript_t)0x08069AE5u)
#define sScriptContext2Enabled 0x03000F9Cu   /* u8 != 0 while a field script/dialogue is active */
#define SLINK_TEXT_BUF   0x0203F900u   /* Lua writes FR-encoded text here before SHOW_MESSAGE */
#define SLINK_SCRIPT_BUF 0x0203F8E0u   /* 9-byte EWRAM scratch: our "msgbox sign" bytecode */
#define gObjectEvents 0x02036E38u   /* stride 0x24 */
#define OE_STRIDE     0x24u
#define gSprites      0x0202063Cu   /* stride 0x44 */
#define SPR_STRIDE    0x44u

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
#define GHOST_SNAP_TILES 4   /* >this many tiles off -> snap instead of walking there */

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

/* ROM-enforced nuzlocke: keep battle style on SET so the player can't free-switch after a KO. */
static void enforce_rules(void)
{
    if (!SS->enforce_rules) return;
    u32 sb2 = R32(gSaveBlock2Ptr);
    if (sb2) R16(sb2 + 0x14) |= OPT_BATTLE_STYLE_SET;
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

/* Peer interaction: when the player presses A facing the ghost NPC, show the pre-set message
 * (dismissable native box) and bump a counter the Lua client polls (to notify the server / partner). */
static void check_peer_interact(void)
{
    if (!SS->pi_armed) return;
    if (R8(sScriptContext2Enabled)) return;              /* a dialogue/script is already up */
    if (!(R16(gMain + 0x2E) & KEY_A)) return;            /* A newly pressed this frame? */
    u32 g = gObjectEvents + (u32)SS->pi_oe * OE_STRIDE;
    if (!(R8(g) & 1)) return;                             /* ghost active? */
    u32 p = gObjectEvents;                                /* player = object-event slot 0 */
    int px = (s16)R16(p + 0x10), py = (s16)R16(p + 0x12);
    u8  f  = R8(p + 0x18) & 0x0F;
    if      (f == 1) py++;       /* down */
    else if (f == 2) py--;       /* up */
    else if (f == 3) px--;       /* left */
    else if (f == 4) px++;       /* right */
    if (px == (s16)R16(g + 0x10) && py == (s16)R16(g + 0x12)) {
        SS->pi_count++;
        run_sign_msgbox();
    }
}

/* Reassign the ghost's OBJ palette slot if the spawned gfx uses PALSLOT_PLAYER (slot 0), which would
 * collide with the real player and corrupt the ghost's colours. STUB for now — first build verifies
 * (via the ghostpalette test) whether the broadcast gfx actually collides before adding the reassign;
 * non-player trainer gfx already get their own ref-counted slot and are correct natively. */
static void fixup_palette(u8 oe)
{
    (void)oe;
}

/* Remove our ghost cleanly (sprite + object-event) IF the slot is still ours, then disarm interact.
 * Never RemoveEventObject a slot a real NPC now owns (post-warp the slot is reused). */
static void ghost_remove(void)
{
    if (GH->oeId != 0xFF) {
        u32 g = gObjectEvents + (u32)GH->oeId * OE_STRIDE;
        if ((R8(g) & 1) && R8(g + 0x08) == GH->localId)
            RemoveEventObject((void *)g);
        GH->oeId = 0xFF;
    }
    SS->pi_armed = 0;
}

/* Engine-driven peer ghost: spawn a real NPC once, then each frame queue a held movement toward the
 * Lua-provided target tile and let the engine animate/position/palette/cull/collide it. Owns the
 * map-change and gfx-change lifecycle the Lua side cannot time. */
static void drive_ghost(void)
{
    if (!GH->active) { if (GH->oeId != 0xFF) ghost_remove(); return; }

    u32 player = gObjectEvents;                  /* slot 0 */
    u8 pg = R8(player + 0x0A), pn = R8(player + 0x09);

    /* (a) map change -> the warp rebuilt all OE slots; clean-remove ours and re-spawn on the new map. */
    if (GH->oeId != 0xFF && (pg != GH->pmapGroup || pn != GH->pmapNum)) ghost_remove();
    GH->pmapGroup = pg; GH->pmapNum = pn;

    /* (b) gfx change (partner mounted bike / surfed / fished) -> re-spawn with the new sprite. */
    if (GH->oeId != 0xFF && GH->gfxId != GH->curGfx) ghost_remove();

    /* (c) spawn once, adjacent to the player. */
    if (GH->oeId == 0xFF) {
        if (R8(sScriptContext2Enabled)) return;  /* not mid-dialogue/warp fade */
        s16 px = (s16)R16(player + 0x10), py = (s16)R16(player + 0x12);
        u8  elev = R8(player + 0x0B) & 0x0F;
        int oe = SpawnSpecialObjectEventParameterized(GH->gfxId, /*MOVEMENT_TYPE_NONE*/0,
                                                      GH->localId, px, (s16)(py + 1), elev);
        if (oe >= 16) return;                    /* no free slot on this map; retry next frame */
        GH->oeId = (u8)oe; GH->curGfx = GH->gfxId;
        fixup_palette((u8)oe);
        SS->pi_oe = (u8)oe; SS->pi_armed = 1;    /* auto-arm talk-to-ghost on the live slot */
        return;
    }

    u32 g = gObjectEvents + (u32)GH->oeId * OE_STRIDE;

    /* (d) slot freed/reassigned under us -> forget, respawn next frame. */
    if (!(R8(g) & 1) || R8(g + 0x08) != GH->localId) { GH->oeId = 0xFF; return; }

    /* (e) only issue a new movement once the previous step finished (let the engine animate it). */
    u8 st = EventObjectClearHeldMovementIfFinished((void *)g);
    if (st != 0 && st != 16) return;

    s16 gx = (s16)R16(g + 0x10), gy = (s16)R16(g + 0x12);
    int dx = GH->tx - gx, dy = GH->ty - gy;
    int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;

    /* (f) too far (teleport/desync) -> hard re-place rather than walking dozens of tiles. */
    if (adx > GHOST_SNAP_TILES || ady > GHOST_SNAP_TILES) {
        MoveEventObjectToMapCoords((void *)g, GH->tx, GH->ty);
        EventObjectTurn((void *)g, GH->tface);
        return;
    }
    /* (g) arrived -> idle facing the partner's facing. */
    if (dx == 0 && dy == 0) {
        EventObjectSetHeldMovement((void *)g, GetFaceDirectionMovementAction(GH->tface));
        return;
    }
    /* (h) step toward the target on the larger-gap axis (4-dir; X on tie). Run when dashing or >1
     *     tile behind so the ghost catches up; else walk. */
    u32 dir = (adx >= ady) ? (dx > 0 ? DIR_EAST : DIR_WEST)
                           : (dy > 0 ? DIR_SOUTH : DIR_NORTH);
    u8 action = (GH->run || (adx + ady) > 1) ? GetWalkFastMovementAction(dir)
                                             : GetWalkNormalMovementAction(dir);
    EventObjectSetHeldMovement((void *)g, action);
}

__attribute__((section(".text.entry"), used))
void slink_hook(void)
{
    MB->signature   = SLNK_SIG;   /* presence beacon, every frame */
    MB->abi_version = ABI_VER;

    drive_force_move();           /* runs the armed controller-swap each frame */
    enforce_rules();              /* persistent nuzlocke option enforcement */
    drive_ghost();                /* engine-driven peer ghost (spawn/walk/despawn lifecycle) */
    check_peer_interact();        /* talk-to-ghost detection */

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

    case OP_PLAY_FANFARE: {       /* args: [0..1] = songId */
        PlayFanfare((u16)(MB->args[0] | (MB->args[1] << 8)));
        break;
    }

    case OP_APPLY_DAMAGE: {       /* linked HP / chip: args [0]=battler [1..2]=amount(u16) */
        u8  b   = MB->args[0];
        u16 amt = (u16)(MB->args[1] | (MB->args[2] << 8));
        u32 hpaddr = gBattleMons + (u32)b * BATTLE_MON_SIZE + 0x28;
        u16 hp = R16(hpaddr);
        hp = (hp > amt) ? (u16)(hp - amt) : 0;
        R16(hpaddr) = hp;         /* engine refreshes the health box on its next touch */
        MB->result[0] = (u8)hp;   /* result[0..1] = new hp (0 => mon will faint) */
        MB->result[1] = (u8)(hp >> 8);
        break;
    }

    case OP_CURE_STATUS: {        /* link-cured status: args [0]=battler — clear status1 */
        u8 b = MB->args[0];
        *(volatile u32 *)(gBattleMons + (u32)b * BATTLE_MON_SIZE + 0x4C) = 0;
        break;
    }

    case OP_SET_RULES:            /* ROM-enforced nuzlocke: args [0]=enforce (1=on) */
        SS->enforce_rules = MB->args[0];
        break;

    case OP_ARM_PEER_INTERACT:    /* talk-to-ghost: args [0]=ghost oeId [1]=armed (1=on) */
        SS->pi_oe = MB->args[0];
        SS->pi_armed = MB->args[1];
        if (MB->args[1]) SS->pi_count = 0;
        break;

    case OP_DESPAWN_PEER_NPC: {   /* args: [0]=objectEventId */
        u8 oe = MB->args[0];
        if (oe >= 16) { ack(ST_FAIL, 2); return; }
        u32 oebase = gObjectEvents + (u32)oe * OE_STRIDE;
        u8 spriteId = R8(oebase + 0x04);
        DestroySprite((void *)(gSprites + (u32)spriteId * SPR_STRIDE));
        R8(oebase + 0x00) = 0;    /* clear active flag (RemoveObjectEventInternal) */
        break;
    }

    case OP_GHOST_SPAWN:          /* engine-driven ghost: args [0]=gfxId [1]=localId. The frame */
        GH->gfxId  = MB->args[0]; /* hook (drive_ghost) spawns + drives it; Lua then writes the */
        GH->localId = MB->args[1];/* target tile/facing/gfx into GhostState each tick. */
        GH->oeId   = 0xFF;
        GH->curGfx = 0xFF;        /* force a spawn next frame */
        GH->pmapGroup = R8(gObjectEvents + 0x0A);   /* seed map so frame 1 doesn't false-trigger */
        GH->pmapNum   = R8(gObjectEvents + 0x09);
        GH->active = 1;
        break;

    case OP_GHOST_CLEAR:          /* drive_ghost does the clean RemoveEventObject next frame */
        GH->active = 0;
        break;

    case OP_FORCE_MOVE_SLOT:      /* args: [0]=battler [1]=target [2]=move_pos */
        AM->battler  = MB->args[0];
        AM->target   = MB->args[1];
        AM->move_pos = MB->args[2];
        AM->seq      = MB->seq;
        AM->frames   = 0;
        AM->armed    = 1;
        MB->status   = ST_BUSY;   /* the controller acks when the move fires */
        MB->opcode   = 0;
        return;

    default:
        ack(ST_FAIL, 1);          /* unknown opcode */
        return;
    }

    ack(ST_OK, 0);
}
