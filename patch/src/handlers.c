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
       OP_APPLY_DAMAGE = 10, OP_CURE_STATUS = 11 };
enum { ST_BUSY = 1, ST_OK = 2, ST_FAIL = 3 };

/* Armed forced-move state (controller-swap driver), EWRAM scratch past the mailbox. */
typedef struct {
    volatile u8  armed, battler, move_pos, target;
    volatile u16 seq, frames;
} ArmedMove;
#define AM ((ArmedMove *)0x0203F8C0u)

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
#define SLINK_TEXT_BUF 0x0203F900u   /* Lua writes FR-encoded text here before SHOW_MESSAGE */
#define gObjectEvents 0x02036E38u   /* stride 0x24 */
#define OE_STRIDE     0x24u
#define gSprites      0x0202063Cu   /* stride 0x44 */
#define SPR_STRIDE    0x44u

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

__attribute__((section(".text.entry"), used))
void slink_hook(void)
{
    MB->signature   = SLNK_SIG;   /* presence beacon, every frame */
    MB->abi_version = ABI_VER;

    drive_force_move();           /* runs the armed controller-swap each frame */

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
        u8 shown = ShowFieldMessage((const u8 *)SLINK_TEXT_BUF);
        MB->result[0] = shown;    /* 1 = box shown, 0 = a box was already up */
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

    case OP_DESPAWN_PEER_NPC: {   /* args: [0]=objectEventId */
        u8 oe = MB->args[0];
        if (oe >= 16) { ack(ST_FAIL, 2); return; }
        u32 oebase = gObjectEvents + (u32)oe * OE_STRIDE;
        u8 spriteId = R8(oebase + 0x04);
        DestroySprite((void *)(gSprites + (u32)spriteId * SPR_STRIDE));
        R8(oebase + 0x00) = 0;    /* clear active flag (RemoveObjectEventInternal) */
        break;
    }

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
