"""pol-panel live runner: the Polished panel driver on a private lane, ROM staged from the COMMITTED ups.

Deliberate differences from run_phone.py:
  * POL_LANE is this lane (F:/slink-work/lanes/pol-panel2), never pol-phone's;
  * the ROM is NOT taken from the shared cache. It is the committed patch/dist/SLink-Polished.ups
    applied to the pinned release ROM, and its sha1 is checked against
    data/polished/overlay_provenance.json -- the same pin build_polished_companion.py enforces.
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys

LANE_ROOT = pathlib.Path("F:/slink-work/lanes/pol-panel2")
os.environ["POL_LANE"] = str(LANE_ROOT)
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))
sys.path.insert(0, str(REPO / "tools" / "polished_live"))

import harness as H  # noqa: E402
from make_ups import ups_apply  # noqa: E402

H.SYMBOLS = H.SYMBOLS + (
    # the panel's own symbols
    "SlinkPanel", "SlinkPanel.page", "SlinkPanel.ready", "SlinkPanel.close", "SlinkPanel.WaitForStage",
    "SlinkPanelFallback", "SlinkPanelEnd", "wSlinkPanelText", "wSlinkMailboxEnd",
    # the Phone card's, as in run_phone.py
    "wPhoneList", "wNumSetBits", "wCurCaller", "wPokegearPhoneCursorPosition", "wPokegearPhoneScrollPosition",
    "wPokegearPhoneSelectedPerson", "PokegearPhoneContactSubmenu", "MakePhoneCallFromPokegear",
    "SlinkPhone_CallGate",
)

RELEASE = pathlib.Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
UPS = REPO / "patch" / "dist" / "SLink-Polished.ups"
PROV = REPO / "data" / "polished" / "overlay_provenance.json"
FIXTURE_SRC = pathlib.Path(os.environ.get("POL_FIXTURE",
    "F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM"))


def stage_from_committed_ups() -> str:
    data = ups_apply(RELEASE.read_bytes(), UPS.read_bytes())
    sha1 = hashlib.sha1(data).hexdigest()
    want = json.loads(PROV.read_text(encoding="utf-8"))["output"]["sha1"]
    if sha1 != want:
        raise SystemExit(f"committed ups produced {sha1}, provenance pins {want}")
    H.ROM.parent.mkdir(parents=True, exist_ok=True)
    H.ROM.write_bytes(data)
    print(f"[pol-panel] staged {H.ROM} from the committed ups: sha1 {sha1}", flush=True)
    return sha1


def main() -> int:
    sha1 = stage_from_committed_ups()
    H.SRAM.mkdir(parents=True, exist_ok=True)
    # Every stale save, exactly as run_phone_ab.py:45 (hygiene only; the stall's real cause was the missing copy below).
    for stale in H.SRAM.glob("*.SaveRAM*"):
        stale.unlink()
    H.FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE_SRC, H.FIXTURE)
    # the save BizHawk actually reads: without this copy the game boots as a NEW GAME (map 0:0, saved 0) and the
    # driver aborts at the boot gate; run_phone_ab.py does the same copy
    shutil.copyfile(H.FIXTURE, H.SRAM / H.SAVE_NAME)
    print(f"[pol-panel] SYNTH fixture {H.FIXTURE} <- {FIXTURE_SRC}", flush=True)
    run = LANE_ROOT / "run"
    text, pid = H.launch("tools/polished_live/pol_panel.lua", run, {}, 900)
    print(f"rom {sha1} pid {pid}")
    print(text[-8000:])
    return 0 if "RESULT: PASS" in text else 1


if __name__ == "__main__":
    sys.exit(main())
