# Shared checked launcher and journal reader

server/runtime_launcher.py and server/journal_reader.py contain no cartridge
addresses or generation admission policy. Gen1 supplies its own prepared-run
descriptor, client-file closure and held-service entrypoint.

## Checked launcher

file_bundle(root, paths) returns a bounded unique list of relative client files
and SHA256 fingerprints. Lua/JSON text uses strict UTF-8 with CRLF normalized to
LF; binary files retain their exact bytes. Absolute paths, traversal, platform
path separators and files resolving outside root are refused.

render_launcher(configuration, host, port, name, root_hint=None) emits Lua with
safe literal/comment encoding and single-pass placeholder substitution. The
configuration names a32-hex run ID, player a/b and the checked file list. The
universal lua/slink.lua entrypoint must be in that list. The generation supplies
and qualifies the complete transitive file closure and its configuration schema.

The launcher resolves the local project root, verifies every listed file through
the host's SHA256/strict UTF-8 APIs before executing project code, then supplies
SLINK_RUNTIME_LAUNCH_JSON to the universal entrypoint. A file mismatch refuses
startup. root_hint is optional; the normal search/cache/folder picker remains
available for launchers downloaded outside the project directory.

This is a file-version check, not attestation of every running Lua/host component.
The generation still owns core/ROM/save identity, runtime admission, execution
holds and its adapters. No configuration field grants gameplay permission.

## Read-only journal

read_journal(path, run_id=None, contract_hash=None) opens only an existing database
using SQLite mode=ro and query_only. It validates the journal application/schema
IDs, bounded metadata, optional expected run/contract identity, exact committed
revision range and the canonical snapshot checksum. It reads metadata and the
snapshot in one transaction and honors committed WAL data.

It returns JournalRead(run_id, contract_hash, snapshot). The returned snapshot is
detached. It neither constructs ProtocolJournal nor initializes missing tables,
repairs corruption, migrates a legacy run, drains commands or grants authority.
SQLite may use its normal reader locks/shared-memory coordination; no journal
data transaction is written. Full event/command-history auditing and generation
state validation remain caller responsibilities.

## Qualification

Thirteen portable shared tests cover line endings versus binary fingerprints,
safe paths, entrypoint inclusion, quoted/template-marker names, current WAL reads,
wrong identity and corrupt snapshot/metadata refusal without repair. Gen1 adds
prepared-run, stopped-reader, Manager/HTTP and actual CLI tests.

Actual generated Gen1 launchers have passed on Yellow/Yellow and Red/Blue under
independent holds, with separate local journals and unchanged frames/WRAM. A
tampered launcher fingerprint refuses before admission/client-journal creation.
Those are held-service results; ordinary gameplay, native execution and recovery
qualification are not implied for Gen1 or another generation.
