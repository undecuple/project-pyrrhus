# Roadmap

What is planned, in rough order. ✅ done · 🔧 in progress · 📋 planned. No dates: the order is firm, the timing is not.
Non-original features are opt-in where they change gameplay; display and input improvements may default on.
Where each feature of the PS3 game stands today, and the port-only features: [FEATURES.md](FEATURES.md). What is broken
or unfinished: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

[Release criteria](RELEASE-CRITERIA.md) say when a tag is a preview and when the port counts as playable.

## 1. The first level, then the campaign, playable at speed  🔧

| | |
|---|---|
| ✅ | Boots to the front end and its menus (main menu, Mission Select, Exit to desktop); the intro movie plays |
| ✅ | **First level** (Corinth River) loads, runs and is drawn lit and in proportion; the briefing cutscene plays with its subtitles |
| 🔧 | **Performance:** in scripted runs, 23.3 frames/s over one 330 s run of the first level (2026-10-22) and a median of 32.6 frames/s in short turn-and-walk windows with the native post-processing (2026-10-29); the goal is the PS3's steady 30. Shaders compiled on first use pause the first minute of an area; a pipeline list cut those pauses in scripted runs, and the installer ships a starting list |
| 🔧 | **In-level play by hand:** the first level was played with a DualShock 4 (2026-10-22, slow then); scripted runs reached the first fight, cover and checkpoint saves |
| ✅ | **Update 1.29 as the base version:** the build targets it and reads its added archive and patch files; the patches' effect on the game data is not checked yet |
| 🔧 | **Saves:** checkpoint saves are written in the first level; loading one back is not checked yet |
| 🔧 | **Audio and movies:** menu and in-game sound and music play; the intro movie plays (the other 27 are not tried yet); sound is mixed down to stereo |
| 🔧 | **Motion-control sections** (valves, charges) without motion sensors: a right-stick stand-in is being tested |
| 📋 | **The whole campaign, start to finish:** only the first level has been played so far |
| 🔧 | **Installer and portable zip** (Windows): check your own disc dump, the 1.29 update and the decrypted EBOOT, then build the port on your machine with a bundled compiler; nothing of the game is shipped or downloaded. Versioned as pre-releases (current <!-- version -->[v0.1.4](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.4)<!-- /version -->) |

## 2. PC display and settings  🔧

- 🔧 Windowed, borderless and exclusive fullscreen, chosen in the installer or the launcher, and Alt+Enter (tried under Proton only)
- ✅ Motion blur off by default while the port runs below 30 frames/s, with a switch to turn it back on
- 📋 Field of view, motion blur strength and bloom as settings on the game's own Display page
- 📋 Widescreen and ultrawide: the view follows the window's shape, the HUD, menus and movies stay 16:9 and centred
- 📋 60 frames/s as an option (some of the game's timing breaks above 30)
- 📋 Surround sound (5.1 and 7.1 output)

## 3. Controls  🔧

- 🔧 Gamepads through SDL3: a DualShock 4 was played by hand, with its motion sensor; Xbox and DualSense pads are in the code, not yet tried by hand
- 🔧 Button prompts for PlayStation 3, PlayStation 4/5, Xbox or keyboard, and an Original or Modern pad layout
- 🔧 A Keyboard page in the main menu that saves key choices (checked in scripted runs only)
- 📋 **Keyboard and mouse** play

## 4. Multiplayer  📋

- 📋 Skirmish against bots, offline
- 📋 Online Warzone through a self-hosted server only: no server is preset, and the port goes online only when you choose online play
- 📋 A two-player campaign (Killzone 2 on PS3 has none): feasibility first

## 5. Later  📋

- 📋 Trophies, shown by the port only
- 📋 **More renderers:** once the game works end to end on Direct3D 12, review Vulkan and OpenGL beside it
- 📋 **Going native, after the game is playable:** replace the run-time layers step by step with native code where it pays off ([what is native today](HOW-IT-WORKS.md#what-kind-of-port-is-this))

## Not planned

- Distributing the game or any part of it: you always bring your own copy

Where each feature stands: [FEATURES.md](FEATURES.md).
