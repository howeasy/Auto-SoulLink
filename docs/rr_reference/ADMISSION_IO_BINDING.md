# RR metadata with actual host API bindings

The installed BizHawk/NLua exports memory and game-info APIs as callable userdata,
not Lua values whose type is `function`. The RR metadata helper's function-only
check rejected direct host bindings before reading any metadata. A controlled
userdata-provider regression reproduced that refusal before the correction.

The helper now accepts function or userdata candidates and still executes every
read inside its protected call, validates all values and compares two save/mode
snapshots plus both ROM-hash reads. A noncallable userdata value or malformed
return fails instead of establishing a provider. The complete78 admission tests
pass, including both added userdata cases.

Private run66 used actual candidate07 and the independently observed07 battery
fixture. It passed the actual userdata APIs directly, read trainer B/ID2BDDC8BF,
verified the loaded ROM, Default/MGM-on flags and native descriptor, and advanced
no frames during the provider call. Party/mailbox bytes stayed unchanged. The
exact child exited normally and original config/SaveRAM remained unchanged.
[Bound evidence](admission_userdata_evidence.json) retains1756 assertions and
all source/fixture/host/result identities.

The descriptor input is bound to the physically checked immutable ROM descriptor.
Client/data bundle hashes are explicitly diagnostic placeholders. This test
establishes the metadata reader's host interoperability; it does not implement
loader attestation, select admission, send HELLO, reconcile players or authorize
gameplay/native mutations. Its evidence keeps those claims false.
