# OoT movie timing and stereo routing

Verified with the original update 131072 assets on an Apple M4 / 16 GB Mac.
Generated movies, screenshots, audio captures, shaders and saves remain private.

## Movie playback

The title movie and `Dm_Kokiri_0000` are 60 FPS AV1 streams. The Kokiri source
is 154.234 seconds long. With roughly 30 rendered frames per second, the old
codec path delivered old pictures instead of catching up with the movie's
nanosecond presentation timestamps. Music and narration continued at normal
speed. A baseline trace advanced 154.050 seconds of Kokiri video in 300.282
seconds of elapsed time; the title advanced 59.383 seconds in 113.082 seconds.

`ns2_codec.c` now anchors a movie clock when the client first accepts a valid
picture. Every input packet is still decoded, preserving AV1 reference frames.
Late decoded pictures can be discarded before publishing the output buffer.
This matters for OoT's actual one-picture pool, where there is no second ready
buffer for the client to choose. Unacquired older output pictures can also be
recycled when a newer decoded picture is due. Client-acquired buffers retain
their ownership, generation and sync-event rules.

At most one discarded picture is retained until the next publication or EOF,
so an empty EOF packet cannot lose the movie's final image. Reset/flush clears
the clock and retained picture. VP8/VP9 behavior is unchanged. No audio delay,
balance adjustment, frame generation or game-clock/physics change is applied.

Diagnostic environment variables:

- `OOT_MOVIE_SYNC=0`: original FIFO behavior, for comparison.
- `OOT_MOVIE_TRACE=1`: one timestamp sample per second, including the decoder,
  uptime nanoseconds, picture timestamp, publications, drops and queue counts.

The final Kokiri playback trace advanced 153.833 seconds of video in
153.844 seconds of elapsed time, then delivered EOF and entered the following
3D cutscene. Maximum sampled drift from its starting timestamp was 21.651 ms.
An earlier corrected title run advanced 98.500 seconds in 98.499 seconds.
These are timestamp progression measurements sampled once per second, not a
measurement of zero device-output latency or a claim of 60 rendered FPS.

Run the actual output-queue code with synthetic owned pictures, no game files:

```sh
make -C engine WORK=/external/work \
  VPX_PREFIX=/path/to/libvpx OPUS_PREFIX=/path/to/opus DAV1D_PREFIX=/path/to/dav1d \
  probe-movie-queue
```

The AddressSanitizer/UndefinedBehaviorSanitizer probe covers one and eight
output buffers, 24/30/60/120 FPS consumers, a 750 ms consumer stall, final-image
and EOF delivery, reset, client-held buffer ownership, and timestamp bounds.
The enabled cases pass 19,577 checks. The disabled comparison passes 3,877
checks that specifically confirm the old accumulated lag: about 3.103 seconds
behind after a three-second source at 30 rendered FPS. These synthetic tests
supplement actual AV1 playback; they do not replace it.

## Stereo routing

The original front-left voice loss was incorporated upstream in
[`df1e321d`](https://github.com/ly05010419/MacNativeGames/commit/df1e321d4a9304855f81de3c9a3d471c4c748af5),
after Christian Furr's fork. Inactive records can retain a stale ID of zero;
they must not clear a live voice with that ID. Channel-resource records are
positional, whereas active voice records name their voices by ID. Preserve
that distinction when changing the parser.

The existing REV15/REV16 wire-request regression now also shuffles the active
voice records between requests, followed by a gain change and stopping one
voice, while an inactive ID-zero record remains present. This protects both
the original stereo repair and the upstream server's active-voice semantics.

The device-free renderer probe also checks all six isolated sink inputs with
default and custom downmix coefficients. A centre-only voice must reach both
stereo channels; LFE remains intentionally omitted from this downmix.

Run the production renderer and mixer without loading game modules or opening
an audio device (macOS with Xcode command-line tools):

```sh
python3 engine/tests/test_audio_renderer.py
```

This builds with AddressSanitizer/UndefinedBehaviorSanitizer, runs 58,133 checks,
and checks a negative control with an intentionally incorrect right-channel
gain. The fixture replaces unrelated IPC/event transport only. It does not
verify physical output, authored voice assets, language selection or listening.

```sh
TOTK_AUDIO_OFF=1 /external/work/build/oot-native rewritten/oot probe-audio
```

The earlier production renderer probe passed 52,373 checks. A 28-second overlap of a
corrected runtime stereo capture against an independently decoded original
title BWAV has correlations of 0.999999842 (left) and 0.999999851 (right), with
unity gain to within 0.000001. The source's natural right-minus-left balance is
about +0.232 dB. No gain compensation or forced mono is used. The first two
capture seconds are omitted only to allow alignment past the capture block's
2.5 ms lead-in; the audio itself is not changed.

## Missing-voice acceptance

Use a scene with a verified authored voice asset, such as the opening Kokiri
narration when present in the user's game version. Text dialogue alone does
not establish that a voice should exist. Inspect the selected locale, matching
voice assets and active mod overlays before changing mixer behavior.

During an integration-scheduled, isolated-profile session, correlate RomFS
opens (`TOTK_FS_LOG=1`), decoder errors, renderer requests and mixer output.
`TOTK_AUDIO_CAPTURE` records the mix before callback delivery: nonzero samples
do not prove the device played them. Check callback nonzero counts, startup
audio-hold release, selected device/channel layout and actual listening too.
The independent AudioOut path logs `[ns2-audio] AudioOut ... opened` and does
not pass through the renderer's capture. Keep extracted audio, logs and saves
private. Missing-voice and physical-output acceptance remain open until this
scene-specific evidence exists; synthetic checks do not resolve the report.
