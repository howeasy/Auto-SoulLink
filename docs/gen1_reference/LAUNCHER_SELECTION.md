# Prepared-run launcher and owned client entry

The [initial enrollment continuation](INITIAL_ENROLLMENT.md) adds an opt-in
production empty-run factory and atomic initial inventory observation through
downloaded held launchers. It binds source context without inventing captures,
links or gameplay authority. Ordinary activation remains separate.
The [temporal checkpoint observer](TEMPORAL_INVENTORY.md) is now included in that
checked file closure. The fixed-frame held entry emits no later checkpoints
until an independently qualified execution lifecycle supplies them.

Prepared Gen1 runs now select the durable service through the normal server CLI
and expose a run-bound launcher through both the run server and Manager. This
selection is currently **held service**: it connects and preserves durable
obligations while refusing ordinary execution and unqualified physical adapters.
It is not yet a normal-play RC launcher.

## Run and client binding

server/gen1_run_config.py publishes gen1_runtime.json only from an already
opened, explicitly bootstrapped runtime. The descriptor binds the journal file,
durable run ID and cartridge contract. Startup validates the existing database
through the read-only reader before opening it; malformed/missing state never
becomes a fresh journal or a legacy links.json fallback. Legacy --reset refuses
prepared durable runs. Existing ordinary runs keep their prior selection.

The downloaded launcher binds run ID, player, endpoint, cartridge profile and a
25-file client closure. Lua/JSON files use normalized-LF UTF-8 SHA256, binary files
use exact SHA256. Every listed file is checked before executing lua/slink.lua.
The universal entrypoint routes explicit durable configuration to
lua/gen1_client_entry.lua instead of the legacy client/log path. Stale/mismatched
client files refuse startup. Gen1 HELLO now also includes the durable run ID;
another run with identical ROM/save metadata cannot silently accept the launcher.

The owned entry validates ROM/profile, waits for the initial verified overworld
checkpoint, establishes the pinned independent Gambatte hold and opens the
player's checked journal. By default client data lives in local application data
under SLink/clients/<run>/<player>. SLINK_CLIENT_STORAGE_ROOT can select a local
portable/test directory; it is not a remote launch-payload path. Reconnect does
not clear the journal. A changed save refuses its binding; changed core/command
contexts still require explicit recovery. The entry never grants ordinary frames
in held-service mode, even if a server sends run authority.

## Stopped runs

The Manager runtime boundary can now read a configured Gen1 journal while stopped,
returning detached committed rules and revision without creating a runtime,
reconciling, repairing, draining commands or touching a legacy save. Unknown
SQLite files without a prepared descriptor retain the unavailable result.

## Evidence and limits

Thirteen Gen1 launcher/configuration tests cover the actual server subprocess,
HTTP and Manager download routes, run mismatch, immutable prepared selection,
stopped reads and invalid inputs. Thirteen shared launcher/reader cases and16
shared arithmetic cases are separately portable.

Three real launcher cases pass: actual downloaded launchers start Yellow/Yellow
and Red/Blue clients with separate processes/journals, persistent pending commands,
unchanged frame counts and unchanged WRAM. The third case corrupts a required
fingerprint and proves refusal before admission or client-journal creation.
The live observer only wraps native yield to inspect state and exit the private
test processes; it grants no frames or game writes. Private test configs disable
rewind to match the qualified hold profile. Runtime/network regression cases also
pass after the run-ID binding change.

The broad unit/integration run passed4,146 tests with the same two Windows
symlink privilege skips. Evidence is in .cache/launch-full.xml,
.cache/launcher-live-final.xml and .cache/gen1-launcher-*/verified.json.

Remaining RC work: authoritative fresh-run/gameplay bootstrap, ordinary-frame and
reset/load/recovery qualification, observation batching and cartridge executors,
native receptionist/partner/coordinator routing, final companions and approved
UPR/browser publication. Pre-run debug fixture initialization also remains needed
for30 legacy Gen1 E2E cases currently blocked by the intentional HTTP guard.

Shared published cuts:31821e195985722893fd3717c31aaa8880fb40cf (checked launcher and
read-only journal reader) and114f3f33e81f66fed5222e94ca664336077b8ad3 (unchanged stat
arithmetic). Gen1-specific selection/entry policy remains in this worktree.
