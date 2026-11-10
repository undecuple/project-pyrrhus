#!/usr/bin/env bash
# Synthetic host regression; no game data. Run under the shared build lock.
set -euo pipefail
cd "$(dirname "$0")/../.."
out=work/runtime/test/lua-unwind
mkdir -p "$out"
python3 tools/release/test_lua_unwind.py --emit-fixture "$out/fixture.cpp"
# The generated include resolves to the context declared by the harness.
echo '// synthetic context supplied by test_lua_unwind.cpp' > "$out/ppu_recomp.h"
"${CXX:-c++}" -std=c++17 -O2 -Wall -Wextra -Werror -pthread -Iport/kz2 -I"$out" \
  -DLUA_FIXTURE='"fixture.cpp"' tools/runtime/test_lua_unwind.cpp -o "$out/test"
"$out/test"
if KZ2_LUA_UNWIND=0 "$out/test" > "$out/old-behavior.log" 2>&1; then
  echo 'FAIL lua-unwind: old behavior survived'; exit 1
fi
grep -q 'guest longjmp returned into abandoned caller' "$out/old-behavior.log"
echo 'PASS lua-unwind: old behavior reproduces returned-longjmp failure'
