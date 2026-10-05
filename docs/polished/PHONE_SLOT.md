# PHONE-SLOT — the SLink entry inside the Pokégear Phone card, as a native-looking contact

**Design doc only.** Owner ruling 2026-10-04: *"the SLink entry lives INSIDE the POKEGEAR's PHONE
CARD as a native-looking contact; must feel vanilla."* This supersedes the card-slot idea in
`POKEGEAR_SLOT.md`, whose coordinator note already recorded that a 5th card is **not** viable (the
icon black bar is only 8 columns wide, so a column-8 icon needs the bar widened).

Marked **VERIFIED** (cited to a line I read), **INFERRED**, or **UNVERIFIED**; line numbers from
`grep -n`, never estimated. Sym addresses read from
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym`; **none guessed**.

**Headline: the contact list is a 40-bit flag array, not a table — so "add a contact" is not an
append.** A contact is a bit in `wPhoneList` (`01:dc8c`–`01:dc91`, exactly five bytes), and its
*metadata* (class, number, map, and up to two timed script pointers) lives in a struct that a
**script** supplies at the moment it calls `AddPhoneNumber`. Adding SLink is therefore a **script
pointer choice plus one intercept**, not a data edit.

---

## 1. How the Phone card builds its list

### 1.1 The list is a flag array (VERIFIED)

`ram/wramx.asm:1304-1305`:

```
wPhoneList:: flag_array NUM_PHONE_CONTACTS
wPhoneListEnd::
```

Sym: **`wPhoneList` `01:DC8C`**, **`wPhoneListEnd` `01:DC91`** — a **5-byte (40-bit) flag array**.

The list is never walked as rows. `engine/pokegear/phone.asm:295-297`
(`PokegearPhone_CountSetBits`) loads `wPhoneList` and the length `wPhoneListEnd - wPhoneList` and
falls into `CountSetBits`; `PokegearPhone_GetCellNumberFromE` (`:278-293`) then advances cell numbers
one **set bit** at a time via `CheckCellNum` (`:283`, `:287`). So **n-th visible row = n-th set bit**,
and there is no per-row record to extend.

### 1.2 Contacts are added at runtime by script (VERIFIED)

`engine/phone/phone.asm:11-25`:

```
AddPhoneNumber::
; Adds phone number c to the contact list. Returns carry if already present.
	call CheckCellNum
	ret c
	ld b, SET_FLAG
	jr DoAddOrDelPhoneNumber
```

and `PhoneFlagAction` (`:1-9`) does `dec c / ld hl, wPhoneList / predef FlagPredef`. **The only two
callers are scripts:** `engine/overworld/scripting.asm:733` and `:2016`, both `farcall
AddPhoneNumber`. `DelCellNum` (`:18`) is the delete half, and `CheckPhoneCall` (`:37`) is unrelated.

### 1.3 The per-contact metadata struct (VERIFIED)

`constants/phone_constants.asm:63-72`:

```
DEF PHONE_CONTACT_TRAINER_CLASS  rb
DEF PHONE_CONTACT_TRAINER_NUMBER rb
DEF PHONE_CONTACT_MAP_GROUP      rb
DEF PHONE_CONTACT_MAP_NUMBER     rb
DEF PHONE_CONTACT_SCRIPT1_TIME   rb
DEF PHONE_CONTACT_SCRIPT1_BANK   rb
DEF PHONE_CONTACT_SCRIPT1_ADDR   rw
DEF PHONE_CONTACT_SCRIPT2_TIME   rb
```

(with `PHONE_CONTACT_SCRIPT2_BANK` / `_ADDR` following at `:71-72`, per `HOOKS.md` §3.4). The base
address is carried in `wCallerContact` (same HOOKS row).

**So a contact is: a bit in `wPhoneList`, plus a 10-or-so-byte struct that supplies a caller class,
a caller number, a map, and up to two (time-gated) script pointers.** `NUM_PHONE_CONTACTS` is
`phone_constants.asm:41` `DEF NUM_PHONE_CONTACTS EQU const_value - 1`; the 5-byte array bounds it
at 40.

### 1.4 Is there a free slot?

**There is no free *data* slot — the array is a full-width bitfield and bits are assigned
dynamically.** But **no array growth is needed**: one of the 40 bits is claimed by SLink exactly the
way a native contact's bit is claimed. Whether bit 40−1 is unused by the shipped game is
**UNVERIFIED** — I did not enumerate which bits the shipped scripts set.

## 2. How a contact selection invokes its script, and where SLink intercepts

### 2.1 The call path (VERIFIED)

```
PokegearPhone_Init                     24:4995   (phone.asm)
  -> PokegearPhoneContactSubmenu       24:4b77   (phone.asm:299)
       call PokegearPhone_GetCellNumber          (:300)
       call CheckCanDeletePhoneNumber           (:301)
       -> .CallDeleteCancelJumptable / .CallDeleteCancelStrings   (:306-307)
       -> .CallCancelJumptable      / .CallCancelStrings           (:311-312)
  -> .Call                                      (:416, jumptable :454-455)
  -> PokegearPhone_MakePhoneCall     24:4a1c   (phone.asm:81)
       call MakePhoneCallFromPokegear           (:101)
                                  24:4118
