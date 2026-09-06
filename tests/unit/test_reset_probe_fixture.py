"""Fault-state content preservation, not physical restore/interlock evidence."""

import hashlib
import io
import zipfile

import pytest

from tools.rr.reset_probe_fixture import MALFORMED_USERDATA, failed_after_restore_copy


def state(*, userdata=None, version=b"Version 2.11.1\r\n", duplicate=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BizVersion.txt", version)
        archive.writestr("Core.bin", bytes(range(256)) * 8)
        archive.writestr("SyncSettings.json", b'{"o":{"SkipBios":true}}')
        archive.writestr("Framebuffer.bmp", b"opaque image bytes")
        if userdata is not None:
            archive.writestr("UserData.txt", userdata)
        if duplicate:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("Core.bin", b"must refuse")
    return output.getvalue()


@pytest.mark.parametrize("userdata", [None, b'{"o":{}}'])
def test_only_userdata_changes_and_core_bytes_are_identical(userdata):
    original = state(userdata=userdata)
    result, manifest = failed_after_restore_copy(original)
    repeated, repeated_manifest = failed_after_restore_copy(original)
    assert (repeated, repeated_manifest) == (result, manifest)
    with (
        zipfile.ZipFile(io.BytesIO(original)) as source,
        zipfile.ZipFile(io.BytesIO(result)) as fault,
    ):
        assert fault.read("UserData.txt") == MALFORMED_USERDATA
        for name in source.namelist():
            if name != "UserData.txt":
                assert fault.read(name) == source.read(name)
                assert (
                    hashlib.sha256(fault.read(name)).hexdigest()
                    == manifest["unchanged_member_sha256"][name]
                )
    assert manifest["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["output_sha256"] == hashlib.sha256(result).hexdigest()
    assert manifest["rom_or_busy_marker_verified"] is False
    assert manifest["emulator_executed"] is False and manifest["interlock_proved"] is False


def test_duplicate_members_are_not_silently_chosen():
    with pytest.raises(ValueError, match="duplicate"):
        failed_after_restore_copy(state(duplicate=True))


def test_wrong_host_version_is_refused():
    with pytest.raises(ValueError, match="2.11.1"):
        failed_after_restore_copy(state(version=b"Version 2.10\n"))


@pytest.mark.parametrize("source", [b"", b"not a zip", "not bytes"])
def test_invalid_input_never_becomes_a_loadable_probe(source):
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        failed_after_restore_copy(source)
