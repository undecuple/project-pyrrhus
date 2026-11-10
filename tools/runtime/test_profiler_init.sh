#!/usr/bin/env bash
# KZ2 readiness-publication race regression, extracting actual toolkit code.
# Runs no game/GPU; --prepare-only extracts fixtures without compiling.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
P="${KZ2_PATCHED_DIR:-${KZ2_OUT:-work}/ps3recomp-patched}"
O=work/runtime/test/profiler-init
mkdir -p "$O"
python3 - "$P" "$O" <<'PY'
from pathlib import Path
import re, sys
p, out = map(Path, sys.argv[1:])
s = (p / 'runtime/diag/kz3_wait_acct.c').read_text()
h = (p / 'runtime/diag/kz3_wait_acct.h').read_text()
# Every remaining plain interval read must belong to the printer, started after
# readiness publication. Catch new bypass guards anywhere in the toolkit sources.
plain_printer = {
    '    fprintf(stderr, "[wacct] ---- t=%.1fs window=%dms flips=%ld\\n", t_s, g_kz3_wacct, flips);',
    '        Sleep((DWORD)g_kz3_wacct);',
    '        usleep((useconds_t)g_kz3_wacct * 1000u);',
}
plain_seen = set()
for source in p.rglob('*'):
    if not source.is_file() or source.suffix not in {'.c', '.h', '.cpp', '.hpp', '.cc', '.cxx'}:
        continue
    text = source.read_text(errors='replace')
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    for line in text.splitlines():
        if not re.search(r'\bg_kz3_wacct\b', line):
            continue
        cleaned = re.sub(r'__atomic_(?:load|store)_n\(&g_kz3_wacct\b', 'atomic_ready', line)
        cleaned = re.sub(r'\bextern int g_kz3_wacct\s*;', '', cleaned)
        cleaned = re.sub(r'^int g_kz3_wacct = -1;$', '', cleaned)
        if re.search(r'\bg_kz3_wacct\b', cleaned):
            if source != p / 'runtime/diag/kz3_wait_acct.c' or line not in plain_printer:
                raise SystemExit(f'FAIL profiler_init: unaudited plain readiness access: {source}: {line}')
            plain_seen.add(line)
if plain_seen != plain_printer:
    raise SystemExit('FAIL profiler_init: printer interval reads changed; re-audit startup ordering')
start = s.index('int kz3_wacct_init(void)\n{')
end = s.index('\n}', start) + 2
body = s[start:end] + '\n'
m = re.search(r'static inline int kz3_wacct_on\(void\)\s*\{.*?\n\}', h, re.S)
if not m:
    raise SystemExit('FAIL profiler_init: expected patched multi-line acquire accessor')
if '__ATOMIC_ACQUIRE' not in m[0] or '__ATOMIC_RELEASE' not in body:
    raise SystemExit('FAIL profiler_init: missing readiness acquire/release')
# Mutate only publication ordering; preserve the rest of the shipped initializer.
store = '        __atomic_store_n(&g_kz3_wacct, ms, __ATOMIC_RELEASE);\n'
setup = '        prof_init();   /* patch 1033 */\n'
if body.count(store) != 1 or body.count(setup) != 1 or body.index(store) < body.index(setup):
    raise SystemExit('FAIL profiler_init: readiness must follow profiler initialization')
mutant = body.replace(store, '').replace(setup, store + setup)
(out / 'init.inc').write_text(body)
(out / 'init-old-order.inc').write_text(mutant)
(out / 'on.inc').write_text(m[0] + '\n')
print('profiler_init: extracted initializer, acquire accessor and old-order mutant')
PY
if [[ "${1:-}" == --prepare-only ]]; then exit 0; fi
[[ $# == 0 ]] || { echo 'usage: test_profiler_init.sh [--prepare-only]' >&2; exit 2; }
for kind in init init-old-order; do
  "${CC:-cc}" -std=gnu11 -O2 -Wall -Wextra -Werror -pthread \
    -DPROFILER_INIT_BODY="\"$ROOT/$O/$kind.inc\"" \
    -DPROFILER_ON_BODY="\"$ROOT/$O/on.inc\"" \
    tools/runtime/test_profiler_init.c -o "$O/$kind"
done
"$O/init"
"$O/init" off
if "$O/init-old-order" > "$O/mutant.log" 2>&1; then
  echo 'FAIL profiler_init: old-order mutation survived'; exit 1
fi
grep -q 'FAIL profiler_init: early=1 attached=0' "$O/mutant.log" || { cat "$O/mutant.log"; exit 1; }
echo 'PASS profiler_init: old-order mutation loses attachment and is rejected'
