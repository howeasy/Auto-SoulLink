"""Presentation of an already reproduced run's exact patch inputs and outputs."""
import hashlib
from server.gen1_prepared_cartridges import PreparedCartridges


def prepared_targets(cartridges):
    if cartridges is None:return {}
    if not isinstance(cartridges,PreparedCartridges):raise ValueError("reproduced prepared cartridges required")
    result={}
    for player,metadata in cartridges.contract()["players"].items():
        variant=metadata["variant"];slug="run-"+player
        source,final,patch=cartridges.unpatched_rom(player),cartridges.rom(player),cartridges.patch(player)
        result[slug]={"slug":slug,"label":"Player "+player.upper()+" · Pokemon "+variant.capitalize(),"variant":variant,
            "patch":"SLink-Run-"+player.upper()+".ups","patch_bytes":patch,
            "base_md5":hashlib.md5(source).hexdigest(),"patched_md5":hashlib.md5(final).hexdigest(),
            "base_sha256":hashlib.sha256(source).hexdigest(),"patched_sha256":hashlib.sha256(final).hexdigest(),
            "patch_sha256":hashlib.sha256(patch).hexdigest(),"capabilities":metadata["capabilities"],
            "accept":".gb,.gbc,application/octet-stream","out_name":"SLink-Player-"+player.upper()+"-"+variant.capitalize()+".gbc",
            "base_hint":"this run's unpatched randomized Pokemon "+variant.capitalize()+" ROM for player "+player.upper()}
    return result
