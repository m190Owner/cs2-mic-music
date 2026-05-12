# cs2-mic-music

Play local audio files, YouTube tracks, and YouTube/YouTube Music playlists
through a virtual microphone so they show up in Counter-Strike 2 voice chat
(or Discord, or anything else that reads a Windows microphone device).

## Features

- Queue mixing local files, single YouTube/YT Music URLs, search queries,
  and full YouTube/YT Music playlists (paste `playlist?list=…` or
  `watch?v=…&list=…` — both expand into the queue)
- YouTube tracks stream on first play and are cached to disk in the
  background so subsequent plays are instant
- Crossfade between tracks (default 4s, configurable)
- Loudness normalization (ffmpeg `loudnorm`) so quiet songs aren't quiet
  and loud songs don't blow out the mic
- Save / load named playlists (mixed local + YouTube)
- Dual-device output: a mic-target device for CS2 / Discord and an
  optional monitor on your headphones so you hear what teammates hear
- Global hotkeys for play/pause, next/prev, volume
- Per-user config persisted to `%APPDATA%\cs2-mic-music\`

## How it works

```
┌──────────────────┐   ┌─────────────┐   ┌──────────────────────────────┐
│ source (file or  │ → │  ffmpeg     │ → │  mixer (crossfade + loudnorm)│
│ youtube stream)  │   │  PCM decode │   │                              │
└──────────────────┘   └─────────────┘   └─────────────┬────────────────┘
                                                       │
                                       ┌───────────────┴────────────────┐
                                       ↓                                ↓
                              ┌──────────────────┐           ┌────────────────────┐
                              │ mic-target sink  │           │  monitor sink       │
                              │ (virtual cable)  │           │ (your headphones)   │
                              └─────────┬────────┘           └────────────────────┘
                                        │
                                        ↓
                            CS2 / Discord reads it as a microphone
```

Audio is decoded once per source and split to two output devices so the
mic-target and headphone monitor stay perfectly in sync.

## Routing: two options

To get music into CS2 you need a virtual audio device that pretends to be
a microphone. There are two ways to wire it up. Pick one.

### Option A — VB-CABLE (simple; music *replaces* your voice)

Use this if you only want to play music and don't need to talk over it.

1. Install [VB-CABLE](https://vb-audio.com/Cable/) and reboot.
2. Launch cs2-mic-music.
3. **Mic output (CS2):** pick `CABLE Input (VB-Audio Virtual Cable)`.
4. **Monitor (headphones):** pick your real headphones; leave "Hear it
   myself" checked.
5. In CS2: **Settings → Audio → Voice → Voice Input Audio Device →
   `CABLE Output (VB-Audio Virtual Cable)`**.
6. Hold your CS2 push-to-talk key — teammates hear the music. Your
   real mic is bypassed entirely.

### Option B — VoiceMeeter (talk *and* play music at the same time)

Use this when you want to keep talking with teammates while music plays.
[VoiceMeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) is free
and the cleanest setup.

1. Install VoiceMeeter Banana and reboot.
2. In VoiceMeeter:
   - **Stereo Input 1 → Select Input Device → WDM: `<your mic>`**.
     On that strip, leave **A** off and turn **B** on (your voice goes to
     the virtual mic, not your headphones).
   - **Virtual Input ("Voicemeeter Input")**: turn both **A** and **B**
     on (so the app's music plays on your headphones *and* feeds CS2).
   - **Hardware Out A1**: click → **MME (Multimedia)** tab → pick your
     real headphones. **Use MME**, not WDM — WDM/WASAPI locks the
     headphones in exclusive mode and silences every other app's audio.
3. In cs2-mic-music:
   - **Mic output (CS2):** `Voicemeeter Input` (or
     `VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)`).
   - **Monitor (headphones):** disable it ("Hear it myself" off) — the
     A bus already feeds your headphones via VoiceMeeter.
4. In CS2: **Settings → Audio → Voice → Voice Input Audio Device →
   `Voicemeeter Out B1`** (you may need to scroll the dropdown; full list
   is visible in Windows **Sound → Recording**).
5. Push to talk. Teammates hear your mic + the music; you hear the music
   plus game audio normally; game audio doesn't get re-injected into your
   mic.

> Tip: if CS2's dropdown can't find `Voicemeeter Out B1`, right-click it
> in Windows **Sound → Recording** → *Set as Default Communications
> Device* and pick `Default Device` in CS2 instead.

## Prerequisites

- Windows 10 / 11
- Python 3.11+
- [**ffmpeg**](https://www.gyan.dev/ffmpeg/builds/) on `PATH`
- One of: VB-CABLE *or* VoiceMeeter (see Routing above)

## Install

```pwsh
git clone https://github.com/m190Owner/cs2-mic-music.git
cd cs2-mic-music
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Run

```pwsh
python -m cs2_mic_music.app
```

Or after `pip install -e .`, you get a `cs2-mic-music.exe` in
`.venv\Scripts\` — pin a shortcut to that to your taskbar for one-click
launch (the GUI entry point under `[project.gui-scripts]` means no console
window flashes on launch).

## Adding tracks

- **Add folder…** / **Add files…**: pull in local audio (mp3, flac, wav,
  m4a, aac, ogg, opus).
- **URL / search box**: paste any of —
  - a single YouTube URL (`youtube.com/watch?v=…` or `youtu.be/…`)
  - a single YouTube Music URL
  - a YouTube *or* YouTube Music playlist URL
    (`/playlist?list=…` or `watch?v=…&list=…`)
  - a free-text search (resolves to the top YouTube hit)
- **Save playlist…** / **Load playlist…**: save your current queue under
  a name, load it back later. Stored as JSON in
  `%APPDATA%\cs2-mic-music\playlists\`.

Playlist tracks resolve lazily — the queue fills instantly with metadata
(title, artist, duration), and each entry resolves to a stream URL or
cached file at play time. A serial background download caches the whole
playlist to `%APPDATA%\cs2-mic-music\cache\` so re-plays are local.

## Default hotkeys

| Action       | Hotkey               |
|--------------|----------------------|
| Play / pause | `Ctrl+Shift+P`       |
| Next track   | `Ctrl+Shift+.`       |
| Prev track   | `Ctrl+Shift+,`       |
| Volume up    | `Ctrl+Shift+=`       |
| Volume down  | `Ctrl+Shift+-`       |

Rebind by editing `%APPDATA%\cs2-mic-music\config.json`. Format follows
[pynput's GlobalHotKeys syntax](https://pynput.readthedocs.io/en/latest/keyboard.html#monitoring-the-keyboard).

## Files and directories

| Path                                          | What                       |
|-----------------------------------------------|----------------------------|
| `%APPDATA%\cs2-mic-music\config.json`         | Settings                   |
| `%APPDATA%\cs2-mic-music\playlists\*.json`    | Saved playlists            |
| `%APPDATA%\cs2-mic-music\cache\*.opus`        | YouTube audio cache        |

## Use responsibly

Valve treats mic spam and disruptive audio in matchmaking as a
reportable offense and it'll get you comms-banned quickly. Use in
private lobbies, with friends, or where it's welcome. YouTube
downloading is for personal use only.

## Layout

```
src/cs2_mic_music/
├── audio/        decoder (ffmpeg PCM), mixer (crossfade), sink (dual device)
├── sources/      local files + YouTube / YouTube Music
├── player/       queue, transport, playlists, async YouTube resolver
├── ui/           PySide6 window
├── hotkeys.py    pynput global hotkeys
├── config.py     %APPDATA% JSON config
└── app.py        entry point
```
