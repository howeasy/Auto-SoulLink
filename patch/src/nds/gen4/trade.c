/* C5 thin game binding. Policy/lifecycle stays in trade_policy.h, shared ABI unchanged.
 * All persistent storage is C2's layout-2 trade sub-struct; no file-scope object.
 * SOURCE citations: pinned pret/pokeheartgold ad7a3afa. Native link/PHYSICAL still OPEN.
 */
#include "global.h"
#include "party.h"
#include "pokemon.h"
#include "system.h"
#include "trade.h"

/* OPEN game/context seams: no guessed ScrCmd variable, fade/script gate, save mode,
 * watchdog bound, or scene-completion predicate. Context must survive the whole trade.
 * Post-save functions return the ALREADY mapped SlinkSavePoll vocabulary.
 * Consent is 0 waiting, 2 yes, 1 ready, negative cancel: NO native pre-commit save.
 * Pokedex delivery choice remains the spec's separate Q4; no extra write is invented.
 */
/* Transparent pointer typedef: the existing C2 source detector accepts typed prototypes
 * but not a '*' return declarator. This is still a function declaration, no object. */
typedef SaveData *SlinkGen4TradeSaveDataPtr;
extern SlinkGen4TradeSaveDataPtr Slink_Gen4Trade_SaveData(void *context);
extern int Slink_Gen4Trade_SelectedSlot(void *context, unsigned *slot);
extern int Slink_Gen4Trade_SafeField(void *context);
extern int Slink_Gen4Trade_StartConsent(void *context);
extern int Slink_Gen4Trade_PollConsent(void *context);
extern int Slink_Gen4Trade_SceneStart(void *context, unsigned slot, const uint8_t *record, uint16_t len);
extern int Slink_Gen4Trade_ScenePoll(void *context);
extern int Slink_Gen4Trade_PostSaveBegin(void *context);
extern int Slink_Gen4Trade_PostSavePoll(void *context);

static Party *Slink_Gen4Trade_Party(void *context)
{
    SaveData *save = Slink_Gen4Trade_SaveData(context);
    /* include/party.h:23; npc_trade.c:110: no save offset or FieldSystem guess. */
    return save != NULL ? SaveArray_Party_Get(save) : NULL;
}

static int Slink_Gen4Trade_Count(void *context)
{
    Party *party = Slink_Gen4Trade_Party(context);
    int count = party != NULL ? Party_GetCount(party) : 0; /* party.h:14 */
    return count > 0 && count <= (int)SLINK_GEN4_PARTY_SLOTS ? count : 0;
}

static int Slink_Gen4Trade_Verify(void *context, const uint8_t *record, uint16_t len)
{
    Pokemon *copy = (Pokemon *)(void *)record;
    (void)context;
    /* Called on the POLICY'S private decoder copy, never on incoming or party bytes.
     * pokemon_types_def.h:155-164,217; pokemon.c:60-67 (DECRYPT_BOX/CHECKSUM).
     * Do NOT use GetMonData to discover a corrupt checksum: it asserts at :416-419.
     * Instead call the engine decrypt/checksum directly and return refusal.
     */
    if (record == NULL || len != sizeof(Pokemon)) return 0;
    if (copy->box.partyDecrypted || copy->box.boxDecrypted || copy->box.checksumFailed) return 0;
    MonDecryptSegment(copy->box.dataBlocks, sizeof copy->box.dataBlocks, copy->box.checksum);
    return CalcMonChecksum(copy->box.dataBlocks, sizeof copy->box.dataBlocks) == copy->box.checksum;
}

