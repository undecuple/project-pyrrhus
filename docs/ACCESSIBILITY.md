# Accessibility

What the port offers today to adjust how the game is played, seen and read. Facts only: where something is missing,
this page says so. Last checked 2026-10-27; see also [KNOWN_ISSUES.md](KNOWN_ISSUES.md). No installer or portable zip
is released yet, so the installer and Start menu entries below describe the release builds, which you cannot download yet.

## Controls

- **Pad layouts.** Two layouts: Original (the game's own buttons, the default) and Modern, which changes the pad
  buttons only. Pick one in the installer, in the portable zip's first run, or later with the Start menu entry
  "Controls".
- **Pads.** PlayStation and Xbox pads through SDL3, with XInput as the fallback without it. A DualShock 4 was played by
  hand; Xbox and DualSense pads have not been tried by hand yet.
- **Keyboard.** The main menu has a Keyboard page that saves key choices to `keybinds.ini` (checked in scripted runs
  so far, not yet by hand). Mouse look is in, with its own sensitivity, zoomed sensitivity and inverted Y
  (`gameplay.ini`, `[mouse]`); not yet tried by hand.
- **Crouch, cover and aim assist.** The port can make crouch and take cover toggles (tap to start, tap again to stop)
  instead of hold, and can switch the aim assist off. All three are off or original by default; set them in
  `gameplay.ini` next to `keybinds.ini` (`crouch_toggle = 1`, `cover_toggle = 1`, `aim_assist = off`; see BUILDING.md for
  the `KZ2_*` variables). There is no in-game page for them yet.
- **Not yet:** remapping single pad buttons, and the game's own controls menu (sensitivity, invert Y).

## Button prompts

The button pictures the game shows can follow the pad in use (Auto) or be fixed to one set: PS3, PS4/PS5, Xbox or
Keyboard. Pick it in the installer, in the portable zip's first run, with the Start menu entry "Button prompts", or
in `keybinds.ini` under `[prompts]`. Known problem: in the PS4/PS5 set, the START and SELECT labels can show as boxes.

## Display

- **Window modes.** Borderless window (the default for a new install), windowed or fullscreen: pick one in the
  installer, in the portable zip's first run or with the Start menu entry "Display". Alt+Enter switches between
  borderless and a window while playing; a `display.ini` you already have keeps its mode.
- **Motion blur** is off by default (it looks doubled below 30 frames per second); a switch turns it back on.
- **Not yet:** the game's own brightness and display options menu.

## Subtitles and text

- **Subtitles.** The game's own subtitles show in cutscenes (seen in the first level's briefing). The game's options
  menu, where the PS3 version turns them on or off, is not in the port yet, so they cannot be turned off for now.
- **Languages.** The game's language screen loads; only English has been tried.

## Installer and launcher

- The installer uses standard Windows controls and the Windows interface font for its text (the headings use the
  project's font). A Windows high-contrast theme turns off the installer's dark style, so the high-contrast colours
  apply.
- The launcher's questions and errors are standard Windows message boxes, which screen readers read.
- The installer's progress page shows the step and the elapsed time as text, not only as a bar.
