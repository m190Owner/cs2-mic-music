# cs2-mic-music - Design

## Purpose
Desktop app that plays local audio files and YouTube tracks through a virtual
audio cable so that they appear on the user's microphone in Counter-Strike 2 (or
any other voice-chat-using application). User can simultaneously monitor the
output on their real headphones.

## Scope
- Music player with queue, play/pause/skip/prev/seek/volume.
- Sources: local files (folder library) and YouTube (URL paste + search).
- Output routing: user-selectable output device (e.g. VB-CABLE Input) **plus**
  an optional second monitor device (e.g. headphones) - same audio fanned to
  both.
- Save/load named playlists (mixed local + YouTube entries) to disk.
- Loudness normalization across tracks (ffmpeg `loudnorm`).
- Crossfade between consecutive tracks.
- YouTube playback: stream immediately, cache the file in the background so
  subsequent plays are offline/instant.
- Global hotkeys for play/pause, next/prev, volume up/down.
- Volume duck hotkey is **out of scope** (explicitly dropped).

## Non-goals
- Live mic mixing (real-mic + music in one stream). Voicemeeter handles that;
  this app only outputs music. The user toggles their CS2 input device when
  they want to talk normally.
- Soundboard / short-clip pads.
- Mobile, web, or non-Windows targets. Windows-only initially.
- Streaming sources other than YouTube (Spotify/SoundCloud later if desired).

## Architecture

Single Python process, four cooperating modules:

```
cs2-mic-music/
├── audio/
│   ├── decoder.py     # ffmpeg subprocess → PCM frames (loudnorm applied)
│   ├── mixer.py       # crossfade-aware PCM combiner for ≤2 active tracks
│   └── sink.py        # 1-2 sounddevice OutputStreams fed from mixer
├── sources/
│   ├── local.py       # file path → decoder
│   └── youtube.py     # URL/search → yt-dlp → streaming + background cache
├── player/
│   ├── queue.py       # ordered list, current index, repeat/shuffle
│   ├── transport.py   # play/pause/skip/seek, owns the mixer
│   └── playlists.py   # save/load named playlists to JSON on disk
├── ui/
│   ├── main_window.py
│   ├── queue_view.py
│   ├── device_picker.py
│   └── url_box.py
├── hotkeys.py         # pynput global hotkeys → transport commands
├── config.py          # settings: device IDs, hotkey bindings, last playlist
└── app.py             # entry point, wires units together
```

### Module boundaries
- `transport` is the **only** thing the UI and hotkeys talk to. The UI never
  touches `audio/` directly. This keeps the audio engine swappable and lets
  `transport` be tested with a fake mixer.
- `sources/*` produce a `Track` record (title, duration, decoder factory) -
  identical to the rest of the system regardless of origin.
- `audio/decoder.py` exposes a uniform PCM-frame interface; mixer and sink
  don't know whether a track came from a local file or YouTube.

### Threading model
- Audio I/O runs in `sounddevice`'s callback thread (high priority, bounded
  latency). The callback ONLY pulls pre-mixed frames from a ring buffer.
- One decoder thread per active track (1–2 during crossfade) reads PCM from
  ffmpeg stdout and pushes into a per-track ring buffer.
- Player logic + GUI run on the Qt main thread; hotkey events from pynput are
  marshalled to Qt via signals (queued connections).
- A single `queue.Queue[Frame]` (or `numpy` ring buffer) sits between the
  per-track buffers and the audio callback to absorb jitter.

## Data flow

```
Track → Decoder (ffmpeg subprocess, applies loudnorm)
            ↓ PCM int16/float32 frames
       Track ring buffer
            ↓
       Mixer (sums up to 2 tracks during crossfade window, applies master volume)
            ↓
       Sink (writes same buffer to 1–2 sounddevice OutputStreams)
            ↓
       Devices: [CABLE Input, headphones]
```

### YouTube flow
1. `youtube.py` accepts a URL or a search query.
2. Cache-hit check: hash of canonical video ID → `~/.cs2-mic-music/cache/`.
3. Cache miss: spawn `yt-dlp` to resolve the direct audio URL, then start
   ffmpeg reading that URL → PCM output. Simultaneously, a parallel `yt-dlp`
   process downloads the best audio format to the cache directory; on
   completion it atomically renames the file into place. Future plays of the
   same track go straight to the local file path.
4. Cache hit: skip yt-dlp entirely; ffmpeg reads the cached file.

### Crossfade
- When the current track has `crossfade_seconds` left, the player starts the
  next track's decoder in parallel.
- The mixer applies an equal-power crossfade curve to both streams over the
  overlap window; both streams output during overlap.
- After the overlap, the previous track's decoder is closed.

## Error handling
- **ffmpeg subprocess failure:** decoder reports an error on its frame channel;
  transport advances to the next track and shows a toast in the UI.
- **yt-dlp failure (network / removed video):** show error in UI, skip track,
  do not advance silently.
- **Device disconnect mid-playback** (e.g. headphones unplugged): sounddevice
  raises; sink catches, pauses playback, and shows a device-lost message; user
  picks a new device.
- **Cache write failure:** non-fatal - playback continues from the streaming
  path, cache miss next time.
- **Hotkey backend unavailable** (pynput init failure): app starts without
  hotkeys, logs a warning, GUI still works.

## Configuration & persistence
- Config file: `%APPDATA%\cs2-mic-music\config.json`
  - Output device IDs (primary + optional monitor)
  - Hotkey bindings
  - Master volume, last playlist, last position
  - Crossfade duration (default 4s, 0 disables)
  - Loudness target LUFS (default −16 LUFS, off-switch in settings)
- Playlists: `%APPDATA%\cs2-mic-music\playlists\<name>.json`
- YouTube cache: `%APPDATA%\cs2-mic-music\cache\<video-id>.<ext>`

## Dependencies
- Python 3.11+
- `PySide6` - GUI
- `sounddevice` (PortAudio) - multi-device output
- `numpy` - PCM buffers, mixer math
- `pynput` - global hotkeys on Windows
- `yt-dlp` - YouTube extraction
- `ffmpeg.exe` - decoding, loudnorm, resampling (bundled or PATH)
- Optional: `mutagen` - read metadata from local files
- Optional: `PyInstaller` - build a single .exe distribution

## Testing
- `transport` and `queue` are pure Python, testable with a fake mixer.
- `mixer.py` tested with deterministic synthetic frames (assert crossfade
  amplitude curve, assert silence after EOS).
- `sources/youtube.py` mocked at the yt-dlp / ffmpeg subprocess boundary.
- End-to-end smoke test: load a short bundled .wav, verify it appears at the
  selected sounddevice output (loopback device in test).
- Manual checklist: VB-CABLE selected → talk-key in CS2 → teammates hear
  music. Headphones monitor works simultaneously. Crossfade audible. Hotkeys
  work while CS2 has focus.

## Out-of-scope risks worth knowing
- **CS2 voice-chat misuse:** Valve treats persistent mic spam as reportable.
  README must include a "use in private lobbies / consensual contexts" note.
- **YouTube ToS:** caching downloads is technically against YouTube ToS for
  some content. App is personal-use only.
