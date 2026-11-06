# Record one native Skyrim movement input

Use this probe to establish that scripted input reaches Skyrim's movement handler
and produces synchronized player and camera observations. It supports only the
Skyrim SE 1.7.104.0 executable identified in [runtime.json](runtime.json).

For repeated stair fixtures, parameter search, and held-out comparisons, use the
[issue #520 hill-climb guide](HILLCLIMB.md).

## Prepare an isolated session

Install Python 3, LLVM (`clang-cl`, `lld-link`, `llvm-dlltool`), a C compiler,
`pkg-config`, libei development headers, libX11, Gamescope, and `xprop`.
Use an installed Proton distribution and an authenticated Steam session.
Provide Tesseract with English language data. For system-installed Tesseract,
pass `--ocr-prefix /`.

Choose an outdoor save with a clear forward path and dependencies available in
your installed game. Preparation copies the save and mutable game files.
It links the source assets into a separate game directory and creates a separate
Proton prefix. The source save is checked for changes after recording.

Run from the repository root, substituting your paths:

```sh
python3 scripts/record_skyrim_motion.py prepare \
	--game '/path/to/Skyrim Special Edition' \
	--save '/path/to/fixture.ess' \
	--proton '/path/to/Proton/proton' \
	--session '/path/to/new-session'
```

Preparation builds a private `dinput8.dll` and a Linux libei input sender.
The DLL forwards `DirectInput8Create` to Wine's system implementation.
The source executable stays unchanged. No SKSE binary, Address Library, Windows
SDK, or Windows C++ runtime is required.

## Record and verify

```sh
python3 scripts/record_skyrim_motion.py run \
	--session '/path/to/new-session' \
	--output '/path/to/new-run' \
	--ocr-prefix /

python3 scripts/record_skyrim_motion.py verify '/path/to/new-run/trace.bin'
```

The runner starts a private headless Gamescope display and a fresh game process.
It loads the copied fixture, declines a recognized survival-mode prompt, selects
first person, and waits for stationary, advancing camera samples. It then sends
one 500 ms W hold through the display's libei socket. The input sender retains
its virtual keyboard until release. Native recording ends two seconds after
Skyrim delivers the release to its movement handler.

Expect `"status": "passed"` in `proof.json`. Verification requires all of these:

- Exactly one native W press and release mapped to `Forward`.
- A positive forward value after the original movement handler returns.
- First-person samples before, during, and after the press, associated with the
  native input sequence.
- Player movement in the starting forward direction and corresponding camera-root
  and attached `NiCamera` movement.
- Contiguous records, finite coordinates, and a native completion record.

Review `before.png`, `after.png`, `issued-input.jsonl`, `trace.jsonl`, and
`proof.json` beside the binary trace. Failed runs retain `failure.json`, partial
traces, logs, and available screenshots. A sent key alone never passes the check.
Each run needs a fresh output directory. Keep game assets, saves, and raw recordings
outside Git. The hill-climb corpus contains only normalized numerical observations
and provenance hashes.

## Interpret the camera boundary

Samples come from the return of the full native `PlayerCamera::Update` call in
the gameplay path, immediately before its caller extracts the camera position.
Each sample contains player position and angles, camera-root local and world
positions, the attached `NiCamera` world position, and its world-to-camera matrix.
Coordinates retain Skyrim's Z-up basis and Creation units.

The sample counter counts observed camera updates. It is not a proven renderer
frame ID. Input events and samples share native QPC timestamps. Host input-send
timestamps use a separate clock.

`trace.jsonl` decodes the fixed 256-byte little-endian records. `kind=2` is a
movement or jump observation; `kind=3` is a camera sample. `sample` counts camera
updates, and `input_sequence` identifies the latest recorded input observation.
The header (`kind=1`) stores QPC frequency in `sample`; `kind=5` closes the trace.
Recorder v2 also emits a paired spring observation (`kind=6`) for each camera
sample. It reads state immediately before and after the original camera update;
the record timestamp is taken after that update.

| Record | `values` slice | Meaning |
| --- | --- | --- |
| Movement | `[0:2]` | Button value and native held seconds |
| Movement | `[2:4]` | Movement vector after the original handler |
| Camera | `[0:3]`, `[3:6]` | Player position and angles in radians |
| Camera | `[6:9]`, `[9:12]` | Camera-root local and world positions |
| Camera | `[12:15]`, `[15:31]` | Attached camera world position and matrix |
| Spring | `[0:3]` | Pre-update player position |
| Spring | `[3:6]`, `[6:9]`, `[9:12]` | Pre-update corrected position, velocity, correction |
| Spring | `[12:15]`, `[15]`, `[16]`, `[17]` | Pre-update source node position, weight, controller flag, scaled dt |
| Spring | `[18:21]`, `[21:24]`, `[24:27]` | Post-update corrected position, velocity, correction |
| Spring | `[27:30]`, `[30]`, `[31]`, `[32]` | Post-update source node position, weight, controller flag, scaled dt |
| Spring | `[36]`, `[37]` | Native spring-base and damping settings |

For camera records, `code & 1` marks valid player/root positions and `code & 2`
marks an attached camera. `state=0` denotes first person. Movement records use
`code` for the keyboard scan code and `text` for the mapped action.
For spring records, `code & 1` and `code & 2` mark valid pre/post observations.

Skyrim dispatches movement through worker threads; camera sampling runs on the
game thread. A recorder lock serializes sequence numbers, timestamps, and file
writes. It is acquired only after each original function returns. Thread IDs
remain in the trace. The lock orders observations; it does not turn them into
renderer frame IDs or eliminate measurement overhead.

This proves a native input-to-motion recording path. It does not establish final
renderer consumption, GPU synchronization, stair response, or Mudcrab parity.
The camera sampler runs after the native update and leaves its result unchanged.

## Runtime evidence and maintenance

The build checks the complete executable hash, movement/jump/camera signatures,
both input vtable slots, controller getter/flag signatures, and the camera call
instruction. The DLL rechecks target code and vtables before installing hooks.
Runtime addresses come from
the single profile in `runtime.json`, which generates the private build header.

The movement observer wraps `MovementHandler::ProcessButton`. It records the
native button value, held duration, action name, and resulting movement vector.
The jump observer wraps `JumpHandler::ProcessButton` in the same way.
The camera observer replaces one verified relative call through a nearby relay.
It does not relocate an arbitrary function prologue.

The design used a small native proxy because current SKSE distribution requires
separate acquisition. It combines the direct-call camera boundary with
compositor input and native acceptance checks. A debugger recorder and a full
CommonLib build were considered; neither is required for this bounded probe.

The profile was checked against the local executable using these public type
declarations as references:

- [SKSE input declarations, pinned revision](https://github.com/ianpatt/skse64/blob/25b72352adb6543fa6d0bd3795780672b2e238e0/skse64/GameInput.h).
- [CommonLib camera declarations, pinned revision](https://github.com/alandtse/CommonLibSSE-NG/blob/59626155bb00b9576054dd9666cd5aecb84b4bf2/include/RE/P/PlayerCamera.h).
- [Issue #520](https://github.com/Mudcrab-Team/mudcrab/issues/520).

Run the local checks after changing the recorder:

```sh
python3 -m unittest discover -s scripts -p test_record_skyrim_motion.py
python3 tools/skyrim-recorder/build.py --exe '/path/to/SkyrimSE.exe' --output '/path/to/build'
```

Then prepare a fresh session and rerun the native recording. Parser tests and a
successful DLL build do not replace that check.

The default 500 ms W command verifies input delivery and motion. The separate
[hill-climb workflow](HILLCLIMB.md) adds fixed routes, repeated native observations,
a free-running Rust response evaluator, and frozen training/held-out partitions.
It compares camera response using native player movement; matching Mudcrab's
collision behavior remains a separate experiment.