```

Sym (VERIFIED, read from the `.sym`): `PokegearPhone_Init` **`24:4995`**,
`PokegearPhoneContactSubmenu` **`24:4B77`**, `PokegearPhone_MakePhoneCall` **`24:4A1C`**,
`MakePhoneCallFromPokegear` **`24:4118`**.

Supporting state: `wPokegearPhoneCursorPosition` **`00:C51D`**,
`wPokegearPhoneScrollPosition` **`00:C51E`** (phone.asm:265-268 sets scroll from the cursor), and
`wNumSetBits` **`01:D26B`** (the live row count).

### 2.2 The two intercept options (HYPOTHESIS)

| option | what it changes | size / shape | risk |
|---|---|---|---|
| **I1 — pointer-choice (recommended)** | The SLink contact's struct carries **SLink's own script pointer** instead of a caller's, so A runs the overlay's dispatcher directly. `MakePhoneCallFromPokegear` is never touched. | **data only** — no ROM code change at all; the overlay supplies the script | The overlay must provide a bank the engine can reach; **UNVERIFIED** that a bank-`$7E`/`$7F` script is callable as a normal contact script |
| **I2 — gate intercept** | At `PokegearPhone_MakePhoneCall` (`24:4a1c`), if the selected caller is the SLink class/number, jump to the panel instead of calling | **same-size rewrite** inside bank `$24` (the routine is already there) | Touches a **shipped engine routine**, so the overlay's UPS hunk must match the clean bytes exactly; higher coupling |

**I1 is the better shape for "feel vanilla"**: the player sees an ordinary contact row, and the
native path (`:81` → `:101` → `24:4118`) runs unmodified for every other contact, so there is no way
for the overlay to perturb real calls.

## 3. How the contact label is drawn

**VERIFIED:** the Phone card's title text is `PokegearText_WhomToCall`, sym **`24:5276`**, referenced
at `phone.asm:15`, `:119`, `:139`, `:394`, `:409`. The Call/Delete/Cancel labels are local strings:
`phone.asm:446` `text "Call"`, consumed via `.CallDeleteCancelStrings` (`:446`) and
`.CallCancelStrings` (`:312`).

**UNVERIFIED:** the per-contact *name* rendering path, the charmap/font used for it, and how a name
is chosen for a contact that is not tied to a trainer class. `PokegearText_WhomToCall` is the card's
own heading, not the row label — I did not trace the row text. **This is the one gap that most
directly affects "feel vanilla" and it must be closed before building.**

What makes it look native (INFERRED, from the two call-submenu strings and the flag-array model):
the row must appear in the **same place any contact appears** — i.e. its bit set at the same point
in the list build, so it takes its natural position among trainer contacts; it must have **no**
ringing animation and **no** call cost, because the native path (`MakePhoneCallFromPokegear`) is
never entered under I1; and the selection must use the **existing** cursor/scroll (`00:C51D` /
`00:C51E`), which it will automatically if the row is a real set bit.

## 4. Interaction with the existing SLink phone-call feature

**They compose, and this ruling improves the earlier plan.**

`PHONE.md`'s coordinator correction (its final section) re-counted
`constants/phone_constants.asm:45-58`: `SPECIALCALL_NONE` = 0, and the **native row at id 9 is
`SPECIALCALL_YELLOWFOREST`, not `LYRASEGG`**; `NUM_SPECIALCALLS` = **12**, so
`SPECIALCALL_SLINK EQU 9` would alias a native row and the first free id is **13**. The correction
also re-read the ROM: `CheckSpecialPhoneCall` flat `0x900BC` = `fa 6b dc a7 28 33`, and
`SpecialPhoneCallList` flat `0x90506` = `09 41 04 62 6c 53`.

That was the *special-call* list (an overlay-registered contact). **This card's ruling moves SLink
to the ordinary contact list instead** (`wPhoneList`), which is a different mechanism:
* **No aliasing risk.** The 40-bit `wPhoneList` is not the `SpecialPhoneCallList` table, so the
  id-9 collision disappears entirely. The `:13` rule remains correct for the special-call route but
  is **no longer on the critical path**.
* **Do not do both.** Keeping a special-call row *and* a contact row would put SLink in the list
  twice. The owner's framing — *"calls come from SLink contacts too"* — reads as: **one** SLink
  contact, and ringing is the native behaviour of a normal contact. I would drop the special-call
  registration and keep the contact.

## 5. Hook change set (HYPOTHESIS — addresses read, bytes not)

| # | change | where | kind |
|---|---|---|---|
| H1 | give the SLink contact a struct whose script pointer targets the overlay dispatcher | overlay data (`bank $7E`/`$7F`) | **data only** |
| H2 | set the SLink bit in `wPhoneList` when the companion advertises the capability | overlay, near the existing phone code | **data only** |
| H3 | *(only if I1 is rejected)* gate at `PokegearPhone_MakePhoneCall` | **`24:4a1c`** (sym) | same-size rewrite, bank `$24` |
| H4 | the row label string | overlay charmap/text | data |

**Nothing here needs a change to `home/`-shared routines** — that is the main win over the
Start-menu route. `PokegearPhoneContactSubmenu` (`24:4b77`), `PokegearPhone_Init` (`24:4995`) and
`MakePhoneCallFromPokegear` (`24:4118`) are all **`engine/pokegear/phone.asm`**, title-local.

**ROM free space: UNVERIFIED.** Under I1 the only code is the overlay's dispatcher, which the existing
overlay budget would cover; I did not re-derive the `$7E`/`$7F` free-space figures here (they live in
`HOOKS.md`) and I am not asserting a number.

## 6. The single live check

A **read-only scripted open of the Phone card**, on a stock Polished overlay plus the SLink bit set:

> Open the Pokégear → Phone card with the SLink contact present. Confirm the list scrolls, the SLink
> row renders **with the same font, spacing and cursor behaviour as every other contact**, the cursor
> reaches it at the expected `wNumSetBits`-derived position, B backs out without ringing, and A
> launches the panel **without** `MakePhoneCallFromPokegear` (`24:4118`) being entered.

That single pass decides "feel native" — the only claim here that is perceptual rather than
structural. It also falsifies I1 immediately: if A still rings, the contact's script pointer is not
being taken from our struct.

## 7. UNVERIFIED inventory

| item | how to settle |
|---|---|
| **the per-contact row-label rendering path** (font, charmap, name selection) | trace the row draw in `engine/pokegear/phone.asm`; the biggest gap for "feel vanilla" |
| whether any of the 40 `wPhoneList` bits is unused in the shipped game | enumerate the `AddPhoneNumber` call sites' contact ids |
| whether an overlay-bank script is reachable as a normal contact script | check the engine's script-call path for a bank limit |
| `wCallerContact`'s address and how the struct base is carried | read `constants/phone_constants.asm:71-72` and its runtime setter |
| ROM free space in `$7E`/`$7F` | re-derive from `HOOKS.md` rather than trusting me |
| whether `MakePhoneCallFromPokegear` validates the caller class/number (would affect I2) | read `24:4118`'s body |
| `CheckCanDeletePhoneNumber`'s rule — it decides whether SLink shows "Delete" | read the routine |


---

## Coordinator verification and the row-label answer (2026-10-04)

Re-read: `wPhoneList` is `flag_array NUM_PHONE_CONTACTS` (`ram/wramx.asm:1304-1305`, sym `01:DC8C..01:DC91`) and
`AddPhoneNumber` only sets a bit (`engine/phone/phone.asm:11-25`): confirmed. **The OMP's biggest gap (the row label) is
answerable from the source:** `PokegearPhone_UpdateDisplayList` (`engine/pokegear/phone.asm:198-230`, 4 rows, `hlcoord 2, 4`,
2 tile rows per entry) calls `GetCallerClassAndName` (`engine/phone/phone.asm:376-428`) for each set bit: a contact whose
trainer-class byte is non-zero prints `<TrainerName>:` plus the class name from the trainer tables; class 0 means a
**non-trainer contact** and prints the string at `NonTrainerCallerNames` (`24:42de`, `data/phone/non_trainer_names.asm`:
one `dw` per `PHONECONTACT_*` id, `assert_table_length NUM_NONTRAINER_PHONECONTACTS + 1`; ids 0-6 = empty, Mom, Bike Shop,
Bill, Elm, Lyra, Buena). So an SLink contact must be a **non-trainer contact with its own name string**, and that string is
read by `rst PlaceString` with bank `$24` mapped (the `ld hl, NonTrainerCallerNames / add hl,bc / add hl,bc` sequence at
`phone.asm:410-414` has no bank switch). **Bank `$24` has ZERO free bytes** (`data/polished/free_space.txt`: only banks 80-100
and 125-127 have any), so the table cannot grow in place and a new string cannot be added in bank `$24`.
Feasible hypothesis (not built, UNVERIFIED): replace the table lookup inside `.NotTrainer` (14 bytes, same-size rewrite) with a
call to a ROM0 bridge (SUPERSEDED 2026-10-04: ROM0's 351 free bytes is a COUNT, not an address; the real gaps are `$0089-$00FF` and
`$3F34-$3FFF` after the phone bridge -- `docs/polished/HOOKS.md:812-813`) that, for the SLink contact id, copies the label from the `$7E`
service into a WRAM string buffer and returns `de` pointing at it (all other ids fall through to the native table lookup);
`PlaceString` then reads from WRAM, so no bank switch happens mid-draw. The native row for every other contact is unchanged.
Also open: a trainer-class-0 contact must not be dropped by `CheckCanDeletePhoneNumber` rules (does it offer Delete? an
SLink contact should refuse Delete), the contact-id constant range (`PHONECONTACT_*` has no free id beyond Buena unless the
constant table grows: it is a `const` list used by `PhoneContacts` rows, `data/phone/phone_contacts.asm`), and the I1 dispatch
(script pointer into the overlay bank) which needs the same `PhoneContacts` row (a data row in bank `$24`: ALSO full).
These two bank-`$24` data needs (a label and a `PhoneContacts` row) mean I1 as written ("data only, zero ROM code change")
is NOT achievable without freeing or bypassing space in bank `$24`; the ROM0-bridge route above is the likely shape.


## Stage 1 implementation (2026-10-04, append-only)

Built and live-checked on the overlay `34942315bb3e62189a56dabbcb9cef6dd3e9a9f5` (UPS 262 B). The final shape is
neither I1 nor I2. The contact is **virtual**: there is no `wPhoneList` bit, no `PhoneContacts` row and nothing in the save.
The Phone card's own list walk is told that contact id `NUM_PHONE_CONTACTS + 1` (= 38) exists. That id sorts after every
native id, so the SLink row is always the last row. Five same-size `call` operand rewrites in bank `$24` route to ROM0
bridges (`patch/polished/src/slink.asm`, fixed `ROM0[$3F34]`). Each bridge falls through to the native callee for every id
except 38:

| flat | routine | old bytes | new bytes | why |
|---|---|---|---|---|
| `0x90B5E` | `PokegearPhone_GetCellNumberFromE` | `cd 6f 4b` (`call PokegearPhone_CountSetBits`) | `cd 34 3f` (`SlinkPhone_CountSetBits`) | native count + 1, `wNumSetBits` too |
| `0x90B66` | same walk | `cd 1f 40` (`call CheckCellNum`) | `cd 3c 3f` (`SlinkPhone_CheckCellNum`) | id 38 reads as present, so the walk stops on it |
| `0x90B0E` | `PokegearPhone_UpdateDisplayList` | `cd ff 41` (`call GetCallerClassAndName`) | `cd 45 3f` (`SlinkPhone_CallerName`) | label `SLink:` / `   Soul Link` from ROM0 (the `.bill`/`.elm` string shape), never the out-of-table `PhoneContacts[38]` |
| `0x90B7A` | `PokegearPhoneContactSubmenu` | `cd 9e 42` (`call CheckCanDeletePhoneNumber`) | `cd 52 3f` (`SlinkPhone_CanDelete`) | c = 0, so Call/Cancel only (Mom/Elm style), no Delete |
| `0x90A1C` | `PokegearPhone_MakePhoneCall` | `cd da 25` (`call GetMapPhoneService`) | `cd 5b 3f` (`SlinkPhone_CallGate`) | "Call" on id 38 drops the return, prints `SLink is linked.` (prompt), then goes back to `POKEGEARSTATE_PHONEJOYPAD` + `PokegearText_WhomToCall`, the same exit as the native out-of-service path. It never rings. |

The ROM0 strings are read with bank `$24` mapped (ROM0 is always visible), so no WRAM buffer is needed. Every other
contact, every call path and the rest of bank `$24` are byte-identical. `verify_overlay` checks each hook's opcode and
both operands (`phone_hook_spans`), and it checks that the ROM0 span was `$FF` in the clean ROM. The UPR patch-0020
signature bytes (`$0070`, `$0DA8`, `$7E:4000`+16) are unchanged. ABI stays 3. No capability bit is added, because
the host takes no part in Stage 1.

**Save safety (why removing the overlay leaves a valid save):** no overlay byte writes `wPhoneList` (the
`test_polished_phone_entry.py` source check), so the save only ever holds native contact bits. The native random-caller
and `AddPhoneNumber`/`DelCellNum` paths never see id 38.

**Native quirk seen live, not caused by the overlay:** `wNumSetBits` is a union with `wNamedObjectIndex`
(`ram/wramx.asm:718-721`), and the trainer branch of `GetCallerClassAndName` writes the trainer class there. So when the
last row drawn is a trainer, `wNumSetBits` holds that class (33 for Wade) until the next walk. The native scroll check
(`phone.asm:178`) reads it. With the SLink row last, that row is usually the overlay's, which resets the count.

UNPROVEN: the text `SLink is linked.` is fixed. The core mailbox publishes no host/link status, so the text does not
reflect whether a host is attached (Stage 2 panel). A `wPhoneList` that is corrupt (bits 38-40 set) would make the walk
overrun, exactly as it would natively.
