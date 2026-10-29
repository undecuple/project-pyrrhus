# Feature parity

How far the port is, feature by feature, against the PS3 game. Statuses: works, partial, in progress, not yet.

## The PS3 game

| Area | Feature | Detail | Status |
|---|---|---|---|
| Campaign | Intro movies and cutscene videos | 28 H.264 720p AVIs with AC-3 5.1 (FFmpeg, LGPL DLLs): the intro movie plays with pictures and clean sound; its 5.1 track is mixed down to stereo (see Surround sound); the other movies are not yet checked | partial |
| Campaign | Title screen and main menu | language select, main menu, New Campaign and difficulty | partial |
| Campaign | Mission 1 loads and runs |  | partial |
| Campaign | In-level play (move, aim, fire, cover) | gamepad | partial |
| Campaign | Full campaign start to finish | all missions, checkpoints, cutscenes | not yet |
| Campaign | SIXAXIS motion sections | valve wheels, charges | in progress |
| Campaign | Checkpoint save and load | cellSaveDataUserAutoSave/AutoLoad | partial |
| Audio | Sound and music | cellAudio, XVAG sound banks | partial |
| Audio | Surround sound (5.1 / 7.1 output) | the PS3 outputs 5.1 and 7.1; the port mixes everything down to stereo (cellAudio opens a 2-channel Windows output and folds the 8-channel port into it) | not yet |
| Options | Settings and controls menus |  | partial |
| Multiplayer | Skirmish (offline bots) |  | not yet |
| Multiplayer | Online Warzone | self-hosted only (the project's online rules) | not yet |
| Other | Trophies |  | not yet |
| Other | Debug menu as a test aid | TEST MENU (chapter/level/section/weapon select), pause-menu god/ammo | partial |
| Campaign | Pause menu | in-level pause screen | partial |
| Campaign | Mission Select and difficulty | mission list with picture, collectibles, difficulty | partial |
| Campaign | Full frame rate (30 fps in levels) | the PS3 holds about 30 frames per second | in progress |
| Other | Language selection and subtitles | language page, briefing subtitles | partial |

## Port work and port-only additions

| Area | Feature | Detail | Status |
|---|---|---|---|
| Toolchain | Patched ps3recomp toolkit | v0.18.0 + Project Helghast's (the Killzone 3 port's) general patch set + KZ2's own | works |
| Toolchain | PPU lift of the EBOOT | static recompilation of all PPU code | works |
| Toolchain | Windows build | MinGW x64 exe, memory-capped build | works |
| Toolchain | Update 1.29 EBOOT as the target | port the latest update | works |
| Boot | Boots under Proton to the first screen | loader, PPU start, SPURS, GCM init, first flip | works |
| Runtime | SPU jobs and SPURS | 23 SPU ELFs + 36 job modules | in progress |
| Runtime | RSX renderer (D3D12) | deferred renderer, 1280x720 2x MSAA | partial |
| Data | Game data access (PSARC, case-duplicate trees) | data_ps3.psarc v1.3, 3,444 unique names; 1.29 added_data + patch_data | partial |
| Data | .core resources (RTTIBin<1.58>) | core.py decodes KZ2's resources | partial |
| Data | Saves (PROFILE/CHECKPNT/SECTION.DAT) | map and stage the game's save files | partial |
| Front end | Front-end page engine (SVML menus) | the game's kin/*.jsp pages from the psarc (interface/svo/svml/<lang>/kin), drawn by the SVO browser | partial |
| Enhancement | Gyro stand-in for SIXAXIS | ENHANCEMENT: stick or mouse | in progress |
| Enhancement | Display modes | ENHANCEMENT: windowed, borderless, exclusive fullscreen, Alt+Enter, display.ini | in progress |
| Enhancement | Gamepads: PlayStation and Xbox | ENHANCEMENT: pads through SDL3: DualShock 4 tried by hand, with its motion sensor; Xbox and DualSense pads in code only | partial |
| Enhancement | Button prompt choice and pad layouts | ENHANCEMENT: PS3, PS4/PS5, Xbox or keyboard prompt symbols; Original or Modern button layout | partial |
| Enhancement | Gameplay options: aim assist switch, crouch and cover toggles | ENHANCEMENT, all off or original by default: gameplay.ini [gameplay] aim_assist auto|on|off, crouch_toggle, cover_toggle (KZ2_AIM_ASSIST / KZ2_CROUCH_TOGGLE / KZ2_COVER_TOGGLE) | partial |
| Enhancement | Movie playback through FFmpeg | ENHANCEMENT: movies decoded by FFmpeg LGPL decoders in separate DLLs | partial |
| Enhancement | Reuse an existing RPCS3 install | ENHANCEMENT: the setup can find an RPCS3 install and reuse its game files, with an optional, separate save copy | in progress |
| Enhancement | Launcher and window controls | ENHANCEMENT: launcher (pad layout, display), window close shuts down cleanly | partial |
