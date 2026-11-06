# Whiterun camera reference, v2

This corpus contains 18 normalized numerical observations from original Skyrim
SE 1.7.104.0: three repeats of each frozen fixture. It contains no executable,
DLL, game asset, save, or screenshot. Each run records hashes of its native trace,
screenshots, runtime, source save, probe, and input sender. `corpus.json` binds the
plan and all run files. `environment-audit.json` retains an additional INI/plugin
list and animation-archive snapshot taken during the last repeat; it is not a
record of every loaded asset.

`result/` preserves the first completed study's report, locked candidate, and
265 trials. Predictions and the interactive HTML report can be regenerated with
the [offline command](../../HILLCLIMB.md). Repeating this study does not turn the
already inspected held-out cases into fresh validation data for a revised model.

The post-release analysis window was extended from 1.5 to 1.9 seconds before any
search, so a full half-second of rest follows the landing animation. Existing
2-second raw tails were reused unchanged; fit thresholds were unchanged.

The local raw campaign is `~/.cache/mudcrab-520/hillclimb/campaign-02/`, including
`raw/`, frozen `source/`, and capture/revision receipts. Original study outputs
are in `~/.cache/mudcrab-520/hillclimb/study-01/`. These machine-local files are
needed to audit native binary records and screenshots; the portable numerical
corpus alone supports response-model replay.
