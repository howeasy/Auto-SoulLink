"""RF-2: prepare_pair audits actual output bytes beyond its rule/site proof.

ROM controls use the pinned sources and the design's scratch UPR outputs; only the external
Java invocation is replaced. Missing private ROMs skip by name, never with synthetic success.
"""
import hashlib
from pathlib import Path

import pytest

from server import upr_gen3_write_domain as W, upr_pipeline as P, upr_settings as U
from tests.unit.test_upr_gen3_write_domain import _clean_path, _log_spec, _manager_output


def _prepare(tmp_path, monkeypatch, first_title, *, widest_movesets=False):
    titles = {"a": first_title, "b": "leafgreen" if first_title == "firered" else "firered"}
    sources = {p: str(_clean_path(title)) for p, title in titles.items()}
    outputs = {title: _manager_output(title, "allowed") for title in titles.values()}
    spec = _log_spec(Path(f"{outputs[first_title]}.log"))
    settings = tmp_path / "allowed.rnqs"
    settings.write_bytes(U.build_spec(spec, family=U.FAMILY_FRLG))
    raw_outputs = {title: path.read_bytes() for title, path in outputs.items()}
    if widest_movesets:
        widest = _manager_output(first_title, "widest").read_bytes()
        raw = bytearray(raw_outputs[first_title])
        for start, end in W._ranges(W.load_model()["titles"][first_title]["domains"]["movesets"]):
            raw[start:end] = widest[start:end]
        assert bytes(raw) != raw_outputs[first_title]
        raw_outputs[first_title] = bytes(raw)
        # SYNTH: retain the allowed output except for the widest artifact's learnsets. This
        # clears the older check, so only the newly wired write-domain audit can refuse it.
        probe = tmp_path / "unverified_movesets.gba"
        probe.write_bytes(raw)
        P._check_content_gen3(sources["a"], str(probe))

    def randomize(_jar, _settings, source, output, *, java):
        title = P.gen3_title(Path(source).read_bytes())
        raw = raw_outputs[title]
        Path(output).write_bytes(raw)
        log = Path(f"{outputs[title]}.log").read_text(encoding="utf-8-sig")
        settings_string = next(line.split(": ", 1)[1] for line in log.splitlines()
                               if line.startswith("Settings String:"))
        return {"output": output, "settings_string": settings_string,
                "sha1": hashlib.sha1(raw).hexdigest(), "seed": 101 if title == "firered" else 102,
                "version": "4.6.1-slink3"}

    monkeypatch.setattr(P, "randomize", randomize)
    return P.prepare_pair("external-process-replaced.jar", str(settings), sources, str(tmp_path / "out"))


@pytest.mark.parametrize("title", ("firered", "leafgreen"))
def test_prepare_pair_refuses_widest_movesets_hidden_behind_allowed_settings(tmp_path, monkeypatch, title):
    with pytest.raises(P.UprPipelineError, match="outside the write domain.*movesets"):
        _prepare(tmp_path, monkeypatch, title, widest_movesets=True)


def test_prepare_pair_retains_the_write_domain_receipt_for_both_titles(tmp_path, monkeypatch):
    result = _prepare(tmp_path, monkeypatch, "firered")
    for row in result["players"].values():
        assert row["sites_intact"] is True
        assert row["write_domain"]["changed"] > 1000
        assert row["write_domain"]["domains"] == sorted(W.domains_for_spec(row["spec"]))
