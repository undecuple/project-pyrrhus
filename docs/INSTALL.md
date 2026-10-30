# Getting it, in detail

**Pre-release <!-- version -->[v0.1.6](https://github.com/undecuple/project-pyrrhus/releases/tag/v0.1.6)<!-- /version -->:** a Windows installer (recommended) and
a portable zip, on the [releases page](https://github.com/undecuple/project-pyrrhus/releases) with a `.sha256` file for each and `SHA256SUMS`. They check your
own disc dump (a folder or a decrypted ISO file), the 1.29 update and the decrypted EBOOT ([what each must
contain](GETTING-FILES.md)), then
translate and build the game's code on your own machine with a bundled compiler. No game code, assets or keys are ever
shipped or downloaded. Do not install into a OneDrive folder (a precaution from a problem reported on Project Helghast: OneDrive would sync the build's thousands of files
while they are written), and keep your game files on this device (in OneDrive: "Always keep on this device"); the
setup refuses both. You can also build the port yourself (see [BUILDING.md](BUILDING.md)). It is partly playable: the first level can be
played with a pad (a scripted run gives about 23 frames per second, the PS3 30; hand play is not measured), and the
rest of the campaign has not been tried. What changed in each
version: [CHANGELOG.md](../CHANGELOG.md).

A first release that calls itself playable waits for the conditions in [RELEASE-CRITERIA.md](RELEASE-CRITERIA.md).
Until then every release is a pre-release. There is no date for it.

Requirements, in short: your own Killzone 2 disc (US, BCUS98116) dumped as a folder, the 1.29 update, and the decrypted EBOOT from your own
copy; a Direct3D 12 GPU. The hardware figures are estimates, provisional until the game runs at full speed. Details: [requirements.md](requirements.md);
what each folder must hold and what the first-run check prints: [GETTING-FILES.md](GETTING-FILES.md).
