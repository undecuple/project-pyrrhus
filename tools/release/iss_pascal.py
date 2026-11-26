#!/usr/bin/env python3
"""A small interpreter for the Pascal Script subset that installer/kz2.iss's folder-guard routines use, so host tests
can run those routines (not grep their text) against a scratch folder on Linux. Port-only test tool; no Inno code.

What it runs: function/procedure declarations with value and var parameters, local var sections (a local const
section is refused, as ISCC refuses it),
begin/end, if/then/else, while/do, repeat/until, try/finally/end, Exit, Break, :=, calls, field reads (R.Name), S[I] on strings,
string literals with '' and #13 codes, integers and $hex, not/and/or (boolean or bitwise on integers), = <> < > <= >=,
+ -. ISPP {#Name} expansions are replaced from the file's own #define lines first. Anything else raises PascalError,
so a routine that outgrows the subset fails its test loudly instead of being half-run.

Use: prog = Program(iss_text, ["DirIsOurs", ...], builtins=..., globals_=...); prog.call("DirIsOurs", "C:\\x").
"""
import re


class PascalError(Exception):
    pass


class _Exit(Exception):
    pass


class _Break(Exception):
    pass


class Ref:
    """A var parameter: reads and writes go to name in env."""
    def __init__(self, env, name):
        self.env, self.name = env, name

    def get(self):
        return self.env.get(self.name)

    def set(self, v):
        self.env.set(self.name, v)


class Record(dict):
    """A record value (TFindRec): fields by name, case-insensitive."""
    def __getitem__(self, k):
        for key in self:
            if key.lower() == k.lower():
                return dict.__getitem__(self, key)
        raise PascalError(f"no field {k}")


def ispp_expand(text):
    defines = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', text, re.M))
    return re.sub(r"\{#(\w+)\}", lambda m: defines.get(m.group(1), m.group(0)), text)


def code_section(text):
    i = text.index("[Code]")
    return text[i + len("[Code]"):]


TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<lc>//[^\n]*) | (?P<bc>\{[^}]*\}) | (?P<pc>\(\*.*?\*\)) |
    (?P<str>(?:'(?:[^']|'')*'|\#\d+)+) | (?P<hex>\$[0-9A-Fa-f]+) | (?P<num>\d+) |
    (?P<id>[A-Za-z_]\w*) | (?P<op>:=|<>|<=|>=|[=<>+\-*/(),;:.\[\]])
