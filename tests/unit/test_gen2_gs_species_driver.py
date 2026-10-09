"""MODEL: exercise the species scenario's setup seam and native input driver, not a live receipt.

The cartridge/UI is DuoSim; duplicate and link commands come from the real Gen 2
adapter/state machine. The setup seam selects the next simulated native battle;
it never supplies a capture or a server command. Existing Crystal controls remain
in test_gen2_duo_driver.py.
"""
from __future__ import annotations

import pytest

from server.adapters.gen2_gsc import Gen2GSCAdapter
from server.state import SoulLinkState
from tests.unit.test_gen2_duo_driver import KEY, ClauseSim, run_driver, tag_json


class GsSpeciesSim(ClauseSim):
    def __init__(self, lua, title="gold", *, state, suppress_prompt=False, dupe_species=16, **kw):
        self.state = state
        self.suppress_prompt = suppress_prompt
        self.setup_species = []
        self.setup_starters = 0
        self.selected_species = None
        self.commands = []
        super().__init__(lua, title, dupe=dupe_species, foes=((19, KEY[:-2] + "13"),), **kw)

    def next_foe(self):
        species = self.selected_species if self.selected_species is not None else 19
        self.selected_species = None
        return species, KEY[:-2] + f"{species:02X}"

    def deliver(self, commands):
        for cmd in commands:
            self.commands.append(cmd)
            if self.suppress_prompt and cmd["cmd"] == "gui_prompt":
                continue
            self.command(**cmd)

    def battle_choice(self, species):
        # The simulated engine has already populated wEnemyMonSpecies; production
        # uses its first in-battle tick for this same public server boundary.
        self.state.check_dupe_on_encounter("b", "route_29", species)
        self.deliver(self.state.handle_event("b", {"event": "tick"}))
        return super().battle_choice(species)

    def on_caught(self, species, key):
        self.deliver(self.state.handle_event("b", {
            "event": "capture", "key": key, "species_id": species,
            "area_id": "route_29", "nickname": "RATTATA", "level": 3,
        }))

    def select(self, species):
        self.setup_species.append(species)
        self.selected_species = species

    def condition(self):
        self.setup_starters += 1


def run_gs_species(tmp_path, *, title="gold", harden=True, helper=True,
                   species_lock=True, suppress_prompt=False, pending_species=16,
                   disclosure=True, condition_ok=True):
    state = SoulLinkState(data_dir=str(tmp_path / "state"), species_lock=species_lock,
                          adapter=Gen2GSCAdapter(title=title))
    state.pokeballs_obtained = {"a": True, "b": True}
    state.handle_event("a", {
        "event": "capture", "key": KEY[:-2] + f"{pending_species:02X}", "species_id": pending_species,
        "area_id": "route_29", "nickname": "PIDGEY", "level": 3,
    })

    def setup(sim, glob):
        # Wrap only S.run's public harness argument, leaving the scenario body,
        # native input route and its original verdict intact.
        glob.MODEL_GS_HARDEN, glob.MODEL_GS_HELPER = harden, helper
        glob.MODEL_DISCLOSURE, glob.MODEL_CONDITION_OK = disclosure, condition_ok
        glob.MODEL_SELECT, glob.MODEL_CONDITION = sim.select, sim.condition
        sim.lua.execute(r'''
local original_dofile = dofile
function dofile(path)
    local value = original_dofile(path)
    if path:match("scenario_gen2_species_clause%.lua$") then
        local run = value.run
        function value.run(h)
            h.gs_harden = MODEL_GS_HARDEN
            h.gs_setup = nil
            if MODEL_GS_HELPER then
                h.gs_setup = {
                    condition_starter=function()
                        MODEL_CONDITION()
                        return MODEL_CONDITION_OK, "model setup refused"
                    end,
                    encounter=function(species)
                        MODEL_SELECT(species)
                        return h.encounter()
                    end,
                }
            end
            -- Disclosure rows are MODEL setup evidence, not a physical claim.
            if h.gs_harden and h.gs_setup and MODEL_DISCLOSURE then
                h.jlog("SYNTH_SETUP", {purpose="model_starter", bytes_before="00", bytes_after="01"})
            end
            return run(h)
        end
    end
    return value
end
''')
        # The parent composition root owns DUO_GEN2.gs_harden. Inject it in this
        # MODEL's JSON encoder rather than replacing any observation/oracle row.
        sim.lua.execute(r'''
local original_dofile = dofile
function dofile(path)
    local value = original_dofile(path)
    if path:match("json_codec%.lua$") then
        local encode = value.encode
        function value.encode(row)
            if type(row) == "table" and row.scenario == "species_clause" then
                row.gs_harden = MODEL_GS_HARDEN or nil
            end
            return encode(row)
        end
    end
    return value
end
''')

    return run_driver(tmp_path, title=title, scenario="species_clause", player="b",
                      go_text=f"GO\nA_PENDING species={pending_species}\n", sim_class=GsSpeciesSim,
                      state=state, suppress_prompt=suppress_prompt, dupe_species=pending_species, setup=setup)


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gs_duplicate_runs_then_native_unlike_family_catch_links_and_saves(tmp_path, title):
    lines, sim, _ = run_gs_species(tmp_path, title=title)
    assert lines[-1].startswith("RESULT: PASS"), "\n".join(lines[-40:])
    assert sim.setup_starters == 1 and sim.setup_species == [16, 19]
    assert sim.battles == [16, 19] and sim.caught
    assert any(c["cmd"] == "gui_prompt" and "Dupes clause:" in c["text"] for c in sim.commands)
    assert tag_json(lines, "ENGINE_CAPTURE")["species_id"] == 19
    receipt = tag_json(lines, "RECEIPT")
    assert receipt["schema"] == "gen2-duo-species-clause-v1"
    assert (receipt["path"], receipt["rerolls"]) == ("reroll_observed", 1)
    assert receipt["input_mode"] == "SYNTH_setup_then_normal_buttons"
    assert receipt["harness_write_scopes"] == receipt["synth_disclosure"]
    assert tag_json(lines, "SAVE_WITNESS")["flushed_matches"] is True


