; Project Pyrrhus (Killzone 2 PC port): Inno Setup 6 script. From Project Helghast installer/kz3.iss (Project Helghast),
; adapted to Killzone 2: the 1.29 update, no shader warm-up tasks, no SPU build steps.
;
; Compiled with ISCC 6.7.3 under Proton (tools/release/wizard_test.sh compile; tools/release/vm_kit.sh build), wizard
; walked headless under Wine, silent install and uninstall run by tools/release/vm_test.py. Needs the release payload
; (tools/release/assemble_payload.py: kz2-setup\, ps3recomp\, port\, toolchain\, licenses\, the launcher
; "Project Pyrrhus.exe") and the headings font (FontDir, below).
;
;   iscc /DPayload=<payload dir> installer\kz2.iss      (output: installer\Output\; AppVersion = the payload's VERSION.txt)
;
; Silent install (no pages, no boxes): setup /VERYSILENT /SUPPRESSMSGBOXES /LOG=<file> [/DIR=<folder>]
;   [/DUMP=<folder with PS3_GAME, or a decrypted .iso> /UPDATE=<BCUS98116 folder> /EBOOT=<EBOOT.elf> [/JOBS=N]]: with /DUMP= the build runs
;   in setup as in the wizard (firstrun.py; the log goes next to setup.exe); without it nothing is built and the
;   first start asks. Silent uninstall (unins000.exe /VERYSILENT) keeps the saves.
;
; What it does: per-user install (no admin) into a folder the player picks; three pages for the player's own dump,
; 1.29 update and decrypted EBOOT (quick presence checks here; tools/release/firstrun_check.py runs the full check
; as the build's first step); runs tools/release/firstrun.py with one progress bar; desktop shortcut (checked by
; default), Start-menu entry and "Project page" link; a "portable install" option (saves and settings in the
; install folder); one install log next to setup.exe with Inno's own log merged in; an uninstaller that asks before
; deleting saves (default keep). It downloads nothing and copies nothing of the game. The welcome page's "Check now"
; runs tools/release/version_check.py once, only on that click: one anonymous GET of the latest-release JSON; a newer
; release opens its page in the browser only on a second click; offline = one line in the log. The finish page and
; the build-error dialog offer "Open log" and "Report a problem" (the issues page).
; Look: wizard images and icons from installer\art\ (tools/release/installer_art.py, the site's palette and fonts;
; our own artwork); native controls, no skin add-on. Texts in the site's voice: short, direct.

#ifndef Payload
  ; ASSUMPTION: where the payload assembly will put the tree
  #define Payload "..\build\release-payload"
#endif
; One version: the payload's VERSION.txt, which assemble_payload.py writes from installer/VERSION. A /DAppVersion
; on the command line must say the same.
#define VerH FileOpen(Payload + "\VERSION.txt")
#if !VerH
  #error cannot read {#Payload}\VERSION.txt (assemble the payload first)
#endif
#define PayloadVersion Trim(FileRead(VerH))
#expr FileClose(VerH)
#ifndef AppVersion
  #define AppVersion PayloadVersion
#endif
#if AppVersion != PayloadVersion
  #error AppVersion {#AppVersion} is not the payload's VERSION.txt {#PayloadVersion}
#endif
#ifndef FontDir
  ; Rajdhani Bold for the headings: fetched and hash-checked against installer/art/art.json
  ; by tools/release/installer_art.py --fetch-fonts (SIL OFL 1.1); never committed
  #define FontDir "..\work\release\fonts"
#endif
#if VER < EncodeVer(6,6,0)
  #error Inno Setup 6.6.0 or later is needed (WizardStyle dark; tested with 6.7.3)
#endif
; The licence page shows LICENSE with each paragraph on one line: the file is hard-wrapped at about 72 columns and
; the memo wraps again at its own width, which left one or two words on every other line (KZ3 wizard test).
; Done here at compile time, so setup loads the file the normal way (a runtime Text reset lost the dark style's text
; colour). Written to %TEMP% because the script folder may be read-only.
#define LicSrc Payload + "\licenses\LICENSE.txt"
#define LicOut AddBackslash(GetEnv("TEMP")) + "kz2-wizard-licence.txt"
#define LicText ""
#define LicLine ""
#define LicPara 1
#define LicH 0
#sub LicAdd
  #define LicLine = Trim(FileRead(LicH))
  #if LicLine == ""
    #if !LicPara
      #define public LicText = LicText + NewLine + NewLine
    #endif
    #define public LicPara = 1
  #else
    #define public LicText = LicText + (LicPara ? "" : " ") + LicLine
    #define public LicPara = 0
  #endif
#endsub
#for {LicH = FileOpen(LicSrc); LicH && !FileEof(LicH); ""} LicAdd
#if LicH
  #expr FileClose(LicH)
#else
  #error cannot read the licence: {#LicSrc}
#endif
#expr SaveStringToFile(LicOut, LicText, 0, 1)
; One product name on every screen; AppId below never changes (its own GUID, not KZ3's)
#define AppName "Project Pyrrhus"
#define AppDirName "Project Pyrrhus"
; ProjectURL = the GitHub repository (issues, releases, source); SiteURL = the project page shown as text and
; opened by "Project page" (ASSUMPTION: the repository until a site exists)
#define ProjectURL "https://github.com/undecuple/project-pyrrhus"
#define SiteURL "https://github.com/undecuple/project-pyrrhus"
#define SiteText "github.com/undecuple/project-pyrrhus"
#define LauncherExe "Project Pyrrhus.exe"
#define FileBase "Project-Pyrrhus"
#define SetupBase "Project-Pyrrhus-setup"

[Setup]
AppId={{5C5D4C2E-8AE0-4446-BEC0-560BC45B6E20}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Project Pyrrhus contributors
AppPublisherURL={#SiteURL}
AppSupportURL={#ProjectURL}/issues
AppUpdatesURL={#ProjectURL}/releases
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
DefaultDirName={localappdata}\Programs\{#AppDirName}
; File times are stored in UTC and converted to the player's time zone on install. Inno's default keeps the compile
; machine's local time as is: a release built in UTC gave a player west of UTC every source file dated hours in the
; future, and ninja stopped with "manifest 'build.ninja' still dirty after 100 tries" (KZ3, a player's log,
; 2026-10-28, 3068397). firstrun.py also refuses future-dated port files (an install made by an older installer).
TimeStampsInUTC=yes
DisableDirPage=no
DefaultGroupName={#AppDirName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Dark by default (as KZ3's), not following the system. Inno 6.7.3 help (WizardStyle topic): forced dark uses
; the built-in dark style for pages, message boxes and task dialogs, and a dark native title bar where the system
; allows it; a Windows high-contrast theme (or /NOSTYLE) turns the custom style off, so high contrast still wins.
WizardStyle=modern dark
; Inno 6 hides the welcome page by default; it carries the notice and "Check now"
DisableWelcomePage=no
SetupLogging=yes
OutputBaseFilename={#SetupBase}
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\kz2-uninstall.ico
SetupIconFile=art\kz2-setup.ico
; Inno picks the closest size per DPI (100/125/150/200 %); relative to this script's folder
WizardImageFile=art\wizard-100.bmp,art\wizard-125.bmp,art\wizard-150.bmp,art\wizard-200.bmp
WizardSmallImageFile=art\header-100.bmp,art\header-125.bmp,art\header-150.bmp,art\header-200.bmp
WizardImageStretch=yes
; Beyond the installed files (KZ3's payload ~0.55 GB with the toolchain): the build folder, 1.1 GB measured for KZ3,
; plus 0.4 GB headroom. ASSUMPTION for KZ2 (a smaller EBOOT and no SPU lift: likely less); measure on a first build.
ExtraDiskSpaceRequired=1610612736
LicenseFile={#LicOut}

[Messages]
; Sentence-case headings, "licence" in our prose, "Setup" as Inno writes it
WizardLicense=Licence agreement
LicenseLabel3=Please read the following licence. You must accept it before continuing with the installation.
WizardSelectDir=Select destination location
WizardSelectTasks=Select additional tasks
WizardReady=Ready to install
WizardPreparing=Preparing to install
WizardUninstalling=Uninstall status
UninstallAppFullTitle=Uninstall %1
BrowseDialogTitle=Browse for folder
ButtonNewFolder=&Make new folder
DirExistsTitle=Folder exists
DirDoesntExistTitle=Folder does not exist
WelcomeLabel1=Project Pyrrhus {#AppVersion}
WelcomeLabel2=Built on your PC, from your own game.%n%nThis installs the port's sources, the patched ps3recomp toolkit and a compiler. Then it checks your Killzone 2 disc dump (BCUS98116), the 1.29 update and the decrypted EBOOT, and builds the game here: 5 to 30 minutes.%n%nNothing is downloaded. Nothing of the game is copied. What it builds holds the game's code in translated form: keep it to yourself.%n%nProject page: {#SiteText}
FinishedHeadingLabel=Setup is done
FinishedLabel=Project Pyrrhus is installed. Start it from the desktop or the Start menu.
FinishedLabelNoIcons=Project Pyrrhus is installed.
SelectTasksLabel2=Pick what Setup does after copying the files. Everything online is off unless you tick it.

[CustomMessages]
; The tasks list has no spacing property: a line break before each later group label gives the gap.
; The shortcut and the portable choice share one "Install:" group (KZ3: the whole list fits without scrolling)
GrpInstall=Install:
GrpBuild=%nBuild:
GrpOnline=%nOnline (opt-in):
GrpPrompts=%nButton prompts:
GrpDisplay=%nDisplay:

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "{cm:GrpInstall}"
Name: "portable"; Description: "&Portable: saves and settings in the install folder (else in %APPDATA%)"; GroupDescription: "{cm:GrpInstall}"; Flags: unchecked
Name: "buildnow"; Description: "&Build now (else the first start builds)"; GroupDescription: "{cm:GrpBuild}"
Name: "modernpad"; Description: "Use the &Modern pad layout (pad buttons only; unchecked = the game's original controls)"; GroupDescription: "{cm:GrpInstall}"; Flags: unchecked
; Button prompts: one radio choice (exclusive), written to [controls] prompts; the names are the ones the game reads
Name: "promptsauto"; Description: "Auto: follow the pad in use"; GroupDescription: "{cm:GrpPrompts}"; Flags: exclusive
Name: "promptsps3"; Description: "PS3"; GroupDescription: "{cm:GrpPrompts}"; Flags: exclusive unchecked
Name: "promptsps4"; Description: "PS4 / PS5"; GroupDescription: "{cm:GrpPrompts}"; Flags: exclusive unchecked
Name: "promptsxbox"; Description: "Xbox"; GroupDescription: "{cm:GrpPrompts}"; Flags: exclusive unchecked
Name: "promptskeyboard"; Description: "Keyboard"; GroupDescription: "{cm:GrpPrompts}"; Flags: exclusive unchecked
; Display: one radio choice (exclusive), written to [display] mode; the names are the ones the game reads (KZ2_DISPLAY)
Name: "displaywindowed"; Description: "Windowed"; GroupDescription: "{cm:GrpDisplay}"; Flags: exclusive
Name: "displayborderless"; Description: "Borderless window"; GroupDescription: "{cm:GrpDisplay}"; Flags: exclusive unchecked
Name: "displayfullscreen"; Description: "Fullscreen"; GroupDescription: "{cm:GrpDisplay}"; Flags: exclusive unchecked
Name: "checkupdates"; Description: "&Check for new versions: one anonymous request to GitHub, at most once a day"; GroupDescription: "{cm:GrpOnline}"; Flags: unchecked

[Files]
; For "Check now" on the welcome page, before anything is installed: the bundled Python and version_check.py,
; extracted to {tmp} on the click only. Listed first so they sit at the start of the solid stream (ASSUMPTION: entry
; order = stream order, so the click does not unpack the whole payload); Inno stores the duplicate data once.
Source: "{#Payload}\toolchain\python\*"; DestDir: "{tmp}\vcheck\python"; Flags: dontcopy recursesubdirs
Source: "{#Payload}\kz2-setup\release\version_check.py"; DestDir: "{tmp}\vcheck"; Flags: dontcopy
; The manual EBOOT page asks rpcs3_import.py whether the picked file is still encrypted (before anything is installed)
Source: "{#Payload}\kz2-setup\release\rpcs3_import.py"; DestDir: "{tmp}\vcheck"; Flags: dontcopy
Source: "{#Payload}\kz2-setup\release\rpcs3_locate.py"; DestDir: "{tmp}\vcheck"; Flags: dontcopy
; run.cmd is the portable zip's entry point (firstrun.py --interactive); the installed copy uses the launcher
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "run.cmd"; Flags: ignoreversion recursesubdirs createallsubdirs
; The wildcard above leaves out dot files (ISCC under Wine sees them as hidden; VM kit pre-flight): the toolkit's
; patch-set stamp (firstrun.py reads it) is listed by name. assemble_payload.py drops .gitignore files.
Source: "{#Payload}\ps3recomp\.kz2-patchset"; DestDir: "{app}\ps3recomp"; Flags: ignoreversion
; Apps & features icon (UninstallDisplayIcon) and the Start menu's Uninstall entry
Source: "art\kz2-uninstall.ico"; DestDir: "{app}"; Flags: ignoreversion
; Headings font: a temporary file for setup's own process only (AddFontResourceEx FR_PRIVATE in InitializeSetup),
; never installed on the system. The payload itself carries fonts\Rajdhani-Medium.ttf and -Bold.ttf (KZ3's error
; notice fonts; firstrun.py and the launcher copy them next to build\kz2.exe) and licenses\Rajdhani-OFL.txt
; (assemble_payload.py FONTS, hash-checked against art\art.json like this one)
; The payload also carries runtime\SDL3.dll (zlib; licenses\SDL3-LICENSE.txt): installed by the payload line above with
; the rest of {app}, copied next to build\kz2.exe by firstrun.py and the launcher (place_sdl3); the game loads it for native pads.
Source: "{#FontDir}\Rajdhani-Bold.ttf"; Flags: dontcopy

[InstallDelete]
; Install over an earlier version: the payload's own folders are replaced whole, so a file a newer version
; dropped cannot linger and be compiled or run. Inno keeps each file's own time stamp, so ninja recompiles only the
; sources that changed. Never listed here: build (the lift and objects; firstrun.py's markers decide what re-runs),
; vfs (the link to the dump), logs, gamedata, cache, kz2-install.ini.
Type: filesandordirs; Name: "{app}\kz2-setup"
Type: filesandordirs; Name: "{app}\port"
Type: filesandordirs; Name: "{app}\ps3recomp"
Type: filesandordirs; Name: "{app}\toolchain"

[Dirs]
Name: "{app}\logs"

[INI]
; Read by the launcher (launch.py read_ini). Paths go to build\paths.json, written by firstrun.py.
Filename: "{app}\kz2-install.ini"; Section: "install"; Key: "portable"; String: "1"; Tasks: portable
Filename: "{app}\kz2-install.ini"; Section: "install"; Key: "portable"; String: "0"; Tasks: not portable
Filename: "{app}\kz2-install.ini"; Section: "online"; Key: "check_updates"; String: "1"; Tasks: checkupdates
Filename: "{app}\kz2-install.ini"; Section: "online"; Key: "check_updates"; String: "0"; Tasks: not checkupdates
; [controls] layout: original is the default; the launcher's --controls changes it later
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "layout"; String: "modern"; Tasks: modernpad
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "layout"; String: "original"; Tasks: not modernpad
; [controls] prompts (auto when nothing else is ticked); the launcher's --prompts changes it later
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "prompts"; String: "ps3"; Tasks: promptsps3
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "prompts"; String: "ps4"; Tasks: promptsps4
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "prompts"; String: "xbox"; Tasks: promptsxbox
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "prompts"; String: "keyboard"; Tasks: promptskeyboard
Filename: "{app}\kz2-install.ini"; Section: "controls"; Key: "prompts"; String: "auto"; Tasks: not promptsps3 and not promptsps4 and not promptsxbox and not promptskeyboard
; [display] mode (windowed when nothing else is ticked); the launcher's --display changes it later
Filename: "{app}\kz2-install.ini"; Section: "display"; Key: "mode"; String: "borderless"; Tasks: displayborderless
Filename: "{app}\kz2-install.ini"; Section: "display"; Key: "mode"; String: "fullscreen"; Tasks: displayfullscreen
Filename: "{app}\kz2-install.ini"; Section: "display"; Key: "mode"; String: "windowed"; Tasks: not displayborderless and not displayfullscreen

[Icons]
Name: "{group}\{#AppDirName}"; Filename: "{app}\{#LauncherExe}"; WorkingDir: "{app}"
; --repair: launch.py checks the install against manifest.json, re-runs the game-file checks, rebuilds what changed
Name: "{group}\Verify and rebuild"; Filename: "{app}\{#LauncherExe}"; Parameters: "--repair"; WorkingDir: "{app}"
; --controls: asks Original (default) or Modern pad layout, writes [controls] layout in kz2-install.ini
Name: "{group}\Controls"; Filename: "{app}\{#LauncherExe}"; Parameters: "--controls"; WorkingDir: "{app}"
; --prompts: moves to the next button prompt set (Auto, PS3, PS4/PS5, Xbox, Keyboard), writes [controls] prompts
Name: "{group}\Button prompts"; Filename: "{app}\{#LauncherExe}"; Parameters: "--prompts"; WorkingDir: "{app}"
; --display: moves to the next display mode (Windowed, Borderless, Fullscreen), writes [display] mode
Name: "{group}\Display"; Filename: "{app}\{#LauncherExe}"; Parameters: "--display"; WorkingDir: "{app}"
Name: "{group}\Project page"; Filename: "{#SiteURL}"
Name: "{group}\Uninstall {#AppDirName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\kz2-uninstall.ico"
Name: "{autodesktop}\{#AppDirName}"; Filename: "{app}\{#LauncherExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#LauncherExe}"; Description: "Start {#AppDirName}"; Flags: nowait postinstall skipifsilent; Check: BuildSucceeded
Filename: "{code:InstallLogPath}"; Description: "Open the install log"; Flags: shellexec postinstall skipifsilent unchecked
Filename: "{#ProjectURL}/issues"; Description: "Report a problem (attach the install log)"; Flags: shellexec postinstall skipifsilent unchecked; Check: BuildBroke
Filename: "{#SiteURL}"; Description: "Open the project page ({#SiteText})"; Flags: shellexec postinstall skipifsilent unchecked

[UninstallDelete]
; The generated derivative goes with the port; the player's dump, update and RPCS3 folder are never touched.
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\logs"
; The game's writable VFS root (launch.py ensure_vfs): vfs\PS3_GAME is a directory junction to the
; player's dump and is removed as a link by CurUninstallStepChanged(usUninstall) before this list runs; nothing
; here recurses into vfs itself, so the dump is never reached even when the junction could not be removed.
Type: filesandordirs; Name: "{app}\vfs\psarc-cache"
Type: filesandordirs; Name: "{app}\vfs\cache"
Type: files; Name: "{app}\vfs\link.json"
Type: dirifempty; Name: "{app}\vfs"
; Portable layout: the runtime's caches sit in the install folder (saves: AskDeleteSaves).
Type: filesandordirs; Name: "{app}\cache"
Type: files; Name: "{app}\kz2-install.ini"
Type: files; Name: "{app}\kz2-uninstall.ico"
; What the launcher and firstrun.py write into {app} that Inno did not install (adapted from Project Helghast, KZ3
; Project Helghast v0.1.1: an uninstall left the folder behind): the first-run log the launcher names (launch.FIRSTRUN_LOG) with its
; time-stamped earlier copies (firstrun.rotate), and a setup log written here. tools/release/test_uninstall_covers.py
; keeps this list complete.
Type: files; Name: "{app}\{#FileBase}-firstrun*.log"
Type: files; Name: "{app}\{#SetupBase}*.log"
; A decrypted disc ISO's files, copied out of it by firstrun.py (iso_dest: {app}\game\disc). The player's ISO itself
; stays where it is, so this copy goes with the port (vfs\PS3_GAME, the link to it, is removed first).
Type: filesandordirs; Name: "{app}\game"
; KZ3's uninstall test: Python's byte-code caches (kz2-setup\release\__pycache__, written when the launcher imports
; firstrun.py) kept the install folder alive, and caches in the data folder outlived a "keep my saves" answer.
; Caches are not saves: they go either way; gamedata stays unless asked.
Type: filesandordirs; Name: "{app}\kz2-setup"
; The VM kit pre-flight: the SPU lift imports the toolkit's scripts, leaving ps3recomp\tools\__pycache__ behind after
; an uninstall. The payload's own folders go whole (as [InstallDelete] replaces them whole).
Type: filesandordirs; Name: "{app}\ps3recomp"
Type: filesandordirs; Name: "{app}\port"
Type: filesandordirs; Name: "{app}\toolchain"
Type: filesandordirs; Name: "{app}\re"
Type: filesandordirs; Name: "{userappdata}\{#AppDirName}\cache"
; The runtime's shader cache and pipeline record (scratch\rsx_shader_cache_v*, pso-template-own.bin) and its debug
; dumps sit in scratch\ under the working folder: caches, not saves.
Type: filesandordirs; Name: "{userappdata}\{#AppDirName}\scratch"
Type: filesandordirs; Name: "{app}\scratch"
; vkd3d-proton's own cache when the launcher's VKD3D_SHADER_CACHE_PATH is not used (an older launcher, a direct start):
; vkd3d-proton.cache, or vkd3d-proton.kz2.exe.cache in newer Proton builds (seen with Proton GE in a Wine test)
Type: files; Name: "{userappdata}\{#AppDirName}\vkd3d-proton*.cache*"
Type: files; Name: "{app}\vkd3d-proton*.cache*"
Type: dirifempty; Name: "{userappdata}\{#AppDirName}"

[Code]
var
  SourcePage: TInputOptionWizardPage;
  RpcsPage, DumpPage, UpdatePage: TInputDirWizardPage;
  EbootPage: TInputFileWizardPage;
  { Game paths used by the build: the pages' values, or what rpcs3_import.py found in the player's RPCS3 folder }
  DumpDir, UpdateDir, EbootFile, RpcsRoot: String;
  DumpInfo: TNewStaticText;
  DumpIsoBtn: TNewButton;
  TrilogyNoted: Boolean;
  AllowOutside, BuildSkipped: Boolean;
  BuildOK, BuildStopped: Boolean;
  StopBtn: TNewButton;
  StopFile: String;
  OurLog: String;
  CheckBtn, ReleaseBtn: TNewButton;
  CheckLbl: TNewStaticText;
  ReleaseURL: String;

function LogName: String;
begin
  { <setup name>.log, e.g. Project-Pyrrhus-setup.log next to the started setup.exe }
  Result := ChangeFileExt(ExtractFileName(ExpandConstant('{srcexe}')), '.log');
end;

function InstallLogPath(Param: String): String;
begin
  if OurLog <> '' then Result := OurLog
  else Result := AddBackslash(ExpandConstant('{src}')) + LogName;
end;

function BuildSucceeded: Boolean;
begin
  Result := BuildOK or not WizardIsTaskSelected('buildnow');
end;

function BuildFailed: Boolean;
begin
  Result := not BuildSucceeded;
end;

{ "Report a problem" on the finish page: a failed build, not one the player stopped }
function BuildBroke: Boolean;
begin
  Result := BuildFailed and not BuildStopped;
end;

function Field(Line, Key: String): String;
var
  P: Integer;
begin
  Result := '';
  P := Pos(' ' + Key + '=', Line);
  if P = 0 then Exit;
  Result := Copy(Line, P + Length(Key) + 2, MaxInt);
  P := Pos(' ', Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
end;

procedure OpenURL(URL: String);
var
  ErrorCode: Integer;
begin
  ShellExec('open', URL, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure ReleaseClick(Sender: TObject);
begin
  { The download happens in the browser, from the release page, on the player's own click. }
  if ReleaseURL <> '' then OpenURL(ReleaseURL);
end;

procedure CheckNowClick(Sender: TObject);
var
  Py, Script, Res, L, Status: String;
  Lines: TArrayOfString;
  RC: Integer;
begin
  { One click = consent for one check. Nothing is sent but the request (version_check.py docstring). }
  CheckBtn.Enabled := False;
  CheckLbl.Caption := 'Asking GitHub...';
  WizardForm.Refresh;
  ExtractTemporaryFiles('{tmp}\vcheck\*');
  { ASSUMPTION: ExtractTemporaryFiles keeps the entries' relative folders under the temp folder (Inno 6 help); untested. }
  Py := ExpandConstant('{tmp}\vcheck\python\python.exe');
  Script := ExpandConstant('{tmp}\vcheck\version_check.py');
  Res := ExpandConstant('{tmp}\vcheck.result');
  L := '';
  if Exec(Py, '"' + Script + '" --current "{#AppVersion}" --timeout 8 --result-file "' + Res + '"', '',
          SW_HIDE, ewWaitUntilTerminated, RC) then
    if LoadStringsFromFile(Res, Lines) and (GetArrayLength(Lines) >= 1) then L := Lines[0];
  { The one log line (merged into the install log next to setup.exe); offline is not an error dialog. }
  if L = '' then L := 'VERSION status=error (the check could not run)';
  Log('version check: ' + L);
  Status := Field(L, 'status');
  if Status = 'newer' then begin
    ReleaseURL := Field(L, 'url');
    if (ReleaseURL = '') or (ReleaseURL = '-') then ReleaseURL := '{#ProjectURL}/releases';
    CheckLbl.Caption := 'Version ' + Field(L, 'latest') + ' is out (this setup is {#AppVersion}).';
    ReleaseBtn.Visible := True;
  end else if Status = 'current' then
    CheckLbl.Caption := 'This is the latest version ({#AppVersion}).'
  else
    CheckLbl.Caption := 'GitHub did not answer (offline or blocked). Nothing else changes.';
  CheckBtn.Enabled := True;
end;

procedure ShowBuildError;
var
  R: Integer;
begin
  { Shown while the build page is still up (its header, not "Installing", behind it). Three labels
    for Yes/No/Cancel: the third is "Close" (KZ3 wizard test). }
  repeat
    R := TaskDialogMsgBox('The build did not finish.',
      { A path has no spaces to wrap at: it ran past the dialog's edge (KZ3 wizard test); "Open log" opens it }
      'The log is at:' + #13#10 + MinimizePathName(InstallLogPath(''), WizardForm.Font, ScaleX(380)) + #13#10 + #13#10 +
      'Start Project Pyrrhus again: it resumes where it stopped. To report it, attach this log on the issues ' +
      'page; it holds no personal folders and nothing of the game.',
      mbError, MB_YESNOCANCEL, ['Open log', 'Report a problem', 'Close'], 0);
    if R = IDYES then OpenURL(InstallLogPath(''))
    else if R = IDNO then OpenURL('{#ProjectURL}/issues');
  until (R <> IDYES) and (R <> IDNO);
end;

const
  FR_PRIVATE = $10;
  HeadFont = 'Rajdhani';

var
  HeadFontFile: String;

function AddFontResourceEx(FileName: String; Flags: Cardinal; Reserved: Integer): Integer;
  external 'AddFontResourceExW@gdi32.dll stdcall';
function RemoveFontResourceEx(FileName: String; Flags: Cardinal; Reserved: Integer): Integer;
  external 'RemoveFontResourceExW@gdi32.dll stdcall';

{ Rajdhani Bold for the headings only; body text, buttons and pickers keep the Windows UI font
  for readability, DPI, high contrast and screen readers. Loaded for this process only (FR_PRIVATE). }
function InitializeSetup: Boolean;
var
  F: String;
begin
  Result := True;
  try
    ExtractTemporaryFile('Rajdhani-Bold.ttf');
    F := ExpandConstant('{tmp}\Rajdhani-Bold.ttf');
    if AddFontResourceEx(F, FR_PRIVATE, 0) > 0 then HeadFontFile := F;
  except
    HeadFontFile := '';
  end;
  if HeadFontFile <> '' then Log('headings font: Rajdhani loaded (private)')
  else Log('headings font: Rajdhani did not load; the headings keep the Windows UI font');
end;

procedure DeinitializeSetup;
begin
  if HeadFontFile <> '' then RemoveFontResourceEx(HeadFontFile, FR_PRIVATE, 0);
end;

procedure HeadingFont(F: TFont; Size: Integer);
begin
  F.Name := HeadFont;
  F.Style := [fsBold];
  if Size > 0 then F.Size := Size;
end;

procedure ApplyHeadingFonts;
begin
  if HeadFontFile = '' then Exit;
  { Rajdhani is set smaller than Segoe UI at the same point size (lower x-height); a few points more keeps the
    titles' visual size. ASSUMPTION: sizes checked in KZ3's Proton screenshots, not on Windows yet. }
  HeadingFont(WizardForm.WelcomeLabel1.Font, 0);
  HeadingFont(WizardForm.FinishedHeadingLabel.Font, 0);
  HeadingFont(WizardForm.PageNameLabel.Font, WizardForm.PageNameLabel.Font.Size + 2);
  { The label keeps the Windows font's height: at +2 pt Rajdhani's descenders (g, y, p) were cut off (KZ3 wizard
    test). Give it room above and below; the description moves down a little. }
  WizardForm.PageNameLabel.Top := WizardForm.PageNameLabel.Top - ScaleY(2);
  WizardForm.PageNameLabel.Height := WizardForm.PageNameLabel.Height + ScaleY(6);
  WizardForm.PageDescriptionLabel.Top := WizardForm.PageDescriptionLabel.Top + ScaleY(2);
end;

{ '' when the disc archive is there, as USRDIR\data_ps3.psarc or as the parts a FAT32 drive makes of a file over
  4 GiB (data_ps3.psarc.66600, .66601, ... in order, no gap; read as one file), else the message naming the missing
  file. Usr = the dump's USRDIR with a trailing backslash. As firstrun_check.py split_parts (from Project Helghast v0.1.3). }
function ArchiveProblem(Usr: String): String;
var
  N, K: Integer;
begin
  Result := '';
  if FileExists(Usr + 'data_ps3.psarc') then Exit;
  N := 66600;
  while FileExists(Usr + 'data_ps3.psarc.' + IntToStr(N)) do N := N + 1;
  if N > 66600 then begin
    { parts 66600 up to N-1 exist; a later one means the numbering has a gap at N }
    for K := N + 1 to N + 40 do
      if FileExists(Usr + 'data_ps3.psarc.' + IntToStr(K)) then begin
        Result := 'PS3_GAME\USRDIR\data_ps3.psarc.' + IntToStr(N) + ' is missing (the archive is split into parts ' +
          'data_ps3.psarc.66600, .66601, ... that must be numbered without a gap).';
        Exit;
      end;
    Exit;
  end;
  for K := 66601 to 66640 do
    if FileExists(Usr + 'data_ps3.psarc.' + IntToStr(K)) then begin
      Result := 'PS3_GAME\USRDIR\data_ps3.psarc.66600 is missing (the archive is split into parts ' +
        'data_ps3.psarc.66600, .66601, ... that must be numbered without a gap).';
      Exit;
    end;
  Result := 'PS3_GAME\USRDIR\data_ps3.psarc is missing.';
end;

{ True when Dir is OneDrive's folder or inside it (the OneDrive, OneDriveConsumer and OneDriveCommercial environment
  variables, case-insensitive prefix match on whole path components; silent installs too). Adapted from Project
  Helghast (the Killzone 3 PC port, same author, MIT), Project Helghast v0.1.2; the same rule as firstrun_check.py O1. }
function InOneDrive(Dir: String): Boolean;
var
  D, B: String;
  I: Integer;
  Vars: array of String;
begin
  Result := False;
  D := Lowercase(RemoveBackslashUnlessRoot(Dir));
  SetArrayLength(Vars, 3);
  Vars[0] := 'OneDrive';
  Vars[1] := 'OneDriveConsumer';
  Vars[2] := 'OneDriveCommercial';
  for I := 0 to 2 do begin
    B := Lowercase(RemoveBackslashUnlessRoot(GetEnv(Vars[I])));
    if (B <> '') and ((D = B) or (Pos(B + '\', D) = 1)) then
      Result := True;
  end;
end;

{ '' when Dir (the final install folder) is acceptable, else the reason }
function InstallDirProblem(Dir: String): String;
var
  D: String;
begin
  Result := '';
  D := RemoveBackslashUnlessRoot(Dir);
  if InOneDrive(D) then
    Result := 'The folder ' + D + ' is inside OneDrive, which syncs the build''s thousands of files while it runs ' +
      'and locks them. Choose a folder outside OneDrive (the default, %LOCALAPPDATA%\Programs\{#AppDirName}, is fine).';
end;

{ Before any file is written, for the wizard and for silent installs with /DIR= alike (a silent install never clicks
  Next on the folder page) }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := InstallDirProblem(ExpandConstant('{app}'));
  if Result <> '' then Log('install folder refused: ' + Result);
end;

{ Dump and update pages (adapted from Project Helghast v0.1.2): a pick one or two levels too deep is stepped
  up, and the disc's TITLE_ID is read from PARAM.SFO and named. Quick checks only; firstrun_check.py (D1-D3, U1-U3,
  E1) runs as the build's first step and repeats them. }
function EndsWithName(Dir, Name: String): Boolean;
begin
  Result := CompareText(ExtractFileName(RemoveBackslashUnlessRoot(Dir)), Name) = 0;
end;

{ The pick is a decrypted disc ISO: an existing file whose name ends in .iso (adapted from Project Helghast, KZ3
  v0.1.2). The page does not open it (Pascal here cannot seek in a 7 GB file); firstrun_check.py reads the image's
  PARAM.SFO, EBOOT.BIN and data_ps3.psarc in the first build step and says "this ISO is encrypted; use a decrypted
  dump" or what else is wrong, then firstrun.py copies its game files into the install folder (game\disc). }
function IsIsoPick(Path: String): Boolean;
begin
  Path := Trim(Path);
  Result := (Path <> '') and (CompareText(ExtractFileExt(Path), '.iso') = 0) and FileExists(Path) and not DirExists(Path);
end;

{ A pick of PS3_GAME or PS3_GAME\USRDIR becomes the folder that holds PS3_GAME (as firstrun_check.py resolve_dump) }
function ResolveDump(Dir: String): String;
var
  D: String;
begin
  D := RemoveBackslashUnlessRoot(Trim(Dir));
  Result := D;
  if IsIsoPick(D) then Exit;
  if (D = '') or FileExists(AddBackslash(D) + 'PS3_GAME\PARAM.SFO') then Exit;
  if EndsWithName(D, 'USRDIR') and EndsWithName(ExtractFileDir(D), 'PS3_GAME') then D := ExtractFileDir(D);
  if EndsWithName(D, 'PS3_GAME') then begin
    D := RemoveBackslashUnlessRoot(ExtractFileDir(D));
    if FileExists(AddBackslash(D) + 'PS3_GAME\PARAM.SFO') then Result := D;
  end;
end;

{ A pick of USRDIR inside the update folder becomes the update folder (as firstrun_check.py resolve_update) }
function ResolveUpdate(Dir: String): String;
var
  D: String;
begin
  D := RemoveBackslashUnlessRoot(Trim(Dir));
  Result := D;
  if (D <> '') and EndsWithName(D, 'USRDIR') and FileExists(AddBackslash(ExtractFileDir(D)) + 'PARAM.SFO') then
    Result := RemoveBackslashUnlessRoot(ExtractFileDir(D));
end;

{ Little-endian integer of Bytes bytes at the 0-based offset P of S; 0 past the end (the same reader as
  firstrun_check.py read_sfo) }
function SfoInt(S: AnsiString; P, Bytes: Integer): Integer;
var
  B: Integer;
begin
  Result := 0;
  if (P < 0) or (P + Bytes > Length(S)) then Exit;
  for B := Bytes - 1 downto 0 do Result := Result * 256 + Ord(S[P + B + 1]);
end;

{ A NUL-terminated string at the 0-based offset P of S, at most Max bytes }
function SfoText(S: AnsiString; P, Max: Integer): String;
var
  I: Integer;
begin
  Result := '';
  I := P + 1;
  while (I <= Length(S)) and (I <= P + Max) and (Ord(S[I]) <> 0) do begin
    Result := Result + Chr(Ord(S[I]));
    I := I + 1;
  end;
end;

{ One field of a PARAM.SFO (magic NUL P S F, key table start at 8, data table start at 12, entry count at 16, 16-byte
  entries from 20: key offset u16, format u16, length u32, max length u32, data offset u32); '' when absent }
function SfoField(Path, Key: String): String;
var
  S: AnsiString;
  KT, DT, N, I, E: Integer;
begin
  Result := '';
  if not LoadStringFromFile(Path, S) then Exit;
  if (Length(S) < 20) or (Ord(S[1]) <> 0) or (Ord(S[2]) <> 80) or (Ord(S[3]) <> 83) or (Ord(S[4]) <> 70) then Exit;
  KT := SfoInt(S, 8, 4);
  DT := SfoInt(S, 12, 4);
  N := SfoInt(S, 16, 4);
  if N > 200 then N := 200;
  for I := 0 to N - 1 do begin
    E := 20 + 16 * I;
    if SfoText(S, KT + SfoInt(S, E, 2), 32) = Key then begin
      Result := SfoText(S, DT + SfoInt(S, E + 12, 4), SfoInt(S, E + 4, 4));
      Exit;
    end;
  end;
end;

function DiscSfo(Dump: String): String;
begin
  Result := AddBackslash(Dump) + 'PS3_GAME\PARAM.SFO';
end;

{ The Killzone Trilogy disc: its PS3_GAME is Killzone 2 itself (BCUS98116) with disc VERSION 02.00 (ASSUMPTION from
  Project Helghast's read-only survey of that disc; untested here), so it is named, not refused }
function IsTrilogy(Dump: String): Boolean;
begin
  Result := SfoField(DiscSfo(Dump), 'VERSION') = '02.00';
end;

{ '' when the folder holds the Killzone 2 US disc (BCUS98116) with its archive, else the message; Id = the title id
  found ('' when none) }
function DumpProblem(Dir: String; var Id: String): String;
var
  Title: String;
begin
  Id := '';
  Result := '';
  if IsIsoPick(Dir) then Exit
  else if (CompareText(ExtractFileExt(Dir), '.iso') = 0) and not DirExists(Dir) then
    Result := 'The ISO file ' + Dir + ' was not found.'
  else if not FileExists(DiscSfo(Dir)) then
    Result := 'This folder does not look like a Killzone 2 disc dump: PS3_GAME\PARAM.SFO is missing. Select the ' +
      'folder that holds PS3_GAME (picking PS3_GAME itself also works), or a decrypted .iso file.'
  else begin
    Id := SfoField(DiscSfo(Dir), 'TITLE_ID');
    Title := SfoField(DiscSfo(Dir), 'TITLE');
    if Id = '' then
      Result := 'PS3_GAME\PARAM.SFO in this folder has no readable TITLE_ID, so it is not a game dump.'
    else if Id <> 'BCUS98116' then
      Result := 'This is ' + Id + ' (' + Title + '), not Killzone 2. The port needs the Killzone 2 US disc ' +
        '(BCUS98116); other releases are not supported.'
    else
      Result := ArchiveProblem(AddBackslash(Dir) + 'PS3_GAME\USRDIR\');
    if (Id = 'BCUS98116') and (Result <> '') then
      Result := 'This is Killzone 2 (BCUS98116) but the dump is incomplete: ' + Result + ' Copy the dump again.';
  end;
end;

{ '' when the update's PARAM.SFO names the disc's TITLE_ID (as firstrun_check.py U1), else the message }
function UpdateIdProblem(Dir, DiscId: String): String;
var
  Id: String;
begin
  Result := '';
  Id := SfoField(AddBackslash(Dir) + 'PARAM.SFO', 'TITLE_ID');
  if Id = '' then
    Result := 'The update''s PARAM.SFO has no readable TITLE_ID.'
  else if (DiscId <> '') and (Id <> DiscId) then
    Result := 'This update is for ' + Id + ', but the disc dump is ' + DiscId + '. Pick the Killzone 2 update ' +
      '(dev_hdd0\game\' + DiscId + ').';
end;

{ "Browse for ISO file...": the folder page's own Browse picks folders only }
procedure DumpIsoClick(Sender: TObject);
var
  F: String;
begin
  F := DumpPage.Values[0];
  if not IsIsoPick(F) then F := '';
  if GetOpenFileName('Pick your decrypted Killzone 2 disc image', F, '', 'ISO images (*.iso)|*.iso|All files|*.*', 'iso') then
    DumpPage.Values[0] := F;
end;

{ The page names what it found in the picked folder, so a wrong pick is clear before Next }
procedure DumpEditChange(Sender: TObject);
var
  D, Id, Problem: String;
begin
  D := ResolveDump(DumpPage.Values[0]);
  Problem := DumpProblem(D, Id);
  if Trim(D) = '' then DumpInfo.Caption := ''
  else if IsIsoPick(D) then
    DumpInfo.Caption := 'ISO image ' + ExtractFileName(D) + '. Setup checks the disc inside it when the build starts, ' +
      'then copies its game files (about 7 GB) into the install folder.'
  else if (Problem = '') and IsTrilogy(D) then
    DumpInfo.Caption := 'Found: ' + Id + ' (Killzone 2 from the Killzone Trilogy disc: untested)'
  else if Problem = '' then DumpInfo.Caption := 'Found: ' + Id + ' (Killzone 2, US disc)'
  else if Id <> '' then DumpInfo.Caption := 'Found: ' + Id + '. ' + Problem
  else DumpInfo.Caption := 'No Killzone 2 dump found here: PS3_GAME\PARAM.SFO is missing.';
end;

procedure InitializeWizard;
begin
  ApplyHeadingFonts;
  SourcePage := CreateInputOptionPage(wpSelectTasks, 'Your game files',
    'Where are your Killzone 2 files?',
    'Setup needs your own disc dump (BCUS98116), the 1.29 update and the decrypted EBOOT. It reads them in ' +
    'place: never changed, never copied.', True, False);
  SourcePage.Add('Use my RPCS3 install (setup finds the disc, the update and the EBOOT for you)');
  SourcePage.Add('I will pick the folders myself');
  RpcsPage := CreateInputDirPage(SourcePage.ID, 'Your RPCS3 folder',
    'Setup looks at Killzone 2 (BCUS98116) in your RPCS3.',
    'Pick the folder of your RPCS3 (the one with rpcs3.exe or its config folder). Leave it empty to look in ' +
    'RPCS3''s usual places; setup asks before it uses one. Setup looks only at Killzone 2 (BCUS98116) in its files. If RPCS3 ' +
    'keeps the disc outside this folder, setup asks before reading it there.', False, '');
  RpcsPage.Add('RPCS3 folder:');
  DumpPage := CreateInputDirPage(RpcsPage.ID, 'Your disc dump',
    'Killzone 2, US disc (BCUS98116), decrypted.',
    'Pick the folder that holds PS3_GAME (picking PS3_GAME itself also works), or a decrypted .iso file. Setup ' +
    'never changes it; a folder is read in place, the files of an ISO are copied out of it into the install folder ' +
    '(about 7 GB).', False, '');
  DumpPage.Add('Disc dump folder (holds PS3_GAME) or decrypted ISO file:');
  DumpIsoBtn := TNewButton.Create(DumpPage);
  DumpIsoBtn.Parent := DumpPage.Surface;
  DumpIsoBtn.Left := 0;
  DumpIsoBtn.Top := DumpPage.Edits[0].Top + DumpPage.Edits[0].Height + ScaleY(8);
  DumpIsoBtn.Width := ScaleX(150);
  DumpIsoBtn.Height := ScaleY(24);
  DumpIsoBtn.Caption := 'Browse for &ISO file...';
  DumpIsoBtn.OnClick := @DumpIsoClick;
  { What the picked folder holds (its title id), under the edit (adapted from Project Helghast v0.1.2) }
  DumpInfo := TNewStaticText.Create(DumpPage);
  DumpInfo.Parent := DumpPage.Surface;
  DumpInfo.Left := 0;
  DumpInfo.Top := DumpIsoBtn.Top + DumpIsoBtn.Height + ScaleY(10);
  DumpInfo.AutoSize := False;
  DumpInfo.WordWrap := True;
  DumpInfo.Width := DumpPage.SurfaceWidth;
  DumpInfo.Height := ScaleY(48);
  DumpPage.Edits[0].OnChange := @DumpEditChange;
  UpdatePage := CreateInputDirPage(DumpPage.ID, 'Update 1.29',
    'The port is built on 1.29.',
    'Pick the folder named BCUS98116 that holds the 1.29 update (the update uses the disc''s own id).' + #13#10 +
    'RPCS3: once you install the update in RPCS3 (see its documentation), it is in RPCS3''s dev_hdd0\game folder.' + #13#10 +
    'PS3: copy dev_hdd0\game\BCUS98116 from the console.', False, '');
  UpdatePage.Add('1.29 update folder (BCUS98116):');
  EbootPage := CreateInputFilePage(UpdatePage.ID, 'Decrypted EBOOT',
    'The 1.29 EBOOT, decrypted.',
    'The port cannot decrypt it. It needs a decrypted EBOOT.elf, made from your own copy, in the update''s USRDIR folder. ' +
    'This project ships no decryption tools or instructions.');
  EbootPage.Add('EBOOT.elf:', 'ELF files (*.elf)|*.elf|All files|*.*', '.elf');
  { Install over an earlier version: the folders picked last time (RegisterPreviousData) }
  { RPCS3 is offered first when its usual folder exists here (display only; rpcs3_import.py does the real search) }
  SourcePage.Values[0] := True;
  SourcePage.Values[1] := False;
  if DirExists(ExpandConstant('{userappdata}\rpcs3')) then
    RpcsPage.Values[0] := ExpandConstant('{userappdata}\rpcs3')
  else if DirExists(ExpandConstant('{localappdata}\Programs\rpcs3')) then
    RpcsPage.Values[0] := ExpandConstant('{localappdata}\Programs\rpcs3');
  if GetPreviousData('UseRpcs3', '1') = '0' then begin
    SourcePage.Values[0] := False;
    SourcePage.Values[1] := True;
  end;
  if GetPreviousData('Rpcs3Dir', '') <> '' then RpcsPage.Values[0] := GetPreviousData('Rpcs3Dir', '');
  DumpPage.Values[0] := GetPreviousData('DumpDir', '');
  UpdatePage.Values[0] := GetPreviousData('UpdateDir', '');
  EbootPage.Values[0] := GetPreviousData('EbootFile', '');

  { Welcome page: "Check now" (one-shot, opt-in by the click) and, after a newer release is found, its page. }
  CheckBtn := TNewButton.Create(WizardForm);
  CheckBtn.Parent := WizardForm.WelcomePage;
  CheckBtn.Left := WizardForm.WelcomeLabel2.Left;
  { Two text lines of room under the button (KZ3 wizard test: one line ran past the page's right edge) }
  CheckBtn.Top := WizardForm.WelcomePage.Height - ScaleY(72);
  CheckBtn.Width := ScaleX(160);
  CheckBtn.Height := ScaleY(24);
  CheckBtn.Caption := 'Check for a new version';
  CheckBtn.OnClick := @CheckNowClick;
  ReleaseBtn := TNewButton.Create(WizardForm);
  ReleaseBtn.Parent := WizardForm.WelcomePage;
  ReleaseBtn.Left := CheckBtn.Left + CheckBtn.Width + ScaleX(8);
  ReleaseBtn.Top := CheckBtn.Top;
  ReleaseBtn.Width := ScaleX(140);
  ReleaseBtn.Height := CheckBtn.Height;
  ReleaseBtn.Caption := 'Open release page';
  ReleaseBtn.Visible := False;
  ReleaseBtn.OnClick := @ReleaseClick;
  CheckLbl := TNewStaticText.Create(WizardForm);
  CheckLbl.Parent := WizardForm.WelcomePage;
  CheckLbl.Left := CheckBtn.Left;
  CheckLbl.Top := CheckBtn.Top + CheckBtn.Height + ScaleY(6);
  CheckLbl.AutoSize := False;
  CheckLbl.WordWrap := True;
  CheckLbl.Width := WizardForm.WelcomePage.Width - CheckLbl.Left - ScaleX(16);
  CheckLbl.Height := ScaleY(30);
  CheckLbl.Caption := 'One anonymous request to GitHub, only on your click. Nothing about you or the game is sent.';

  { Directory page: Inno's folder icon left an empty gap under Proton and the page reads the same
    without it, so the text starts at the icon's left edge on every system. }
  WizardForm.SelectDirBitmapImage.Visible := False;
  WizardForm.SelectDirLabel.Width := WizardForm.SelectDirLabel.Left + WizardForm.SelectDirLabel.Width -
    WizardForm.SelectDirBitmapImage.Left;
  WizardForm.SelectDirLabel.Left := WizardForm.SelectDirBitmapImage.Left;
end;

{ Kept with the uninstall entry for the next install over this one }
procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  if SourcePage.Values[0] then SetPreviousData(PreviousDataKey, 'UseRpcs3', '1')
  else SetPreviousData(PreviousDataKey, 'UseRpcs3', '0');
  SetPreviousData(PreviousDataKey, 'Rpcs3Dir', RpcsPage.Values[0]);
  SetPreviousData(PreviousDataKey, 'DumpDir', DumpPage.Values[0]);
  SetPreviousData(PreviousDataKey, 'UpdateDir', UpdatePage.Values[0]);
  SetPreviousData(PreviousDataKey, 'EbootFile', EbootPage.Values[0]);
end;

{ Ready page: the picked game folders too }
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo,
  MemoGroupInfo, MemoTasksInfo: String): String;
begin
  if SourcePage.Values[0] then begin
    Result := MemoDirInfo + NewLine + NewLine +
      'Your game files (read in place, never copied):' + NewLine +
      Space + 'From your RPCS3 install: ';
    if RpcsPage.Values[0] <> '' then Result := Result + RpcsPage.Values[0]
    else Result := Result + 'found in the usual places when the build starts (setup asks first)';
  end else if IsIsoPick(DumpPage.Values[0]) then
    Result := MemoDirInfo + NewLine + NewLine +
      'Your game files (the ISO''s files are copied into the install, about 7 GB; the rest is read in place):' + NewLine +
      Space + 'Disc image: ' + DumpPage.Values[0] + NewLine +
      Space + '1.29 update: ' + UpdatePage.Values[0] + NewLine +
      Space + 'Decrypted EBOOT: ' + EbootPage.Values[0]
  else
    Result := MemoDirInfo + NewLine + NewLine +
      'Your game files (read in place, never copied):' + NewLine +
      Space + 'Disc dump: ' + DumpPage.Values[0] + NewLine +
      Space + '1.29 update: ' + UpdatePage.Values[0] + NewLine +
      Space + 'Decrypted EBOOT: ' + EbootPage.Values[0];
  if MemoGroupInfo <> '' then Result := Result + NewLine + NewLine + MemoGroupInfo;
  { The group labels' leading line break comes after Inno's indent: move the indent past it }
  StringChangeEx(MemoTasksInfo, Space + NewLine, NewLine + Space, True);
  if MemoTasksInfo <> '' then Result := Result + NewLine + NewLine + MemoTasksInfo;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and BuildFailed then begin
    if BuildStopped then
      WizardForm.FinishedLabel.Caption := 'Project Pyrrhus is installed; the build was stopped. Start Project ' +
        'Pyrrhus to resume it where it stopped.'
    else
      WizardForm.FinishedLabel.Caption := 'Project Pyrrhus is installed, but the build did not finish. Start ' +
        'Project Pyrrhus to try again from where it stopped, or report the problem with the install log.';
  end;
  if (CurPageID = wpFinished) and BuildSkipped then
    WizardForm.FinishedLabel.Caption := 'Project Pyrrhus is installed. Your game files are not set up yet: start ' +
      'Project Pyrrhus and it asks again (it can use your RPCS3 folder, or you pick the folders).';
  if (CurPageID = EbootPage.ID) and (EbootPage.Values[0] = '') then
    EbootPage.Values[0] := AddBackslash(UpdatePage.Values[0]) + 'USRDIR\EBOOT.elf';
end;

{ RPCS3 path: the folder page only for it, the three manual pages only for the other }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  { Silent: the game pages are skipped, so Inno's own folder check never sees their empty fields (it refused the
    whole install: "You must enter a full path with drive letter", VM kit pre-flight); RunBuild reads /DUMP= etc. }
  if WizardSilent and ((PageID = SourcePage.ID) or (PageID = RpcsPage.ID) or (PageID = DumpPage.ID) or
     (PageID = UpdatePage.ID) or (PageID = EbootPage.ID)) then begin
    Result := True;
    Exit;
  end;
  if PageID = RpcsPage.ID then Result := not SourcePage.Values[0]
  else if (PageID = DumpPage.ID) or (PageID = UpdatePage.ID) or (PageID = EbootPage.ID) then
    Result := SourcePage.Values[0];
end;

{ The manual EBOOT page: is the picked file still an encrypted SELF? Same test as the text UI (rpcs3_import.py
  --eboot-kind, rpcs3_locate.eboot_kind). It runs before anything is installed, so it uses the Python and the two
  scripts extracted to the temp folder (vcheck). True = encrypted, Msg = the help text. Any failure to run it = not encrypted
  (the build's own check, firstrun_check E1, still refuses an encrypted file). }
function EbootEncrypted(Path: String; var Msg: String): Boolean;
var
  Lines: TArrayOfString;
  ResFile: String;
  RC, I: Integer;
begin
  Result := False;
  Msg := '';
  ResFile := ExpandConstant('{tmp}\eboot-kind.txt');
  DeleteFile(ResFile);
  try
    ExtractTemporaryFiles('{tmp}\vcheck\*');
  except
    Exit;
  end;
  if not Exec(ExpandConstant('{tmp}\vcheck\python\python.exe'),
      '"' + ExpandConstant('{tmp}\vcheck\rpcs3_import.py') + '" --eboot-kind "' + Path + '" --out "' + ResFile + '"',
      '', SW_HIDE, ewWaitUntilTerminated, RC) then Exit;
  if not LoadStringsFromFile(ResFile, Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do begin
    if Pos('status=encrypted', Lines[I]) = 1 then Result := True;
    if Pos('help=', Lines[I]) = 1 then Msg := Copy(Lines[I], 6, MaxInt);
  end;
  if Result and (Msg = '') then Msg := 'This EBOOT is still encrypted.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  D, EbootMsg, Problem, Id: String;
  FreeB, TotalB: Int64;
begin
  Result := True;
  { A silent install simulates the Next clicks (Inno help, NextButtonClick); a box here would wait for a click
    nobody makes. The game paths then come from /DUMP= /UPDATE= /EBOOT= (RunBuild) and firstrun_check.py checks them. }
  if WizardSilent then Exit;
  { OneDrive and the like: said on the folder page already; PrepareToInstall repeats it for silent installs }
  if CurPageID = wpSelectDir then begin
    Problem := InstallDirProblem(WizardDirValue);
    if Problem <> '' then begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end;
  end;
  if CurPageID = RpcsPage.ID then begin
    D := AddBackslash(RpcsPage.Values[0]);
    if (RpcsPage.Values[0] <> '') and not (FileExists(D + 'rpcs3.exe') or FileExists(D + 'config\games.yml') or
        FileExists(D + 'games.yml') or FileExists(D + 'config\vfs.yml') or FileExists(D + 'vfs.yml')) then begin
      MsgBox('This does not look like an RPCS3 folder (rpcs3.exe or config\games.yml is needed). Select the ' +
        'folder of your RPCS3, or leave it empty to look in the usual places.', mbError, MB_OK);
      Result := False;
    end;
  end;
  { Quick checks only; firstrun_check.py (D1-D3, U1-U3, E1) runs as the build's first step. }
  if CurPageID = DumpPage.ID then begin
    { The folder that holds PS3_GAME is used from here on, whichever level was picked }
    DumpPage.Values[0] := ResolveDump(DumpPage.Values[0]);
    Problem := DumpProblem(DumpPage.Values[0], Id);
    if Problem <> '' then begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end else if IsIsoPick(DumpPage.Values[0]) then begin
      Log('disc dump: decrypted ISO ' + DumpPage.Values[0] + ' (read by the build''s first step)');
      { the copy out of the ISO: about 7 GB for the game files, room for the build }
      if GetSpaceOnDisk64(ExtractFileDrive(WizardDirValue), FreeB, TotalB) and
         (FreeB < Int64(10) * 1024 * 1024 * 1024) then
        Result := MsgBox('The install folder''s drive has less than 10 GB free; copying the game files out of the ' +
          'ISO needs about 7 GB and the build about 2 GB more. Go on anyway?', mbConfirmation,
          MB_YESNO or MB_DEFBUTTON2) = IDYES;
    end else begin
      Log('disc dump: ' + DumpPage.Values[0] + ', TITLE_ID ' + Id + ', disc VERSION ' +
        SfoField(DiscSfo(DumpPage.Values[0]), 'VERSION'));
      if IsTrilogy(DumpPage.Values[0]) and (not TrilogyNoted) then begin
        TrilogyNoted := True;
        MsgBox('This is Killzone 2 (BCUS98116) from the Killzone Trilogy disc. The port is built and tested on the ' +
          'stand-alone US disc; the Trilogy copy is untested. The first-run check compares its game archive with ' +
          'the known one. Setup goes on.', mbInformation, MB_OK);
      end;
    end;
  end else if CurPageID = UpdatePage.ID then begin
    UpdatePage.Values[0] := ResolveUpdate(UpdatePage.Values[0]);
    D := AddBackslash(UpdatePage.Values[0]);
    Problem := '';
    if FileExists(D + 'PARAM.SFO') then
      Problem := UpdateIdProblem(UpdatePage.Values[0], SfoField(DiscSfo(DumpPage.Values[0]), 'TITLE_ID'));
    if Problem <> '' then begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end else if not (FileExists(D + 'PARAM.SFO') and FileExists(D + 'USRDIR\EBOOT.BIN') and
            FileExists(D + 'USRDIR\added_data_ps3.psarc')) then begin
      { A missing 1.29 update stops here with the steps; Next again = check again.
        ASSUMPTION: the exact RPCS3/PS3 wording is to be checked against RPCS3's own docs before release. }
      MsgBox('The 1.29 update was not found in this folder (PARAM.SFO, USRDIR\EBOOT.BIN and ' +
        'USRDIR\added_data_ps3.psarc are needed). The port is built on 1.29.' + #13#10 + #13#10 +
        'To add it:' + #13#10 +
        '  - on your PS3: install the 1.29 update for Killzone 2, then copy the game''s update ' +
        'folder from dev_hdd0\game\BCUS98116; or' + #13#10 +
        '  - with RPCS3: install the 1.29 update in RPCS3 (see its documentation).' + #13#10 + #13#10 +
        'Then select the folder again and press Next to check again.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = EbootPage.ID then begin
    { A folder typed in: its EBOOT.elf, else its USRDIR\EBOOT.elf (as the first run's console question, Project Helghast v0.1.4) }
    D := AddBackslash(Trim(EbootPage.Values[0]));
    if DirExists(EbootPage.Values[0]) then begin
      if FileExists(D + 'EBOOT.elf') then EbootPage.Values[0] := D + 'EBOOT.elf'
      else if FileExists(D + 'USRDIR\EBOOT.elf') then EbootPage.Values[0] := D + 'USRDIR\EBOOT.elf'
      else begin
        MsgBox('No EBOOT.elf in this folder (looked for ' + D + 'EBOOT.elf and ' + D + 'USRDIR\EBOOT.elf). ' +
          'Select the decrypted EBOOT.elf file itself.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end;
    if FileExists(EbootPage.Values[0]) and EbootEncrypted(EbootPage.Values[0], EbootMsg) then begin
      MsgBox(EbootMsg, mbError, MB_OK);
      Result := False;
    end else if not FileExists(EbootPage.Values[0]) then begin
      MsgBox('No decrypted EBOOT here. The port cannot decrypt it. It needs a decrypted EBOOT.elf, made from ' +
        'your own copy, in that folder.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ "key=value" field of a PROGRESS/RESULT line }
function StepLabel(Name: String): String;
begin
  { The labels of firstrun.py's step table }
  if Name = 'check' then Result := 'Checking the game files'
  else if Name = 'load' then Result := 'Loading the EBOOT'
  else if Name = 'ppu-lift' then Result := 'Lifting PPU code'
  else if Name = 'configure' then Result := 'Configuring the build'
  else if Name = 'compile' then Result := 'Compiling'
  else Result := 'Finishing';
end;

function Clock(Secs: Integer): String;
begin
  Result := Format('%d:%.2d:%.2d', [Secs div 3600, (Secs div 60) mod 60, Secs mod 60]);
end;

procedure StopClick(Sender: TObject);
begin
  { firstrun.py --stop-file: it ends the running tool (the whole process tree), leaves no marker for that step and
    writes RESULT step=cancelled; the next start resumes at that step. }
  if MsgBox('Stop the build now?' + #13#10 + #13#10 + 'The steps already done are kept: the next start of ' +
            'Project Pyrrhus resumes where it stopped.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then Exit;
  SaveStringToFile(StopFile, 'stop', False);
  Log('build: stop requested by the player');
  StopBtn.Enabled := False;
  StopBtn.Caption := 'Stopping...';
end;

{ ---- "Use my RPCS3 install": all logic is in tools/release/rpcs3_import.py (host-tested, test_rpcs3_import.py);
  this only asks the questions and passes the answers. It reads results from key=value files. }
function Rpcs3Import(Args, OutFile: String): Boolean;
var
  RC: Integer;
begin
  DeleteFile(OutFile);
  { The arguments hold the player's paths: the Inno log gets the command name only }
  Log('rpcs3_import: ' + Copy(Args, 1, Pos(' ', Args + ' ') - 1));
  Result := Exec(ExpandConstant('{app}\toolchain\python\python.exe'),
    '"' + ExpandConstant('{app}\kz2-setup\release\rpcs3_import.py') + '" ' + Args + ' --out "' + OutFile + '"',
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC) and FileExists(OutFile);
end;

{ All values of Key in a key=value file, one per line joined by NewLine; '' when none }
function KVAll(Lines: TArrayOfString; Key: String; Sep: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to GetArrayLength(Lines) - 1 do
    if Pos(Key + '=', Lines[I]) = 1 then begin
      if Result <> '' then Result := Result + Sep;
      Result := Result + Copy(Lines[I], Length(Key) + 2, MaxInt);
    end;
end;

function KV(Lines: TArrayOfString; Key: String): String;
var
  P: Integer;
begin
  Result := KVAll(Lines, Key, #13#10);
  P := Pos(#13#10, Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
end;

function RpcsArgs(Cmd: String): String;
begin
  Result := Cmd + ' --rpcs3 "' + RemoveBackslashUnlessRoot(RpcsRoot) + '"';
  if AllowOutside then Result := Result + ' --allow-outside';
end;

{ Fills DumpDir/UpdateDir/EbootFile from the player's RPCS3. False = the player left it (the first start asks again). }
function ResolveRpcs3: Boolean;
var
  ResFile, Msg, Probs: String;
  Lines: TArrayOfString;
  Done: Boolean;
  I: Integer;
begin
  Result := False;
  ResFile := ExpandConstant('{tmp}\rpcs3.txt');
  RpcsRoot := RpcsPage.Values[0];
  AllowOutside := False;
  if RpcsRoot = '' then begin
    if not (Rpcs3Import('--detect', ResFile) and LoadStringsFromFile(ResFile, Lines) and (KV(Lines, 'status') = 'ok')) then begin
      MsgBox('No RPCS3 folder was found in the usual places. Start Project Pyrrhus later and give the folder ' +
        'of your RPCS3, or pick the game folders yourself.', mbInformation, MB_OK);
      Exit;
    end;
    RpcsRoot := KV(Lines, 'root');
    if MsgBox('Found RPCS3 at ' + RpcsRoot + #13#10#13#10 + 'Use it for the game files? Setup looks only at ' +
        'Killzone 2 (BCUS98116) in it, in place.', mbConfirmation, MB_YESNO) <> IDYES then Exit;
  end;
  Done := False;
  while not Done do begin
    if not (Rpcs3Import(RpcsArgs('--resolve'), ResFile) and LoadStringsFromFile(ResFile, Lines)) then begin
      MsgBox('The RPCS3 lookup did not run.', mbError, MB_OK);
      Exit;
    end;
    if KV(Lines, 'status') = 'ok' then begin
      DumpDir := KV(Lines, 'dump');
      UpdateDir := KV(Lines, 'update');
      EbootFile := KV(Lines, 'eboot');
      Result := True;
      Exit;
    end else if KV(Lines, 'status') = 'approval' then begin
      if MsgBox('RPCS3''s own settings keep some of Killzone 2 outside that folder:' + #13#10 +
          KVAll(Lines, 'outside', #13#10) + #13#10#13#10 + 'Read it there too? Setup looks only at ' +
          'Killzone 2 (BCUS98116) in it.', mbConfirmation, MB_YESNO) <> IDYES then Exit;
      AllowOutside := True;
    end else begin
      Probs := '';
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Pos('problem=', Lines[I]) = 1 then
          Probs := Probs + Copy(Lines[I], Pos('|', Lines[I]) + 1, MaxInt) + #13#10;
      StringChangeEx(Probs, #31, #13#10, True);   { the lookup breaks long paths with #31 (the box clips long words) }
      Msg := Probs + #13#10 + KVAll(Lines, 'help', #13#10#13#10);
      if MsgBox(Msg + #13#10#13#10 + 'Retry checks again. Cancel leaves the game files for the first start.',
          mbError, MB_RETRYCANCEL) <> IDRETRY then Exit;
    end;
  end;
end;

function SaveDataDir: String;
begin
  if WizardIsTaskSelected('portable') then Result := ExpandConstant('{app}')
  else Result := ExpandConstant('{userappdata}\{#AppDirName}');
end;

{ After a good build: the optional, separate "Import your RPCS3 save" question. Copies only on a yes; an existing
  save is replaced only after a second yes. Counts only; no save contents or names reach the log. }
procedure OfferSaveImport;
var
  ResFile, Dry: String;
  Lines: TArrayOfString;
begin
  ResFile := ExpandConstant('{tmp}\rpcs3-save.txt');
  if not (Rpcs3Import(RpcsArgs('--save-dryrun') + ' --data-dir "' + RemoveBackslashUnlessRoot(SaveDataDir) + '"', ResFile)
          and LoadStringsFromFile(ResFile, Lines)) or (KV(Lines, 'status') <> 'ok') then Exit;
  Dry := KVAll(Lines, 'line', #13#10);
  if MsgBox('Import your RPCS3 save for Killzone 2?' + #13#10#13#10 + Dry + #13#10#13#10 +
      'Optional. It is copied unchanged; RPCS3''s own copy is never touched.', mbConfirmation,
      MB_YESNO or MB_DEFBUTTON2) <> IDYES then begin
    Log('rpcs3 save import: the player said no');
    Exit;
  end;
  Rpcs3Import(RpcsArgs('--save-copy') + ' --data-dir "' + RemoveBackslashUnlessRoot(SaveDataDir) + '"', ResFile);
  if LoadStringsFromFile(ResFile, Lines) and (KV(Lines, 'status') = 'exists') then begin
    if MsgBox('You already have a Killzone 2 save here. Replace it with the RPCS3 one?' + #13#10#13#10 +
        'Files that are only in yours stay.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      Rpcs3Import(RpcsArgs('--save-copy') + ' --overwrite --data-dir "' + RemoveBackslashUnlessRoot(SaveDataDir) +
        '"', ResFile)
    else begin
      Log('rpcs3 save import: kept the existing save');
      Exit;
    end;
  end;
  if LoadStringsFromFile(ResFile, Lines) then begin
    Log(KV(Lines, 'line'));
    if KV(Lines, 'status') = 'copied' then MsgBox('Your RPCS3 save was copied.', mbInformation, MB_OK)
    else MsgBox('The save could not be copied. Nothing was changed in RPCS3.', mbError, MB_OK);
  end;
end;

procedure RunBuild;
var
  Page: TOutputProgressWizardPage;
  Py, Script, Status, Params, L, Name, Pct: String;
  Lines: TArrayOfString;
  RC, Elapsed, P: Integer;
  Finished: Boolean;
begin
  DumpDir := DumpPage.Values[0];
  UpdateDir := UpdatePage.Values[0];
  EbootFile := EbootPage.Values[0];
  if WizardSilent then begin
    { Silent install (/SILENT, /VERYSILENT): no pages and no questions. The game paths come from the command line,
      /DUMP=<folder with PS3_GAME> /UPDATE=<BCUS98116 folder> /EBOOT=<EBOOT.elf> (/JOBS=N limits the compile jobs);
      without /DUMP= nothing is built and the first start of Project Pyrrhus asks. The RPCS3 lookup asks questions,
      so it is never used here. }
    DumpDir := ResolveDump(ExpandConstant('{param:DUMP|}'));
    UpdateDir := ResolveUpdate(ExpandConstant('{param:UPDATE|}'));
    EbootFile := ExpandConstant('{param:EBOOT|}');
    if DumpDir = '' then begin
      BuildSkipped := True;
      BuildStopped := True;
      Log('silent install without /DUMP=: nothing built; the first start asks for the game files');
      Exit;
    end;
  end else if SourcePage.Values[0] and not ResolveRpcs3 then begin
    BuildSkipped := True;
    BuildStopped := True;
    Log('rpcs3 import: no game files from RPCS3; the first start asks again');
    Exit;
  end;
  Py := ExpandConstant('{app}\toolchain\python\python.exe');
  Script := ExpandConstant('{app}\kz2-setup\release\firstrun.py');
  Status := ExpandConstant('{tmp}\firstrun.status');
  StopFile := ExpandConstant('{tmp}\firstrun.stop');
  Params := '"' + Script + '" --root "' + ExpandConstant('{app}') + '"' +
    ' --dump "' + DumpDir + '" --update "' + UpdateDir + '"' +
    ' --eboot "' + EbootFile + '"' +
    ' --rpcs3 "' + RemoveBackslashUnlessRoot(RpcsRoot) + '"' +
    ' --toolchain "' + ExpandConstant('{app}\toolchain\llvm-mingw') + '"' +
    ' --log-dir "' + ExpandConstant('{src}') + '" --log-name "' + LogName + '"' +
    ' --status-file "' + Status + '" --stop-file "' + StopFile + '"';
  if StrToIntDef(ExpandConstant('{param:JOBS|0}'), 0) > 0 then
    Params := Params + ' --jobs ' + IntToStr(StrToIntDef(ExpandConstant('{param:JOBS|0}'), 0));
  { RPCS3 paths stay out of the Inno log; firstrun.py's own log redacts them (<RPCS3>/...) }
  if SourcePage.Values[0] and not WizardSilent then Log('firstrun: ' + Py + ' (game paths from the RPCS3 import)')
  else Log('firstrun: ' + Py + ' ' + Params);
  Page := CreateOutputProgressPage('Building Project Pyrrhus', 'From your own game files: usually 5 to 30 minutes.');
  { The wizard has no Cancel after the files are copied: our own Stop. Buttons and the note sit
    under the progress bar; SetProgress in the loop below keeps them answering clicks. }
  StopBtn := TNewButton.Create(Page);
  StopBtn.Parent := Page.Surface;
  StopBtn.Left := Page.ProgressBar.Left;
  StopBtn.Top := Page.ProgressBar.Top + Page.ProgressBar.Height + ScaleY(16);
  StopBtn.Width := ScaleX(110);
  StopBtn.Height := ScaleY(24);
  StopBtn.Caption := 'Stop the build';
  StopBtn.OnClick := @StopClick;
  with TNewStaticText.Create(Page) do begin
    Parent := Page.Surface;
    Left := StopBtn.Left + StopBtn.Width + ScaleX(12);
    Top := StopBtn.Top + ScaleY(4);
    AutoSize := False;
    WordWrap := True;
    Width := Page.SurfaceWidth - Left;
    Height := ScaleY(30);
    Caption := 'Stopping keeps the finished steps: the next start of Project Pyrrhus resumes the build.';
  end;
  Page.SetProgress(0, 1000);
  Page.Show;
  try
    if not Exec(Py, Params, ExpandConstant('{app}'), SW_HIDE, ewNoWait, RC) then begin
      SuppressibleMsgBox('Could not start the build (' + SysErrorMessage(RC) + ').', mbError, MB_OK, IDOK);
      Exit;
    end;
    Finished := False;
    { SetProgress processes the window's messages (the Stop button's click, repaints); Sleep alone would not. }
    while not Finished do begin
      Sleep(250);
      Page.SetProgress(Page.ProgressBar.Position, 1000);
      if LoadStringsFromFile(Status, Lines) and (GetArrayLength(Lines) >= 2) then begin
        if Pos('LOG path=', Lines[0]) = 1 then OurLog := Copy(Lines[0], 10, MaxInt);
        L := Lines[1];
        if Pos('RESULT ', L) = 1 then begin
          Finished := True;
          BuildOK := Field(L, 'ok') = '1';
          BuildStopped := Field(L, 'step') = 'cancelled';
        end else if Pos('PROGRESS ', L) = 1 then begin
          Name := Field(L, 'name');
          Elapsed := StrToIntDef(Field(L, 'elapsed'), 0);
          Pct := Field(L, 'pct');
          P := Pos('.', Pct);
          if P > 0 then Pct := Copy(Pct, 1, P - 1);
          if Name = 'compile' then
            Page.SetText(StepLabel(Name) + ' ' + Field(L, 'done') + ' / ' + Field(L, 'total'),
              'Step ' + Field(L, 'step') + ', elapsed ' + Clock(Elapsed))
          else
            Page.SetText(StepLabel(Name), 'Step ' + Field(L, 'step') + ', elapsed ' + Clock(Elapsed));
          Page.SetProgress(StrToIntDef(Pct, 0) * 10, 1000);
        end;
      end;
    end;
    StopBtn.Visible := False;
    if BuildStopped then
      Page.SetText('Build stopped', 'Start Project Pyrrhus to resume it.')
    else if not BuildOK then begin
      Page.SetText('The build did not finish', 'The install log says why.');
      if WizardSilent then Log('build: did not finish; the install log says why')
      else ShowBuildError;
    end;
  finally
    Page.Hide;
  end;
end;

procedure MergeInnoLog;
var
  Lines: TArrayOfString;
  I: Integer;
  Home: String;
begin
  { One file per run: Inno's own log appended to firstrun.py's, user folder redacted. }
  if not LoadStringsFromFile(ExpandConstant('{log}'), Lines) then Exit;
  Home := GetEnv('USERPROFILE');
  for I := 0 to GetArrayLength(Lines) - 1 do
    if Home <> '' then StringChangeEx(Lines[I], Home, '%USERPROFILE%', True);
  SaveStringToFile(InstallLogPath(''), #13#10 + '# --- Inno Setup log ---' + #13#10, True);
  SaveStringsToFile(InstallLogPath(''), Lines, True);
end;

{ The game folders the wizard resolved, written whether or not "Build now" is ticked: the launcher's first start
  (a build left for later, or one that stopped at a FAIL) checks these first (firstrun.py --check-first) instead of
  asking again in a console (from Project Helghast v0.1.3). From [Code], not [INI]: Inno's setup log prints every [INI] value.
  Without a build the RPCS3 lookup is not run (it asks questions); the first start's own RPCS3 lookup finds them. }
procedure WritePaths;
var
  Ini: String;
begin
  if not WizardIsTaskSelected('buildnow') then begin
    if WizardSilent then begin
      DumpDir := ExpandConstant('{param:DUMP|}');
      UpdateDir := ExpandConstant('{param:UPDATE|}');
      EbootFile := ExpandConstant('{param:EBOOT|}');
    end else if not SourcePage.Values[0] then begin
      DumpDir := DumpPage.Values[0];
      UpdateDir := UpdatePage.Values[0];
      EbootFile := EbootPage.Values[0];
    end;
  end;
  if (DumpDir = '') or (UpdateDir = '') then Exit;
  Ini := ExpandConstant('{app}\kz2-install.ini');
  SetIniString('paths', 'dump', DumpDir, Ini);
  SetIniString('paths', 'update', UpdateDir, Ini);
  SetIniString('paths', 'eboot', EbootFile, Ini);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('buildnow') then begin
    RunBuild;
    if BuildOK and SourcePage.Values[0] and (RpcsRoot <> '') and not WizardSilent then OfferSaveImport;
  end;
  if CurStep = ssPostInstall then WritePaths;
  if CurStep = ssDone then MergeInnoLog;
end;

procedure AskDeleteSaves(Dir: String);
begin
  if DirExists(Dir) and not UninstallSilent then
    if MsgBox('Delete your Project Pyrrhus saves and settings too?' + #13#10 + Dir + #13#10 + #13#10 +
              'No keeps them for a later install.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Dir, True, True, True);
end;

procedure AskDeletePortableSaves(App: String);
begin
  if not DirExists(App + '\gamedata') or UninstallSilent then Exit;
  if MsgBox('Delete your Project Pyrrhus saves and settings too?' + #13#10 + App + '\gamedata' + #13#10 + #13#10 +
            'No keeps them for a later install.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then begin
    DelTree(App + '\gamedata', True, True, True);
    RemoveDir(App);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Ask before removing saves, default keep (silent uninstall keeps them). A normal install keeps saves in
    APPDATA, a portable one in the install folder (launch.py data_dir: gamedata). }
  if CurUninstallStep = usUninstall then begin
    { The junction to the dump: RemoveDirectory on a junction removes the link only, never the target. }
    RemoveDir(ExpandConstant('{app}\vfs\PS3_GAME'));
    Exit;
  end;
  if CurUninstallStep <> usPostUninstall then Exit;
  AskDeleteSaves(ExpandConstant('{userappdata}\{#AppDirName}'));
  { Portable: launch.py's data folder is the install folder itself (gamedata = cellSaveData). }
  AskDeletePortableSaves(ExpandConstant('{app}'));
end;
