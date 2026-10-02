# New-game route for the starter producer (V4/H6), SOURCE research (2026-10-02)

**Source:** OMP cx-d4cf0982, at the PINNED pret tree `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ `ad7a3afa`.

**Status:** SOURCE only. Nothing here has been run.

**Why a new game:** the owner saves already hold a starter. The first settled view learns it silently (`poll_events.lua`), so the starter acquisition can only be receipted from a new game.

## Chain

1. **Boot.** `src/main.c:83` registers the main menu (OVY_36) directly. There is no PRESS START gate.
   - Soft-reset chord: START+SELECT+L+R (`:97-100`).
2. **Main menu.**
   - A confirms (`main_menu.c:281`); NEW GAME is a menu row (`:176-177`, `:1430`, `:1487-1490`).
   - The default highlighted row is UNVERIFIED.
3. **New Game app.** No input (`overlay_36.c:93-115`). It wipes the save, sets the start position, money 3000 and flag 960.
4. **Oak's speech.** ONE app, `gApplication_OakSpeech` OVY_53 (`unk_02091564.c:15`), with a 127-state machine (`oaks_speech.c:43-129`, dispatch `:1530-2146`).
   - Most text boxes take A. Two pages auto-advance (`:1639`, `:1675`, waitButtonMode 0; meaning inferred).
   - The tutorial and "understood?" are YES/NO menus.
   - Gender menu (`:1907-1927`): the cursor is preset to `lastChosenGender` (`:1922`, initial value UNVERIFIED). The confirm YES/NO defaults to option 0 (`:1953`).
   - **Never leave the gender non-binary:** the default name is then uninitialised (`naming_screen.c:664-665`).
   - **Name entry:** a child OverlayManager (`oaks_speech.c:2012`). Press OK with an EMPTY buffer and `NamingScreenApp_Exit` supplies a random default (`naming_screen.c:700-712`, `:707`). No typing is needed.
   - **No rival-name prompt** (fixed default, `oaks_speech.c:645`). **No clock/RTC prompt**; time of day is narration only (`:1795-1799`).
5. **After Oak.** One more app with no input (`overlay_36.c:117-139`). The trainer ID is set here (`:145`), so trainer ID ≠ 0 means "past Oak".
6. **Field start.** `MAP_NEW_BARK_PLAYER_HOUSE_2F`, x6 y6 dir1 warpId -1 (`location_backup.c:10-16`).
   - Bedroom script: ~~`scr_seq_0844_T20R0102.s`~~ **`scr_seq_0846_T20R0202.s`**; 0844/T20R0102 is Elm's lab 2F (map 62). See the corrections below. Lab: `scr_seq_0843_T20R0101.s`.
7. **Starter.** `ChooseStarter` at `scr_seq_0843_T20R0101.s:169`, guarded by `FLAG_GOT_STARTER` (`:167` check, `:170` set).
   - The cursor defaults to the first ball (`choose_starter.c:53`).
   - **A second menu follows** (the nickname question, `:174-186`).

## Poll signals

| Signal | Meaning |
|---|---|
| OverlayManager main slot = OVY_36 | menu, new game |
| OverlayManager main slot = OVY_53 | Oak's speech |
| Child slot occupied | name entry |
| Location mapId = player house 2F | in the field |
| `FLAG_GOT_STARTER` | the authoritative starter oracle |

## Open before a route card

- the pad buttons per `CHOOSE_STARTER_INPUT_*` (`choose_starter_app.c:35-59`, handler not read);
- the bedroom → street → Elm's lab trigger chain (forced movement vs input) and the lab map id;
- the main-menu default row; the initial `lastChosenGender`;
- hge script equality (the fork checkout lacks the script tree; the C side shows no intro override).

## Corrections and closures (OMP cx-4bc1e15f, coordinator-verified at `ad7a3afa`, 2026-10-02)

- **Maps** (`include/constants/maps.h:64-68`):
  - New Bark 60;
  - Elm's lab 1F 61 (`T20R0101`) and 2F 62 (`T20R0102`);
  - player house 1F 63 (`T20R0201`) and 2F 64 (`T20R0202`, the bedroom; script `scr_seq_0846_T20R0202.s`).
- **Main menu:** a blank save forces `selectedApp = APPOPTION_NEW_GAME` (`main_menu.c:1429-1431`), so no cursor move is needed. The drawn row is unverified; it matters only to a cursor-polling route.
- **Gender:** `lastChosenGender = 0` (MALE) at init (`oaks_speech.c:559`; `global.h:12`).
- **YES/NO:** the default is option 0 unless a template sets `initialCursorPos` (`yes_no_prompt.c:87-89`); the overrides on this path are not enumerated. Confirm and decline both play `SEQ_SE_DP_BUTTON9`, so assert on state, never on sound.
- **Starter input** (`choose_starter_app.c:1071-1103`):
  - A advances and confirms (one nav input, then two A presses, `:1077`); B backs out in CONFIRM only;
  - Left = clockwise, Right = counterclockwise; Left and Right are suppressed in CONFIRM.
  - The default ball initialiser is unread.
- **Lab:** stepping onto X 3/4/5 in lab 1F auto-walks the player (`GetPlayerCoords` + `ApplyMovement obj_player`, `scr_seq_0843_T20R0101.s` ~54-67), so the entry column matters.
- **Still open:**
  - the warp tiles: bedroom stairs (map 64) and lab door (map 60). Take them from the zone event data via the route tooling, never vision;
  - the T20R0202 bedroom script trigger chain;
  - the default ball.