@pytest.mark.parametrize("red", ["disabled_rule", "suppressed_prompt"])
def test_gs_missing_real_duplicate_prompt_stops_before_catch(tmp_path, red):
    lines, sim, _ = run_gs_species(tmp_path, species_lock=red != "disabled_rule",
                                 suppress_prompt=red == "suppressed_prompt")
    assert lines[-1] == "RESULT: FAIL (no dupes-clause prompt for species 16 (A's))"
    assert sim.setup_species == [16] and sim.battles == [16] and not sim.caught
    assert not any(line.startswith(("REROLL ", "ENGINE_CAPTURE ", "RECEIPT ")) for line in lines)
    prompts = [c for c in sim.commands if c["cmd"] == "gui_prompt"]
    assert bool(prompts) == (red == "suppressed_prompt")


def test_gs_missing_helper_fails_before_any_native_encounter(tmp_path):
    lines, sim, _ = run_gs_species(tmp_path, helper=False)
    assert lines[-1] == "RESULT: FAIL (G/S setup helper missing)"
    assert sim.battles == [] and not sim.caught


def test_gs_non_pidgey_pending_selects_native_pidgey_after_reroll(tmp_path):
    lines, sim, _ = run_gs_species(tmp_path, pending_species=19)
    assert lines[-1].startswith("RESULT: PASS"), "\n".join(lines[-40:])
    assert sim.setup_species == [19, 16] and sim.battles == [19, 16]
    assert tag_json(lines, "ENGINE_CAPTURE")["species_id"] == 16


def test_gs_failed_starter_setup_does_not_enter_hunt(tmp_path):
    lines, sim, _ = run_gs_species(tmp_path, condition_ok=False)
    assert lines[-1] == "RESULT: FAIL (G/S starter setup: model setup refused)"
    assert sim.setup_starters == 1 and sim.battles == [] and not sim.caught


def test_gs_receipt_refuses_undisclosed_setup(tmp_path):
    lines, sim, _ = run_gs_species(tmp_path, disclosure=False)
    assert lines[-1] == "RESULT: FAIL (missing G/S SYNTH_SETUP disclosure)"
    assert sim.battles == [16, 19] and sim.caught
    assert not any(line.startswith("RECEIPT ") for line in lines)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_without_gs_guard_original_nonduplicate_hunt_is_unchanged(tmp_path, title):
    lines, sim, _ = run_gs_species(tmp_path, title=title, harden=False)
    assert lines[-1].startswith("RESULT: PASS"), "\n".join(lines[-30:])
    assert sim.setup_starters == 0 and sim.setup_species == [] and sim.battles == [19]
    receipt = tag_json(lines, "RECEIPT")
    assert (receipt["path"], receipt["rerolls"]) == ("reroll_unobserved", 0)
    assert receipt["input_mode"] == "normal_buttons" and receipt["harness_write_scopes"] == []
    assert "synth_disclosure" not in receipt
