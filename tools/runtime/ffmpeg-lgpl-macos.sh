#!/usr/bin/env bash
# Build the LGPL-only FFmpeg the native macOS port loads for movies (H.264, MPEG-2) and AC-3 sound:
# the same version and decoder set as tools/runtime/ffmpeg-lgpl-win.nix, built for the host Mac with Apple Clang.
#
#   tools/runtime/ffmpeg-lgpl-macos.sh [OUT]      # OUT defaults to work/ffmpeg-macos
#
# Licence: LGPL-2.1-or-later only. No --enable-gpl, no --enable-version3, no --enable-nonfree, no external
# libraries (--disable-autodetect); the script stops unless FFmpeg's own config.h says so.
# Network: one shallow clone of the FFmpeg source at the pinned tag. The game and the repository are not read.
# Output: OUT/lib/libavcodec.63.dylib and libavutil.61.dylib (install names @loader_path, so avcodec finds avutil
# beside it), OUT/include, and OUT/share/ffmpeg-lgpl/{COPYING.LGPLv2.1,LICENSE-build.txt,SOURCE.txt}.
# tools/build-kz2-macos.py --ffmpeg-include OUT/include compiles against it; tools/run-kz2-macos.py loads OUT/lib.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo "ffmpeg-lgpl-macos: macOS only (Windows: tools/runtime/ffmpeg-lgpl-win.nix)" >&2; exit 1; }
VERSION=9.0.1
TAG="n$VERSION"
URL=https://git.ffmpeg.org/ffmpeg.git
ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
OUT="${1:-$ROOT/work/ffmpeg-macos}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"
SRC="$(mktemp -d "${TMPDIR:-/tmp}/ffmpeg-lgpl.XXXXXX")"
trap 'rm -rf "$SRC"' EXIT
git clone -q --depth 1 --branch "$TAG" "$URL" "$SRC/ffmpeg"
cd "$SRC/ffmpeg"
REV="$(git rev-parse HEAD)"
[[ "$(cat RELEASE)" == "$VERSION" ]] || { echo "ffmpeg-lgpl-macos: tag $TAG is not release $VERSION" >&2; exit 1; }
./configure --prefix="$OUT" --install-name-dir='@loader_path' --arch="$(uname -m)" \
  --enable-shared --disable-static \
  --disable-autodetect --enable-pthreads --disable-network \
  --disable-programs --disable-doc --disable-debug \
  --disable-avdevice --disable-avformat --disable-avfilter --disable-swscale --disable-swresample \
  --disable-everything \
  --enable-decoder=h264,mpeg2video,ac3 \
  --enable-parser=h264,mpegvideo,ac3 >"$SRC/configure.log"
grep -q '#define FFMPEG_LICENSE "LGPL version 2.1 or later"' config.h
grep -q '#define CONFIG_GPL 0' config.h
grep -q '#define CONFIG_NONFREE 0' config.h
grep -q '#define CONFIG_VERSION3 0' config.h
# Half the cores: the other local builds share this machine (docs/BUILDING.md, the macOS build's resource guard).
JOBS=$(( $(sysctl -n hw.ncpu) / 2 )); (( JOBS > 0 )) || JOBS=1
make -j"$JOBS" >"$SRC/make.log"
make install >"$SRC/install.log"
d="$OUT/share/ffmpeg-lgpl"; mkdir -p "$d"
cp COPYING.LGPLv2.1 "$d/"
grep -E '#define (FFMPEG_LICENSE|FFMPEG_CONFIGURATION|CONFIG_GPL|CONFIG_NONFREE|CONFIG_VERSION3) ' config.h > "$d/LICENSE-build.txt"
printf 'FFmpeg %s, source %s tag %s (commit %s), LGPL-2.1-or-later, built unmodified for macOS %s by tools/runtime/ffmpeg-lgpl-macos.sh\n' \
  "$VERSION" "$URL" "$TAG" "$REV" "$(uname -m)" > "$d/SOURCE.txt"
rm -rf "$OUT/lib/pkgconfig" "$OUT/share/ffmpeg/examples"
echo "ffmpeg-lgpl-macos: $OUT/lib (libavcodec.63.dylib, libavutil.61.dylib), headers in $OUT/include"