""", re.X | re.S)


def tokenize(src):
    out, pos = [], 0
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise PascalError(f"cannot read {src[pos:pos + 30]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "lc", "bc", "pc"):
            continue
        v = m.group(kind)
        if kind == "str":
            s = ""
            for part in re.findall(r"'(?:[^']|'')*'|\#\d+", v):
                s += chr(int(part[1:])) if part[0] == "#" else part[1:-1].replace("''", "'")
            out.append(("str", s))
        elif kind == "hex":
            out.append(("num", int(v[1:], 16)))
        elif kind == "num":
            out.append(("num", int(v)))
        elif kind == "id":
            out.append(("id", v.lower()))
        else:
            out.append(("op", v))
    out.append(("eof", None))
    return out


def extract(code, name):
    """The source of routine name (header to its final end;) from a [Code] section."""
    m = re.search(r"^(function|procedure)\s+" + re.escape(name) + r"\b", code, re.M | re.I)
    if not m:
        raise PascalError(f"no routine {name}")
    toks_src = code[m.start():]
    # find the body's matching end: count begin/try/case/repeat vs end/until after the first top-level begin
    depth, pos, seen = 0, 0, False
    for t in TOKEN.finditer(toks_src):
        if t.lastgroup != "id":
            continue
        w = t.group("id").lower()
        if w in ("begin", "try", "case"):
            depth += 1
            seen = True
        elif w == "repeat":
            depth += 1
        elif w in ("end", "until"):
            depth -= 1
            if seen and depth == 0:
                pos = t.end()
                break
    if not pos:
        raise PascalError(f"no end for {name}")
    rest = toks_src[pos:]
    semi = rest.index(";")
    return toks_src[:pos + semi + 1]


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k]

    def take(self, kind=None, val=None):
        tok = self.t[self.i]
        if (kind and tok[0] != kind) or (val is not None and tok[1] != val):
            raise PascalError(f"expected {val or kind}, got {tok}")
        self.i += 1
        return tok

    def at(self, kind, val=None):
        tok = self.t[self.i]
        return tok[0] == kind and (val is None or tok[1] == val)

    def routine(self):
        kind = self.take("id")[1]
        name = self.take("id")[1]
        params = []
        if self.at("op", "("):
            self.take("op", "(")
            while not self.at("op", ")"):
                byref = False
                if self.at("id", "var") or self.at("id", "const"):
                    byref = self.take("id")[1] == "var"
                names = [self.take("id")[1]]
                while self.at("op", ","):
                    self.take("op", ",")
                    names.append(self.take("id")[1])
                self.take("op", ":")
                self.take("id")
                params += [(n, byref) for n in names]
                if self.at("op", ";"):
                    self.take("op", ";")
            self.take("op", ")")
        if kind == "function":
            self.take("op", ":")
            self.take("id")
        self.take("op", ";")
        consts, lvars = {}, []
        if self.at("id", "const"):
            # ISCC 6.7.3 refuses a routine's own const section ("'BEGIN' expected", the 2026-11-26 compile)
            raise PascalError(f"{name}: a local const section does not compile in Inno's Pascal Script")
        while self.at("id", "var"):
            sec = self.take("id")[1]
            while self.at("id") and not self.at("id", "begin") and not self.at("id", "var") and not self.at("id", "const"):
                names = [self.take("id")[1]]
                while self.at("op", ","):
                    self.take("op", ",")
                    names.append(self.take("id")[1])
                if sec == "const":
                    self.take("op", "=")
                    consts[names[0]] = self.expr()
                else:
                    self.take("op", ":")
                    lvars += names
                    self.take("id")
                self.take("op", ";")
        body = self.block()
        self.take("op", ";")
        return {"kind": kind, "name": name, "params": params, "consts": consts, "vars": lvars, "body": body}

    def block(self):
        self.take("id", "begin")
        stmts = self.stmts(("end",))
        self.take("id", "end")
        return ("block", stmts)

    def stmts(self, stop):
        out = []
        while not any(self.at("id", s) for s in stop):
            if self.at("op", ";"):
                self.take("op", ";")
                continue
            out.append(self.stmt())
            if self.at("op", ";"):
                self.take("op", ";")
        return out

    def stmt(self):
        if self.at("id", "begin"):
            return self.block()
        if self.at("id", "if"):
            self.take("id")
            c = self.expr()
            self.take("id", "then")
            a = self.stmt()
            b = None
            if self.at("id", "else"):
                self.take("id")
                b = self.stmt()
            return ("if", c, a, b)
        if self.at("id", "while"):
            self.take("id")
            c = self.expr()
            self.take("id", "do")
            return ("while", c, self.stmt())
        if self.at("id", "repeat"):
            self.take("id")
            body = self.stmts(("until",))
            self.take("id", "until")
            return ("repeat", body, self.expr())
        if self.at("id", "try"):
            self.take("id")
            body = self.stmts(("finally",))
            self.take("id", "finally")
            fin = self.stmts(("end",))
            self.take("id", "end")
            return ("try", body, fin)
        if self.at("id", "exit"):
            self.take("id")
            return ("exit",)
        if self.at("id", "break"):
            self.take("id")
            return ("break",)
        if self.at("id") and self.peek(1) == ("op", ":="):
            name = self.take("id")[1]
            self.take("op", ":=")
            return ("assign", name, self.expr())
        e = self.primary()
        if e[0] == "var":
            e = ("call", e[1], [])
        if e[0] != "call":
            raise PascalError(f"not a statement: {e}")
        return ("callstmt", e)

    REL = ("=", "<>", "<", ">", "<=", ">=")

    def expr(self):
        a = self.simple()
        if self.peek()[0] == "op" and self.peek()[1] in self.REL:
            op = self.take()[1]
            a = ("bin", op, a, self.simple())
        return a

    def simple(self):
        a = self.term()
        while (self.peek()[0] == "op" and self.peek()[1] in ("+", "-")) or self.at("id", "or"):
            op = self.take()[1]
            a = ("bin", op, a, self.term())
        return a

    def term(self):
        a = self.factor()
        while self.at("id", "and"):
            self.take()
            a = ("bin", "and", a, self.factor())
        return a

    def factor(self):
        if self.at("id", "not"):
            self.take()
            return ("not", self.factor())
        if self.at("op", "-"):
            self.take()
            return ("neg", self.factor())
        return self.primary()

    def primary(self):
        tok = self.take()
        if tok[0] in ("str", "num"):
            return ("lit", tok[1])
        if tok == ("op", "("):
            e = self.expr()
            self.take("op", ")")
            return e
        if tok[0] != "id":
            raise PascalError(f"unexpected {tok}")
        if tok[1] in ("true", "false"):
            return ("lit", tok[1] == "true")
        e = ("var", tok[1])
        if self.at("op", "("):
            self.take("op", "(")
            args = []
            while not self.at("op", ")"):
                args.append(self.expr())
                if self.at("op", ","):
                    self.take("op", ",")
            self.take("op", ")")
            e = ("call", tok[1], args)
        while self.at("op", ".") or self.at("op", "["):
            if self.take()[1] == ".":
                e = ("field", e, self.take("id")[1])
            else:
                e = ("index", e, self.expr())
                self.take("op", "]")
        return e


class Env:
    def __init__(self, local, glob):
        self.local, self.glob = local, glob

    def get(self, n):
        if n in self.local:
            v = self.local[n]
            return v.get() if isinstance(v, Ref) else v
        if n in self.glob:
            return self.glob[n]
        raise PascalError(f"unknown name {n}")

    def set(self, n, v):
        if n in self.local:
            if isinstance(self.local[n], Ref):
                self.local[n].set(v)
            else:
                self.local[n] = v
        elif n in self.glob:
            self.glob[n] = v
        else:
            raise PascalError(f"assignment to unknown name {n}")


class Program:
    """routines: names to load from the script's [Code]; builtins: name -> (python function, var-parameter indices);
    globals_: the [Code] globals and constants the routines read (lower-case names)."""

    def __init__(self, iss_text, routines, builtins, globals_=None):
        code = code_section(ispp_expand(iss_text))
        self.routines = {}
        for r in routines:
            d = Parser(tokenize(extract(code, r))).routine()
            self.routines[d["name"]] = d
        self.builtins = {k.lower(): v for k, v in builtins.items()}
        self.glob = {k.lower(): v for k, v in (globals_ or {}).items()}

    def call(self, name, *args):
        return self._invoke(name.lower(), [("val", a) for a in args])

    def _invoke(self, name, args):
        if name in self.routines:
            d = self.routines[name]
            if len(args) != len(d["params"]):
                raise PascalError(f"{name}: {len(args)} arguments for {len(d['params'])} parameters")
            local = {}
            for (pn, byref), a in zip(d["params"], args):
                local[pn] = a[1] if byref else (a[1].get() if isinstance(a[1], Ref) else a[1])
            for v in d["vars"]:
                local[v] = None
            if d["kind"] == "function":
                local["result"] = None
            env = Env(local, self.glob)
            for c, e in d["consts"].items():
                local[c] = self.eval(e, env)
            try:
                self.run(d["body"], env)
            except _Exit:
                pass
            return local.get("result")
        if name in self.builtins:
            fn, _ = self.builtins[name]
            return fn(*[a[1] for a in args])
        raise PascalError(f"unknown routine {name}")

    def _args(self, name, args, env):
        byref = set()
        if name in self.routines:
            byref = {i for i, (_, r) in enumerate(self.routines[name]["params"]) if r}
        elif name in self.builtins:
            byref = set(self.builtins[name][1])
        out = []
        for i, a in enumerate(args):
            if i in byref:
                if a[0] != "var":
                    raise PascalError(f"{name}: var argument {i} is not a variable")
                out.append(("ref", Ref(env, a[1])))
            else:
                out.append(("val", self.eval(a, env)))
        return out

    def run(self, s, env):
        k = s[0]
        if k == "block":
            for x in s[1]:
                self.run(x, env)
        elif k == "assign":
            env.set(s[1], self.eval(s[2], env))
        elif k == "if":
            if self.eval(s[1], env):
                self.run(s[2], env)
            elif s[3] is not None:
                self.run(s[3], env)
        elif k == "while":
            try:
                while self.eval(s[1], env):
                    self.run(s[2], env)
            except _Break:
                pass
        elif k == "repeat":
            try:
                while True:
                    for x in s[1]:
                        self.run(x, env)
                    if self.eval(s[2], env):
                        break
            except _Break:
                pass
        elif k == "try":
            try:
                for x in s[1]:
                    self.run(x, env)
            finally:
                for x in s[2]:
                    self.run(x, env)
        elif k == "exit":
            raise _Exit()
        elif k == "break":
            raise _Break()
        elif k == "callstmt":
            self.eval(s[1], env)
        else:
            raise PascalError(f"statement {k}")

    def eval(self, e, env):
        k = e[0]
        if k == "lit":
            return e[1]
        if k == "var":
            try:
                return env.get(e[1])
            except PascalError:
                if e[1] in self.routines or e[1] in self.builtins:
                    return self._invoke(e[1], [])
                raise
        if k == "call":
            if e[1] in ("string", "ansistring"):
                return self.eval(e[2][0], env)
            return self._invoke(e[1], self._args(e[1], e[2], env))
        if k == "index":
            return self.eval(e[1], env)[self.eval(e[2], env) - 1]       # strings are 1-based
        if k == "field":
            return self.eval(e[1], env)[e[2]]
        if k == "not":
            v = self.eval(e[1], env)
            return (not v) if isinstance(v, bool) else ~v
        if k == "neg":
            return -self.eval(e[1], env)
        if k == "bin":
            op, a = e[1], self.eval(e[2], env)
            if op == "and" and isinstance(a, bool):
                return a and bool(self.eval(e[3], env))      # Pascal Script short-circuits
            if op == "or" and isinstance(a, bool):
                return a or bool(self.eval(e[3], env))
            b = self.eval(e[3], env)
            return {"and": lambda: a & b, "or": lambda: a | b, "+": lambda: a + b, "-": lambda: a - b,
                    "=": lambda: a == b, "<>": lambda: a != b, "<": lambda: a < b, ">": lambda: a > b,
                    "<=": lambda: a <= b, ">=": lambda: a >= b}[op]()
        raise PascalError(f"expression {k}")