static int Slink_Gen4Trade_Decode(void *context, const uint8_t *record, uint16_t len,
                                uint16_t logical_offset, uint32_t *out)
{
    Pokemon *copy = (Pokemon *)(void *)record;
    if (out == NULL || logical_offset != slink_binding_gen4_pk4.otid_logical_off) return 0;
    if (!Slink_Gen4Trade_Verify(context, record, len)) return 0;
    /* Private copy is already decrypted and checked: avoid the getter's assert path.
     * GetBoxMonData's native GetSubstruct dispatch reads OT at MON_DATA_OT_ID
     * (pokemon.c:464-482,539-541); no PK4 shuffle/cipher is authored here. */
    copy->box.boxDecrypted = TRUE;
    *out = GetBoxMonData(&copy->box, MON_DATA_OT_ID, NULL);
    return 1;
}

static int Slink_Gen4Trade_Record(void *context, unsigned slot, const uint8_t **record, uint16_t *len)
{
    Party *party = Slink_Gen4Trade_Party(context);
    Pokemon *mon;
    int count = party != NULL ? Party_GetCount(party) : 0;
    if (count <= 0 || count > (int)SLINK_GEN4_PARTY_SLOTS || party == NULL || record == NULL || len == NULL || slot >= (unsigned)count
        || slot >= SLINK_GEN4_PARTY_SLOTS) return 0;
    /* Party_GetMonByIndex asserts bounds (party.c:9-12,56-59); check first. */
    mon = Party_GetMonByIndex(party, (int)slot);
    if (mon == NULL) return 0;
    *record = (const uint8_t *)mon;
    *len = (uint16_t)sizeof(Pokemon);
    return 1;
}

static int Slink_Gen4Trade_Identity(void *context, unsigned slot, SlinkIdentity *identity)
{
    const uint8_t *record;
    uint16_t len;
    Pokemon copy;
    if (identity == NULL || !Slink_Gen4Trade_Record(context, slot, &record, &len)) return 0;
    memcpy(&copy, record, sizeof copy);
    identity->pid = copy.box.personality; /* pokemon_types_def.h:156, plaintext header */
    return Slink_Gen4Trade_Decode(context, (const uint8_t *)&copy, len,
                                slink_binding_gen4_pk4.otid_logical_off, &identity->otid);
}

static int Slink_Gen4Trade_CopySlot(void *context, unsigned slot, const uint8_t *record, uint16_t len)
{
    Party *party = Slink_Gen4Trade_Party(context);
    Pokemon copy, checked;
    int count = party != NULL ? Party_GetCount(party) : 0;
    if (count <= 0 || count > (int)SLINK_GEN4_PARTY_SLOTS || party == NULL || record == NULL || len != sizeof copy || slot >= SLINK_GEN4_PARTY_SLOTS
        || slot >= (unsigned)count) return 0;
    memcpy(&copy, record, sizeof copy);
    memcpy(&checked, record, sizeof checked);
    if (!Slink_Gen4Trade_Verify(context, (const uint8_t *)&checked, len)) return 0;
    /* The ONE RAM mutation, after policy bounds/COMMIT_ENTERED. Copy the pristine
     * bytes so the native getter cannot temporarily decrypt producer.incoming.
     * party.c:97-105 / npc_trade.c:154 reset Aprijuice modifiers via this exact API. */
    Party_SafeCopyMonToSlot_ResetAprijuiceModifiers(party, (int)slot, &copy);
    return 1;
}

static uint32_t Slink_Gen4Trade_Frame(void *context)
{
    (void)context;
    return gSystem.vblankCounter; /* system.h:33,60; main.c:124 forbids frameCounter */
}

static int Slink_Gen4Trade_Start(void *context)
{
    return Slink_Gen4Trade_StartConsent(context); /* Q3: consent only, save ONLY after */
}

static int Slink_Gen4Trade_State(const SlinkGen4State *st)
{
    return st != NULL && st->magic == SLINK_GEN4_STATE_MAGIC
        && Slink_Gen4TradeState_LayoutValid(&st->trade)
        && st->trade.policy.magic == SLINK_GEN4_TRADE_POLICY_MAGIC;
}

