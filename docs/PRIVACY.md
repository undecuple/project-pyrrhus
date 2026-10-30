# What goes online

Nothing unless you ask. The port does not start any connection of its own.

- **Version check, off by default.** The installer's "Check now" button and the portable zip's first run ask GitHub
  once, when you choose to, whether a newer release exists. With "Check for new versions" ticked, the launcher asks
  at most once a day. Each check is one anonymous request for this project's list of releases, with nothing about
  you, your computer or your game.
- **Updating, only when you say yes.** When a check finds a newer release, the launcher asks first. Only after a yes
  does it download that release's setup and its published checksum from this project's GitHub releases, check the
  file against the checksum, and start it for your install folder.

- **Project website** (`site/`): viewing it loads the Rajdhani font from Google Fonts, which sees your visit. The repository, installer and game do not.

Online multiplayer, if it comes, will only use a self-hosted server you choose.
