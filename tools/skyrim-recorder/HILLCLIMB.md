# Compare native stair-camera responses

This experiment addresses [issue #520](https://github.com/Mudcrab-Team/mudcrab/issues/520)
with original Skyrim observations and an offline parameter search. It fits camera
response to the recorded player trajectory. It does not replay Mudcrab's collision
solver or change the engine camera defaults.

The [recorded result](../../docs/research/skyrim-camera-520.md) recovers the native
spring parameters and passes the stair comparisons, but rejects the complete
camera candidate on jump/landing error.

## Rerun the offline study

The numerical reference corpus contains no game assets, saves, DLLs, or screenshots.
With Python 3 and `rustc` installed, run from the repository root:

```sh
python3 scripts/hillclimb_skyrim_camera.py study \
  --corpus tools/skyrim-recorder/reference/whiterun-v2/corpus.json \
  --output /tmp/skyrim-camera-study-new
python3 scripts/plot_camera_hillclimb.py /tmp/skyrim-camera-study-new
```

Use a new study output directory. The study compiles `camera_response.rs`, validates
corpus hashes, searches only the training runs, writes `winner.json`, and then
loads and scores held-out observations. `trials.jsonl` retains every unique trial.
`report.json` records per-run errors, repeat spread, acceptance gates, model/source
hashes, and the verdict. CSV files retain predictions for each run; the optional
HTML report shows one repeat of each fixture interactively.

An inconclusive or rejected verdict is a completed experiment. It does not mean
the search should tune against the held-out cases. Further model development needs
a new withheld dataset before making another generalization claim.

## Capture fresh original-game references

First prepare a private session using [the recorder instructions](README.md).
Use a session prepared with the current recorder source. This fixture plan is tied
to the executable and source-save hashes it declares; a different save needs a
separate surveyed plan. Start an authenticated Steam session, then run:

```sh
python3 scripts/hillclimb_skyrim_camera.py capture \
  --plan tools/skyrim-recorder/fixtures/hillclimb-v2.json \
  --session /path/to/prepared-session \
  --output /path/to/new-campaign \
  --ocr-prefix /
```

The command serially records three repeats of six fixtures, alternating routes
between repeats. Lower castle stair ascent/descent train the model. A separate
upper flight and courtyard flat/jump controls are held out. Each run reloads the
copied save, places the player through a private console batch, verifies native
position/heading and stationary camera pre-roll, and sends one bounded W chord.
Shift selects walking; Space requests the jump control. The native movement and
jump handlers record the mapped actions and their press/release events.

Capture can resume the same campaign only with the same plan, session, recorder,
runner, and normalization source. It retains failed attempts and reuses completed
raw runs only when their fixture and source hashes match. A native run must pass
before normalization; normalization additionally checks the surveyed route,
vertical excitation, native spring state, time continuity, and settling tail.

The source save and original executable stay unchanged. Captures and private game
copies remain outside Git. Preserve `raw/`, `source/` when present, `assets.json`,
and the campaign receipts with the normalized corpus for local audits.

## What the candidates mean

All candidates receive the same native player-height sequence and the same
recorded, scaled camera timestep. They start at rest during stationary pre-roll
and evolve their own state. They never receive future observed spring velocity,
correction, or final camera height as inputs.

- **Direct:** zero relative-height correction, equivalent to this checkout's
  `walk_camera_follow_system` after subtracting its constant eye height.
- **55 ms exponential:** the response formula from open
  [PR #511 at `41df866`](https://github.com/Mudcrab-Team/mudcrab/pull/511), applied
  to every observed vertical change. PR511's solver-validated stair eligibility,
  accumulated fixed-tick events, and resets are **not replayed**.
- **Spring:** an experimental, free-running two-state recurrence supported by the
  native observations. Search parameters are the exponential spring base and
  velocity-damping coefficient. Its applicability is limited to the observed
  controller flag and spring weight both remaining one.

For target player height `p`, prior corrected height `h`, prior velocity `v`, and
native scaled timestep `dt`, the spring candidate computes:

```text
delta = h - p
correction = spring_base ** dt * delta + damping * dt * v
h = p + correction
v = (correction - delta) / dt
```

This is a behavioral model written independently from the native measurements
and limited static findings. The tool uses f64 arithmetic on relative heights;
it does not claim binary-identical f32 execution or reproduce all native gates.
The observed native settings, 0.001 and 0.6, are evaluated after winner selection
as a diagnostic, not inserted as the search answer.

The primary target is attached-camera height minus player height minus one
stationary eye-offset estimate. This holds eye-height conventions constant without
assuming native actor position equals Mudcrab's capsule centre. The search has no
free time shift, fitted baseline per trial, or time warping. Native scaled time
advances the models; QPC wall time weights errors.

## Decision rules and scope

The plan fixes bounds, seeds, train/held-out membership, and thresholds before
search. Stair gains must beat both baselines by more than the larger of 0.05
Creation units and training-repeat baseline RMSE spread. Held-out absolute RMSE,
peak-error, end-bias, and control nonregression gates are reported separately.
A flat or blocked trace cannot satisfy a stair fixture. Missing native input,
unpaired spring samples, nonfinite values, camera gaps over 100 ms, unsupported
spring gates, and insufficient rest reject the recording.

Three repeats quantify this bounded campaign's variation; they are not a
population-level confidence interval. Stair routes were confirmed in native
screenshots and linked to authored placement candidates. Native player movement
is already comparatively smooth on these stairs, so using that movement as input
does not test Mudcrab's discrete stair solver.

The source `Camera1st` node can add animation independent of player height,
including a landing dip. `source_node_conditioned_peak` diagnoses the remaining
error if that measured source-node motion is supplied. It does not participate in
search or acceptance and must not be presented as a successful whole-camera
candidate: Mudcrab does not currently supply that native animation input.

Samples are taken around the full CPU `PlayerCamera::Update` call. They do not
establish final GPU consumption, arbitrary-framerate parity, door/teleport behavior,
or behavior outside this pinned runtime and observed gate state.

## Native fields recorded for issue #520

The profile stores RVAs relative to the executable image base `0x140000000`.
The observer wraps the full camera update at RVA `0x8f8680` through its gameplay
call at `0x746964`. This is a broader boundary than the first-person update at
`0x8f47a0` identified in the issue.

| Observation | Location in this runtime |
| --- | --- |
| Player movement-controller pointer | Player `+0x150`, verified against its getter |
| Controller flag | Controller `+0x1c5`; getter RVA `0x796ac0` |
| Corrected position, velocity, correction | First-person state `+0x30`, `+0x3c`, `+0x48` |
| Source `Camera1st` node and spring weight | First-person state `+0x58` and `+0x80` |
| Source-node world position | Node `+0xa0` |
| Scaled camera timestep | Global RVA `0x3275608` |
| Vertical spring and damping values | RVAs `0x20ba098` and `0x20ba0b0` |

Native vertical coordinates are Z; Mudcrab uses Y. The comparison removes a
stationary eye offset instead of assuming the two engines use the same actor
origin. The records preserve the observed controller flag and weight rather than
inferring their values from construction defaults.

## Design and checks

The design compared a shared response crate, a standalone replay tool, and full
headless Bevy/Rapier trials. The standalone Rust evaluator keeps one experimental
recurrence implementation and avoids an unused production abstraction. Full
controller trials would mix collision differences into this camera-only question.
The independent designs agreed on frozen data splits and explicit eligibility
limits. The configured judge pool used only the parent's model family, and the
other-family providers were disabled; the parent performed the final comparison.

Run the deterministic checks without Skyrim:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*skyrim*camera.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p test_record_skyrim_motion.py
rustc --edition=2024 --test tools/skyrim-recorder/camera_response.rs -o /tmp/camera-response-tests
/tmp/camera-response-tests
```

The checks include wrong-fixture, missing-input, lost-time, nonfinite-matrix,
unsupported-gate, corrupted-hash, and flat/no-motion negatives. Kernel checks cover
rest, direct follow, exponential settling, reversal continuity, and spring memory.
Native capture and the final held-out study remain the evidence for real behavior.
