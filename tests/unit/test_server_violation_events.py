"""The events log's `violation` / `reroll` rows come from the capture reply's gui_prompt text.

f1d79c72 shortened every rejection toast ("... -- catch again!" -> "[x] ...") but the server still keyed
`violation` on "catch again", so no clause rejection has reached events.json since. First seen on the
G<->S gen2_type_clause duo (2026-09-23): server.log "Type clause: shared Normal ... rejecting capture",
events.json without a violation row. The texts below are server/state.py's own prompts.
"""
from server.server import prompt_event_type


def test_every_capture_rejection_prompt_is_a_violation():
    for text in ("[x] Type clause: shared Normal",          # state.py clause rejection ("[x] " + violation)
                 "[x] Gender clause: both are ♂",
                 "[x] Species clause: both are Pidgey",
                 "[x] Species clause: Pidgey & Pidgeotto same family - retry",   # bonus-pair rejection
                 "[x] Dup Pidgey"):                           # species-clause capture rejection
        assert prompt_event_type(text) == "violation", text


def test_a_dupes_reroll_is_a_reroll_not_a_violation():
    assert prompt_event_type("Dupes clause: Rattata -- reroll!") == "reroll"


def test_other_toasts_log_nothing():
    for text in ("[x] DZ: Route 29", "[x] Linked: Route 29", "[x] 2nd: Route 29", "[x] PC empty",
                 "[x] Dead in party -> grave", "[x] WRONG SAVE: slot A"):
        assert prompt_event_type(text) is None, text
