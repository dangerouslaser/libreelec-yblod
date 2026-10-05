# Native precision diagnostic — not an engine policy

`native_precision_probe.c/.h` compares explicitly requested floor, nearest
half-up and nearest ties-even input quantization followed by the unchanged
native integer NLQ stage. A separate entry point evaluates the literal rational
pre-floor algebra, with metadata limiting before the final signed floor.
There is no default selected policy and no change to `native_composer`.

The declared input convention is native 10-bit code `s = W / 64`, with strict
raw-word domain **0 through 65472**. Values above that domain are rejected for
every candidate, even where a particular quantizer might produce a valid code.
This is an explicit experiment domain, not a claim that every Y416 surface uses
this convention. Alpha is not a picture sample. No texture sampling, shader
floating-point noise guard, Dolby conformance, player fit or movie accuracy is
emulated.

For `d = W - 64*offset` and its sign `z`, the literal diagnostic returns
uncapped numerator `(2*d - 64*z)*slope + 128*z*threshold`, capped numerator
limited to `±128*maximum`, divisor `64*2^(D-15)`, and the signed floor of that
ratio. At neutral all are zero except the divisor. Accepted coefficient bounds
keep every intermediate below signed 64-bit limits. The rational ratio remains
visible: flooring it is reported separately, not silently substituted for the
fractional value. Python `Fraction` comparisons are test oracles only.

Build against `native_composer.c`; its GCC/Clang signed `__int128` requirement
still applies. Run `python3 -m unittest test_native_precision_probe`.
Tests exhaust all 1024 integer anchors for 75 configurations across D15/23/32,
varied offsets, zero/extreme coefficients and binding/nonbinding limits; they
also test every word in the declared Q6 domain for one nonbinding configuration
and dense neutral-boundary inputs. Every integer anchor must reduce to the
unchanged integer contract. Malformed metadata and overshoot leave outputs
unchanged. Caller-owned pointers must be valid, aligned, separate and stable.

For the synthetic offset512/slope2048/threshold0/D23 fixture, raw32769 gives
literal −7.75 correction units while all three input quantizers give zero;
raw32767 gives literal +7.75 while floor gives −8 and both nearest policies
give zero. These differing answers identify an unresolved input contract, not
an accepted fix. An artificial maximum1025 produces +8/−9 after clipping then
flooring at ±2 native codes. Artificial coefficients are arithmetic fixtures,
not assertions that a complete encoded stream is conforming.

The original saved scaler profiles had no nonzero driven-axis samples within
±32 raw words of neutral. Subsequent [near-neutral cohorts](INTEL_Y416_NEUTRAL_RESULTS.md)
now provide measured quarter- and half-code examples, but do not establish
which fractional reconstruction policy is correct.
The diagnostic can be studied without capturing or publishing film frames.
