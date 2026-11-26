#!/usr/bin/env bash
# Host test for KZ2 patch 6107 (runtime, 2026-11-26): the weak SPU gates of runtime/spu/spu_context.h (SPU_GATE) must
# resolve, in a MinGW GNU ld link, to one address per gate that is one of that gate's own per-object defaults
# (.weak.<gate>.<tu>). Before 6107 every gate of a TU shared .data$kz3rm (KZ3 patch 1102) and GNU ld resolved each
# default at twice its offset: the gates after the first read the words past them, which made every native SPU job
# fall back at ~3 fps once patch 7045 added a ninth gate.
#   Three TUs include the patched header and each returns every gate's address (a rip-relative lea); the link's
#   disassembly and symbol table are compared. No program runs, so no Wine/Proton is needed.
# Negative control (must FAIL): the same header with port/patches/6107 reversed. No game data, no GPU.
# SKIP (exit 77) without the MinGW cross tools (the .#win shell has them):
#   nix develop .#win --command tools/sandbox.sh -- tools/runtime/test_spu_gate_weak_pe.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
PT="${KZ2_OUT:-work}/ps3recomp-patched"
H="$PT/runtime/spu/spu_context.h"
P="$ROOT/port/patches/6107-spu-gates-own-sections-gnu-ld-weak.patch"
T=test_spu_gate_weak_pe
X=x86_64-w64-mingw32
for t in gcc nm objdump; do
  command -v "$X-$t" >/dev/null || { echo "[$T] SKIP: no $X-$t (run in nix develop .#win)"; exit 77; }
done
grep -q 'KZ2 patch 6107' "$H" 2>/dev/null || { echo "[$T] FAIL: $H without patch 6107 (run tools/ps3recomp-patched.sh)"; exit 1; }
O="$(mktemp -d "${TMPDIR:-/tmp}/kz2-gateweak.XXXXXX")"; trap 'rm -rf "$O"' EXIT
mkdir -p "$O/new/runtime/spu" "$O/old/runtime/spu"
cp "$H" "$O/new/runtime/spu/spu_context.h"
cp "$H" "$O/old/runtime/spu/spu_context.h"
(cd "$O/old" && git apply -R "$P") || { echo "[$T] FAIL: patch 6107 does not reverse on $H"; exit 1; }
grep -q 'KZ2 patch 6107' "$O/old/runtime/spu/spu_context.h" && { echo "[$T] FAIL: reversed header still names 6107"; exit 1; }
GATES="$(sed -nE 's/^SPU_GATE[^=;]* int (g_[A-Za-z0-9_]+) *=.*/\1/p' "$H" | sort -u)"
NG=$(printf '%s\n' "$GATES" | grep -c .)
[[ $NG -ge 9 ]] || { echo "[$T] FAIL: found $NG SPU_GATE gates in $H (expected at least 9)"; exit 1; }

# check DIR: link three TUs against DIR's header; prints "ok" or the first mismatch, returns 0 when every gate resolves
check() {
  local d="$1" w="$O/b-$(basename "$1")" k g
  mkdir -p "$w"
  for k in 1 2 3; do
    {
      echo '#include "spu_context.h"'
      echo "int tu${k}_first(void) { return $k; }"   # names the per-object defaults .weak.<gate>.tu<k>_first
      echo "static int tu${k}_local = $k; int* tu${k}_lp(void) { return &tu${k}_local; }"
      for g in $GATES; do echo "void* tu${k}_${g}(void) { return (void*)&${g}; }"; done
      [[ $k == 1 ]] && echo 'int main(void) { return 0; }'
    } > "$w/tu$k.c"
    "$X-gcc" -std=gnu11 -O2 -msse4.1 -w -I"$d/runtime/spu" -I"$ROOT/$PT/runtime/spu" -I"$ROOT/$PT/runtime" \
      -I"$ROOT/$PT/include" -c "$w/tu$k.c" -o "$w/tu$k.o" > "$w/cc.log" 2>&1 \
      || { echo "build error: $(head -3 "$w/cc.log" | tr '\n' ' ')"; return 2; }
  done
  "$X-gcc" "$w/tu1.o" "$w/tu2.o" "$w/tu3.o" -o "$w/t.exe" > "$w/ld.log" 2>&1 \
    || { echo "link error: $(head -3 "$w/ld.log" | tr '\n' ' ')"; return 2; }
  "$X-nm" "$w/t.exe" > "$w/nm.txt"
  "$X-objdump" -d --no-show-raw-insn "$w/t.exe" > "$w/dis.txt"
  python3 - "$w" $GATES <<'PY'
import re, sys
w, gates = sys.argv[1], sys.argv[2:]
syms = {}
for line in open(f"{w}/nm.txt"):
    f = line.split()
    if len(f) == 3:
        syms.setdefault(f[2], []).append(int(f[0], 16))
target, cur = {}, None
for line in open(f"{w}/dis.txt"):
    m = re.match(r"^[0-9a-f]+ <(tu[123]_g_[A-Za-z0-9_]+)>:", line)
    if m:
        cur = m.group(1); continue
    m = re.search(r"\blea\s+0x[0-9a-f]+\(%rip\),%rax\s+# ([0-9a-f]+)", line)
    if cur and m:
        target[cur] = int(m.group(1), 16); cur = None
bad = []
for g in gates:
    own = {a for s, v in syms.items() if s == g or s.startswith(f".weak.{g}.") for a in v}
    t = [target.get(f"tu{k}_{g}") for k in (1, 2, 3)]
    if None in t:
        bad.append(f"{g}: no lea found ({t})")
    elif len(set(t)) != 1:
        bad.append(f"{g}: TUs resolve to different addresses {[hex(x) for x in t]}")
    elif t[0] not in own:
        bad.append(f"{g}: resolves to {t[0]:#x}, not one of its own definitions {sorted(hex(x) for x in own)}")
print("ok" if not bad else f"{len(bad)} of {len(gates)} gates wrong; first: {bad[0]}")
sys.exit(1 if bad else 0)
PY
}

fail=0
if out="$(check "$O/new")"; then
  echo "[$T] patched header: $NG gates, each resolves to its own definition in all 3 TUs ($out)"
else
  echo "[$T] FAIL: patched header: $out"; fail=1
fi
rc=0; out="$(check "$O/old")" || rc=$?
if [[ $rc == 0 ]]; then
  echo "[$T] FAIL: negative control (6107 reversed) passed: the test no longer detects the GNU ld weak-default bug"; fail=1
elif [[ $rc == 2 ]]; then
  echo "[$T] FAIL: negative control did not build: $out"; fail=1
else
  echo "[$T] negative control (6107 reversed) detected: $out"
fi
[[ $fail == 0 ]] && echo "[$T] PASS"
exit $fail