int Slink_NDS_Trade_Bind(SlinkGen4State *st, const SlinkGen4TradeSeam *seam,
                       volatile SlinkTradeWitnessV2 *witness,
                       const volatile SlinkRecordStageV1 *stage, uint32_t save_timeout_frames)
{
    if (st == NULL || st->magic != SLINK_GEN4_STATE_MAGIC || seam == NULL || seam->frame == NULL
        || witness == NULL || stage == NULL || save_timeout_frames == 0) return 0;
    if (st->trade.layout != 0) return 0; /* first bind only; stale/current allocations never rebind */
    if (st->trade.policy.magic == SLINK_GEN4_TRADE_POLICY_MAGIC) return 0; /* never rebind live state */
    st->trade.seam = *seam; /* callbacks/opaque context outlive this service stack */
    if (!Slink_Gen4TradePolicy_Init(&st->trade.policy, &st->trade.seam, witness, stage, save_timeout_frames)) return 0;
    st->trade.layout = SLINK_GEN4_STATE_TRADE_LAYOUT;
    st->trade.caps = 0;
    return 1;
}

int Slink_NDS_Trade_Init(SlinkGen4State *st, void *context, volatile SlinkTradeWitnessV2 *witness,
                       const volatile SlinkRecordStageV1 *stage, uint32_t save_timeout_frames)
{
    SlinkGen4TradeSeam seam;
    if (context == NULL) return 0;
    memset(&seam, 0, sizeof seam);
    seam.context = context;
    seam.party_count = Slink_Gen4Trade_Count;
    seam.party_slot_identity = Slink_Gen4Trade_Identity;
    seam.party_slot_record = Slink_Gen4Trade_Record;
    seam.script_chosen_slot = Slink_Gen4Trade_SelectedSlot;
    seam.commit_party_slot = Slink_Gen4Trade_CopySlot;
    seam.safe_field = Slink_Gen4Trade_SafeField;
    seam.start_pre_save = Slink_Gen4Trade_Start;
    seam.poll_pre_save = Slink_Gen4Trade_PollConsent;
    seam.scene_start = Slink_Gen4Trade_SceneStart;
    seam.poll_scene = Slink_Gen4Trade_ScenePoll;
    seam.post_save_begin = Slink_Gen4Trade_PostSaveBegin;
    seam.post_save_poll = Slink_Gen4Trade_PostSavePoll;
    seam.decode_read_u32 = Slink_Gen4Trade_Decode;
    seam.verify = Slink_Gen4Trade_Verify;
    seam.frame = Slink_Gen4Trade_Frame;
    return Slink_NDS_Trade_Bind(st, &seam, witness, stage, save_timeout_frames);
}

void Slink_NDS_Trade_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m)
{
    if (!Slink_Gen4Trade_State(st) || m == NULL) return;
    st->trade.caps = SLINK_GEN4_TRADE_CAPABILITIES;
    Slink_Gen4TradePolicy_Service(&st->trade.policy, m);
}

int Slink_NDS_Trade_CommitEntered(SlinkGen4State *st, unsigned slot)
{
    /* An unarmed policy is the ordinary native NPC trade, not our authority. */
    if (st != NULL && st->magic == SLINK_GEN4_STATE_MAGIC && st->trade.layout != 0
        && !Slink_Gen4Trade_State(st)) return 0; /* claimed but stale/corrupt is not ordinary NPC authority */
    if (!Slink_Gen4Trade_State(st)) return 1;
    return Slink_Gen4Trade_CommitEntered(&st->trade.policy, slot);
}

int Slink_NDS_Trade_Commit(SlinkGen4State *st, unsigned slot)
{
    if (st != NULL && st->magic == SLINK_GEN4_STATE_MAGIC && st->trade.layout != 0
        && !Slink_Gen4Trade_State(st)) return 0;
    if (!Slink_Gen4Trade_State(st)) return 1;
    return Slink_Gen4Trade_Commit(&st->trade.policy, slot);
}
