#!/usr/bin/env python3
"""Convert the forall x: UBC edition LaTeX sources into PreTeXt.

This is a purpose-built converter for the macros and environments used in
Latex-Files/*.tex (see forallx-ubc.sty).  It is not a general LaTeX parser.

Usage:  python3 pretext/scripts/latex2ptx.py
Writes: pretext/source/*.ptx   (chapters, appendices, preface)

Proof trees (prooftrees.sty) and Fitch-style natural deduction proofs are
emitted as <latex-image> elements, which PreTeXt turns into SVG files.  Their
display widths come from pretext/scripts/image-sizes.json, which is produced by
pretext/scripts/measure_images.py after the images have been generated once.
"""

import hashlib
import json
import os
import re
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LATEX = os.path.join(REPO, "Latex-Files")
OUT = os.path.join(REPO, "pretext", "source")
SIZES_FILE = os.path.join(HERE, "image-sizes.json")

CHAPTERS = [
    ("forallx-ubc-1-intro.tex", "chapter"),
    ("forallx-ubc-2-sentential.tex", "chapter"),
    ("forallx-ubc-3-truthtables.tex", "chapter"),
    ("forallx-ubc-4-SLmodels.tex", "chapter"),
    ("forallx-ubc-5-SLtrees.tex", "chapter"),
    ("forallx-ubc-6-SLsoundcomplete.tex", "chapter"),
    ("forallx-ubc-7-SLND.tex", "chapter"),
    ("forallx-ubc-8-predicate.tex", "chapter"),
    ("forallx-ubc-9-QLmodels.tex", "chapter"),
    ("forallx-ubc-10-QLtrees.tex", "chapter"),
    ("forallx-ubc-11-QLsoundcomplete.tex", "chapter"),
    ("forallx-ubc-12-identity.tex", "chapter"),
    ("forallx-ubc-13-QLND.tex", "chapter"),
    ("forallx-ubc-app-notation.tex", "appendix"),
    ("forallx-ubc-app-quickreference.tex", "appendix"),
]
PREFACE = "forallx-ubc-preface.tex"
SOLUTIONS = "forallx-ubc-app-solutions.tex"

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# command name -> (optional args allowed, mandatory args)
ARITY = {
    "chapter": (1, 1), "chapter*": (1, 1), "section": (1, 1), "section*": (1, 1),
    "subsection": (1, 1), "subsection*": (1, 1), "paragraph": (0, 1),
    "label": (0, 1), "ref": (0, 1), "pageref": (0, 1), "typeref": (0, 1),
    "emph": (0, 1), "textsl": (0, 1), "textit": (0, 1), "textbf": (0, 1),
    "textsc": (0, 1), "texttt": (0, 1), "textrm": (0, 1), "textsf": (0, 1),
    "define": (0, 1), "url": (0, 1), "footnote": (0, 1), "mbox": (0, 1),
    "text": (0, 1), "factoidbox": (0, 1), "script": (0, 1), "model": (0, 1),
    "extension": (0, 1), "referent": (0, 1), "ntuple": (0, 1),
    "focusnode": (0, 1), "TTbf": (0, 1), "centerline": (0, 1), "nix": (0, 1),
    "marginpar": (0, 1), "ensuremath": (0, 1), "caption": (1, 1),
    "substitute": (0, 2), "substitutesome": (0, 2),
    "solutionpart": (0, 2), "solutionsection": (0, 1),
    "multicolumn": (0, 3), "cline": (0, 1), "setlength": (0, 2),
    "setcounter": (0, 2), "addcontentsline": (0, 3), "vspace": (0, 1),
    "vspace*": (0, 1), "hspace": (0, 1), "hspace*": (0, 1), "markright": (0, 1),
    "item": (1, 0), "ex": (0, 1), "includegraphics": (1, 1),
    "tablefbox": (0, 1), "textcolor": (0, 2), "parbox": (1, 2),
    "stepcounter": (0, 1), "addtocounter": (0, 2), "thispagestyle": (0, 1),
    "pagestyle": (0, 1), "\\": (1, 0), "includepdf": (1, 1),
}

# commands that only make sense in math mode; in text mode they become <m>
MATHCMDS = {
    "eand", "eor", "eif", "eiff", "enot", "metaA", "metaB", "metaC",
    "metaSetX", "metaSetY", "metaSetZ", "forall", "exists", "models", "vdash",
    "nvdash", "bot", "neq", "emptyset", "pi", "script", "model", "extension",
    "referent", "ntuple", "substitute", "substitutesome", "Longleftrightarrow",
    "Rightarrow", "rightarrow", "leftrightarrow", "neg", "wedge", "vee",
    "supset", "equiv", "sim", "times", "ast", "oplus", "alpha", "beta", "Phi",
    "Psi", "Sigma", "langle", "rangle", "cdots", "vdots", "uparrow", "backslash",
    "checkmark", "bigvee", "not", "lor", "mathcal", "ensuremath",
}

# environments whose body is kept as raw text
RAW_ENVS = {
    "prooftree", "highlightprooftree", "ndproof", "nd", "tabular", "tabular*",
    "array", "partialmodel", "displaymath", "equation*", "equation",
    "multline*", "align*", "verbatim",
}


class Node:
    pass


class Text(Node):
    def __init__(self, s):
        self.s = s

    def __repr__(self):
        return "Text(%r)" % self.s


class Cmd(Node):
    def __init__(self, name, opt, args, raw):
        self.name, self.opt, self.args, self.raw = name, opt, args, raw

    def __repr__(self):
        return "Cmd(%s,%r,%r)" % (self.name, self.opt, self.args)


class Group(Node):
    def __init__(self, children, raw):
        self.children, self.raw = children, raw

    def __repr__(self):
        return "Group(%r)" % self.children


class Env(Node):
    def __init__(self, name, opt, args, children, raw, body_raw):
        self.name, self.opt, self.args = name, opt, args
        self.children, self.raw, self.body_raw = children, raw, body_raw

    def __repr__(self):
        return "Env(%s,%r)" % (self.name, self.children)


class Math(Node):
    def __init__(self, raw, display):
        self.raw, self.display = raw, display

    def __repr__(self):
        return "Math(%r,%s)" % (self.raw, self.display)


def strip_comments(s):
    out = []
    for line in s.split("\n"):
        i = 0
        cut = None
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2
                continue
            if c == "%":
                cut = i
                break
            i += 1
        if cut is None:
            out.append(line)
        else:
            # a comment-only line vanishes entirely (does not create a blank line)
            if line[:cut].strip() == "":
                out.append(None)
            else:
                out.append(line[:cut])
    return "\n".join(l for l in out if l is not None)


def match_brace(s, i, open_="{", close="}"):
    """s[i] == open_; return index just past the matching close."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("unbalanced %s at %d: %r" % (open_, i, s[i:i + 80]))


def skip_ws(s, i, newlines=True):
    while i < len(s) and s[i] in " \t" + ("\n" if newlines else ""):
        i += 1
    return i


def find_env_end(s, i, name):
    """Find the \\end{name} matching an already-opened \\begin{name}."""
    depth = 1
    pat = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    while True:
        m = pat.search(s, i)
        if not m:
            raise ValueError("no \\end{%s}" % name)
        if m.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start(), m.end()
        i = m.end()


class Parser:
    def __init__(self, s):
        self.s = s

    def parse(self, i=0, end=None, stop_at_brace=False):
        s = self.s
        end = len(s) if end is None else end
        nodes = []
        buf = []

        def flush():
            if buf:
                nodes.append(Text("".join(buf)))
                buf.clear()

        while i < end:
            c = s[i]
            if c == "}" and stop_at_brace:
                flush()
                return nodes, i
            if c == "{":
                flush()
                j = match_brace(s, i)
                children, _ = Parser(s).parse(i + 1, j - 1)
                nodes.append(Group(children, s[i:j]))
                i = j
                continue
            if c == "$":
                flush()
                if s.startswith("$$", i):
                    j = s.index("$$", i + 2)
                    nodes.append(Math(s[i + 2:j], True))
                    i = j + 2
                else:
                    j = i + 1
                    while True:
                        j = s.index("$", j)
                        if s[j - 1] == "\\":
                            j += 1
                            continue
                        break
                    nodes.append(Math(s[i + 1:j], False))
                    i = j + 1
                continue
            if c == "\\":
                if s.startswith("\\[", i):
                    flush()
                    j = s.index("\\]", i)
                    nodes.append(Math(s[i + 2:j], True))
                    i = j + 2
                    continue
                if s.startswith("\\(", i):
                    flush()
                    j = s.index("\\)", i)
                    nodes.append(Math(s[i + 2:j], False))
                    i = j + 2
                    continue
                m = re.compile(r"\\([A-Za-z@]+\*?|.)", re.S).match(s, i)
                name = m.group(1)
                if name.endswith("*") and name[:-1] not in ("section", "subsection", "chapter", "vspace", "hspace") and name not in ARITY:
                    name = name[:-1]
                    j = m.end() - 1
                else:
                    j = m.end()
                if name == "\n":
                    name = " "
                if name in ("&", "%", "$", "#", "_", "{", "}", " ", ",", "@", "/", ";", "!", "-", "S", "L"):
                    buf.append({"&": "&", "%": "%", "$": "$", "#": "#", "_": "_",
                                "{": "{", "}": "}", " ": " ", ",": "\u2009", "@": "",
                                "/": "", ";": " ", "!": "", "-": "", "S": "\u00a7",
                                "L": "\u0141"}[name])
                    i = j
                    continue
                flush()
                if name == "begin":
                    k = skip_ws(s, j, newlines=False)
                    e = match_brace(s, k)
                    ename = s[k + 1:e - 1].strip()
                    pos = e
                    opt, args = [], []
                    # environment arguments
                    nargs = {"multicols": 1, "tabular": 1, "tabular*": 2, "array": 1,
                             "minipage": 1, "adjustbox": 1}.get(ename, 0)
                    p2 = skip_ws(s, pos, newlines=False)
                    if p2 < len(s) and s[p2] == "[" and ename in ("genaipractice", "tabular", "minipage", "figure", "table", "array"):
                        q = match_brace(s, p2, "[", "]")
                        opt.append(s[p2 + 1:q - 1])
                        pos = q
                    for _ in range(nargs):
                        p2 = skip_ws(s, pos)
                        q = match_brace(s, p2)
                        args.append(s[p2 + 1:q - 1])
                        pos = q
                    bstart = pos
                    bend, eend = find_env_end(s, pos, ename)
                    body = s[bstart:bend]
                    if ename in RAW_ENVS:
                        nodes.append(Env(ename, opt, args, None, s[i:eend], body))
                    else:
                        children, _ = Parser(s).parse(bstart, bend)
                        nodes.append(Env(ename, opt, args, children, s[i:eend], body))
                    i = eend
                    continue
                nopt, nman = ARITY.get(name, (0, 0))
                opt, args = [], []
                pos = j
                if nopt:
                    p2 = skip_ws(s, pos, newlines=False)
                    if p2 < len(s) and s[p2] == "[":
                        q = match_brace(s, p2, "[", "]")
                        sub, _ = Parser(s).parse(p2 + 1, q - 1)
                        opt.append(sub)
                        pos = q
                for _ in range(nman):
                    p2 = skip_ws(s, pos)
                    if p2 < len(s) and s[p2] == "{":
                        q = match_brace(s, p2)
                        sub, _ = Parser(s).parse(p2 + 1, q - 1)
                        args.append((sub, s[p2 + 1:q - 1]))
                        pos = q
                    else:
                        # single-token argument, e.g. \ref x (does not occur) or \emph x
                        m2 = re.compile(r"\\[A-Za-z]+|\S").match(s, p2)
                        args.append((Parser(m2.group(0)).parse()[0], m2.group(0)))
                        pos = m2.end()
                if name in ("section*", "subsection*", "chapter*"):
                    name = name[:-1]
                nodes.append(Cmd(name, opt, args, s[i:pos]))
                i = pos
                continue
            buf.append(c)
            i += 1
        flush()
        return nodes, i


def parse(s):
    return Parser(s).parse()[0]


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

def sanitize_id(label):
    x = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")
    if not x or not x[0].isalpha():
        x = "x-" + x
    return x


class State:
    def __init__(self):
        self.labels = {}       # label -> (kind, value)  kind in div|num|part
        self.ids = set()
        self.solutions = {}    # problem label -> list of blocks
        self.solution_intro = []
        self.image_labels = set()
        self.seq_answers = {}
        self.mc_count = 0
        self.warnings = []
        try:
            with open(SIZES_FILE) as f:
                self.sizes = json.load(f)
        except FileNotFoundError:
            self.sizes = {}

    def new_id(self, base):
        base = sanitize_id(base)
        cand, k = base, 2
        while cand in self.ids:
            cand = "%s-%d" % (base, k)
            k += 1
        self.ids.add(cand)
        return cand

    def warn(self, msg):
        self.warnings.append(msg)


STATE = State()

# ---------------------------------------------------------------------------
# Block objects
# ---------------------------------------------------------------------------


class Block:
    kind = "block"

    def xml(self):
        raise NotImplementedError


class XmlBlock(Block):
    def __init__(self, x, kind="xml"):
        self.x, self.kind = x, kind

    def xml(self):
        return self.x


class Marker(Block):
    """Structural marker: chapter, section, subsection, exercises, part..."""

    def __init__(self, kind, title="", labels=None):
        self.kind, self.title = kind, title
        self.labels = labels or []
        self.id = None

    def xml(self):
        return ""


class ListBlock(Block):
    """A list.  items: list of (label_xml_or_None, [blocks])"""

    def __init__(self, style, items, cols=None):
        self.kind = "list"
        self.style = style   # ol | ul | dl
        self.items = items
        self.cols = cols

    def compact(self, limit=48):
        """True for a labelled list of short one-line items (an argument or a
        symbolization key made of formulas), which reads best as a table."""
        if self.style != "dl":
            return False
        for lab, blocks in self.items:
            if len(blocks) != 1 or blocks[0].kind != "p" or "<paragraphs" in blocks[0].xml():
                return False
            text = re.sub(r"<m>(.*?)</m>", lambda m: "x" * max(1, len(m.group(1)) // 3), blocks[0].xml())
            text = re.sub(r"<[^>]+>", "", text)
            if len(text) > limit:
                return False
        return True

    def tabular_xml(self):
        rows = []
        for lab, blocks in self.items:
            rows.append("<row><cell>%s</cell><cell>%s</cell></row>" % ((lab or "").strip(), li_content(blocks)))
        return '<tabular><col halign="right"/><col halign="left"/>%s</tabular>' % "".join(rows)

    def xml(self):
        out = []
        if self.style == "dl" and self.compact():
            return self.tabular_xml()
        if self.style == "dl":
            out.append('<dl width="%s">' % getattr(self, "width", "narrow"))
            for lab, blocks in self.items:
                out.append("<li><title>%s</title>" % (lab if lab and lab.strip() else "\u00a0"))
                out.append(blocks_to_xml(blocks, para_required=True) or "<p/>")
                out.append("</li>")
            out.append("</dl>")
        else:
            attrs = ' cols="%d"' % self.cols if self.cols else ""
            out.append("<%s%s>" % (self.style, attrs))
            for lab, blocks in self.items:
                out.append("<li>%s</li>" % li_content(blocks))
            out.append("</%s>" % self.style)
        return "<p>" + "".join(out) + "</p>"


def li_content(blocks):
    blocks = [b for b in blocks if not (isinstance(b, XmlBlock) and b.x.strip() in ("", "<p/>"))]
    if len(blocks) == 1 and isinstance(blocks[0], XmlBlock) and blocks[0].kind == "p":
        inner = blocks[0].x
        return inner[3:-4] if inner.startswith("<p>") else inner
    if not blocks:
        return ""
    return blocks_to_xml(blocks, para_required=True)


def blocks_to_xml(blocks, para_required=False):
    return "\n".join(b.xml() for b in blocks if not isinstance(b, Marker))


# ---------------------------------------------------------------------------
# Inline conversion
# ---------------------------------------------------------------------------

def math_escape(s):
    s = s.replace("\\ensuremath", "")
    s = re.sub(r"\\label\{[^}]*\}", "", s)
    return escape(s.strip())


def text_escape(s):
    s = escape(s)
    # quotes and dashes
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = s.replace("`", "\u2018").replace("'", "\u2019")
    s = s.replace("~", "\u00a0")
    return s


def is_mathish(n):
    if isinstance(n, Math) and not n.display:
        return True
    if isinstance(n, Cmd) and n.name in MATHCMDS:
        return True
    return False


class Ctx:
    """Conversion context for a file."""

    def __init__(self, chapter_key=""):
        self.ex_counter = 0
        self.seq = 0
        self.part_counter = 0
        self.chapter_key = chapter_key
        self.in_table = False
        self.cur_marker = None


def inline(nodes, ctx):
    """Convert a node list to inline PreTeXt markup (no paragraph breaks)."""
    out = []
    i = 0
    n = len(nodes)
    while i < n:
        node = nodes[i]
        # merge runs of math-ish material into one <m>
        if is_mathish(node):
            parts = []
            j = i
            while j < n:
                nd = nodes[j]
                if is_mathish(nd):
                    parts.append(nd.raw if isinstance(nd, Cmd) else nd.raw)
                    j += 1
                elif isinstance(nd, Group) and not nd.children and parts:
                    parts.append("{}")
                    j += 1
                elif isinstance(nd, Text) and nd.s.strip() == "" and "\n\n" not in nd.s and j + 1 < n and is_mathish(nodes[j + 1]):
                    parts.append(" ")
                    j += 1
                else:
                    break
            # text-mode macros may carry $...$ inside their arguments
            out.append("<m>%s</m>" % math_escape(re.sub(r"(?<!\\)\$", "", "".join(parts))))
            i = j
            continue
        out.append(inline_node(node, ctx))
        i += 1
    return "".join(out)


def arg_inline(cmd, k, ctx):
    return inline(cmd.args[k][0], ctx)


def arg_raw(cmd, k):
    return cmd.args[k][1]


SIMPLE_TEXT = {
    "ldots": "\u2026", "dots": "\u2026", "therefore": "\u2234", "LaTeX": "<latex/>",
    "TeX": "<tex/>", "copyright": "\u00a9", "quad": "\u2003", "qquad": "\u2003\u2003",
    "textbullet": "\u2022", "hfill": "", "noindent": "", "centering": "",
    "newpage": "", "pagebreak": "", "nopagebreak": "", "FloatBarrier": "",
    "phantomsection": "", "medskip": "", "smallskip": "", "bigskip": "",
    "vfill": "", "small": "", "footnotesize": "", "scriptsize": "", "large": "",
    "Large": "", "LARGE": "", "huge": "", "Huge": "", "normalsize": "",
    "sf": "", "tt": "", "bf": "", "rm": "", "it": "", "em": "", "sc": "",
    "onecolumn": "", "twocolumn": "", "raggedbottom": "", "TTon": "", "TToff": "",
    "solutions": "", "leftsolutions": "", "today": "2026", "bookversion": "",
    "forallx": "<em>forall</em>\u00a0<m>\\script{x}</m>", "blank": "_____",
    "hline": "", "vline": "", "relax": "", "item": "", "printindex": "",
    "displaystyle": "", "bigl": "", "bigr": "", "left": "", "right": "",
    "ifgenaiprompts": "", "fi": "", "center": "", "endcenter": "",
}


def inline_node(node, ctx):
    if isinstance(node, Text):
        return text_escape(node.s)
    if isinstance(node, Math):
        if node.display:
            return "<me>%s</me>" % math_escape(node.raw)
        return "<m>%s</m>" % math_escape(node.raw)
    if isinstance(node, Group):
        return inline(node.children, ctx)
    if isinstance(node, Env):
        if node.name in ("displaymath", "equation*", "equation"):
            return "<me>%s</me>" % math_escape(node.body_raw)
        if node.name in ("multline*", "align*"):
            return "<me>%s</me>" % math_escape(node.body_raw.replace("\\\\", " ").replace("&", ""))
        if node.children is not None:
            return inline(node.children, ctx)
        STATE.warn("inline raw env %s: %s" % (node.name, node.raw[:60]))
        return ""
    if isinstance(node, Cmd):
        return inline_cmd(node, ctx)
    return ""


def inline_cmd(c, ctx):
    name = c.name
    if name in SIMPLE_TEXT:
        return SIMPLE_TEXT[name]
    if name in ("emph", "textsl", "textit"):
        return "<em>%s</em>" % arg_inline(c, 0, ctx)
    if name == "define":
        return "<term>%s</term>" % arg_inline(c, 0, ctx)
    if name in ("textbf", "TTbf"):
        return "<alert>%s</alert>" % arg_inline(c, 0, ctx)
    if name == "textsc":
        return "<em>%s</em>" % arg_inline(c, 0, ctx)
    if name == "texttt":
        return "<c>%s</c>" % escape(arg_raw(c, 0))
    if name in ("textrm", "textsf", "mbox", "text", "centerline", "ensuremath", "tablefbox"):
        return arg_inline(c, 0, ctx)
    if name == "url":
        u = arg_raw(c, 0)
        return '<url href="%s" visual="%s"/>' % (escape(u), escape(re.sub(r"^https?://", "", u)))
    if name == "footnote":
        return "<fn>%s</fn>" % arg_inline(c, 0, ctx)
    if name in ("ref", "pageref", "typeref"):
        return ref_placeholder(arg_raw(c, 0).strip(), name)
    if name == "ex":
        ctx.ex_counter += 1
        lab = arg_raw(c, 0).strip()
        STATE.labels[lab] = ("num", str(ctx.ex_counter))
        return "%d." % ctx.ex_counter
    if name == "nextSeq":
        ctx.seq += 1
        return "%d, " % ctx.seq
    if name == "noSeq":
        ctx.seq += 1
        return ""
    if name == "lastSeq":
        ctx.seq += 1
        r = "and %d " % ctx.seq
        ctx.seq = 0
        return r
    if name == "focusnode":
        return arg_inline(c, 0, ctx)
    if name == "label":
        # handled at block level; inline labels map to the current division
        return "@@LABEL:%s@@" % arg_raw(c, 0).strip()
    if name in ("nix", "setlength", "setcounter", "addcontentsline", "vspace",
                "hspace", "markright", "cline", "stepcounter", "addtocounter",
                "thispagestyle", "pagestyle", "includegraphics", "includepdf",
                "caption", "textcolor"):
        if name == "textcolor":
            return arg_inline(c, 1, ctx)
        return ""
    if name == "\\":
        return " "
    if name == "multicolumn":
        return arg_inline(c, 2, ctx)
    if name == "parbox":
        return arg_inline(c, 1, ctx)
    if name in MATHCMDS:
        return "<m>%s</m>" % math_escape(re.sub(r"(?<!\\)\$", "", c.raw))
    STATE.warn("unknown inline command \\%s" % name)
    return ""


def ref_placeholder(label, kind):
    return "@@REF:%s:%s@@" % (kind, label)


# ---------------------------------------------------------------------------
# Block conversion
# ---------------------------------------------------------------------------

def split_items(children):
    """Split environment children at \\item commands -> [(Cmd item, [nodes])]."""
    items = []
    cur = None
    for nd in children:
        if isinstance(nd, Cmd) and nd.name == "item":
            cur = [nd, []]
            items.append(cur)
        elif cur is not None:
            cur[1].append(nd)
    return items


def image_block(code, kind, desc):
    code = code.strip()
    h = hashlib.sha1(code.encode()).hexdigest()[:10]
    base = "%s-%s" % (kind, h)
    label = base
    k = 2
    while label in STATE.image_labels:
        label = "%s-%d" % (base, k)
        k += 1
    STATE.image_labels.add(label)
    pt = STATE.sizes.get(base)
    return ImageBlock(label, code, pt, desc)


# width of the HTML text column, in points of LaTeX output, used to scale
# generated SVGs so that their text matches the size of the body text
PT_PER_FULL_WIDTH = 350.0


class ImageBlock(Block):
    kind = "image"

    def __init__(self, label, code, pt, desc):
        self.label, self.code, self.pt, self.desc = label, code, pt, desc

    def pct(self):
        if not self.pt:
            return 50
        return max(6, min(100, int(round(self.pt / PT_PER_FULL_WIDTH * 100))))

    def inner(self):
        return ('<latex-image label="%s">\n%s\n</latex-image>\n<shortdescription>%s</shortdescription>'
                % (self.label, escape(self.code), escape(self.desc)))

    def xml(self, width=True):
        w = ' width="%d%%"' % self.pct() if width else ""
        return "<image%s>%s</image>" % (w, self.inner())


class SideBySide(Block):
    """Panels side by side.  Each panel is a list of blocks: an image (with
    optional caption paragraphs below it), a list, or a table."""
    kind = "sbs"

    def __init__(self, panels):
        self.panels = [p if isinstance(p, list) else [p] for p in panels]

    @staticmethod
    def panel_xml(blocks):
        parts = []
        for b in blocks:
            if isinstance(b, ImageBlock):
                parts.append(b.xml(width=False))
            elif isinstance(b, ListBlock) and b.compact(limit=1000):
                parts.append(b.tabular_xml())
            elif isinstance(b, ListBlock):
                x = b.xml()
                parts.append(x[3:-4] if x.startswith("<p><") and x.endswith("</p>") else x)
            else:
                parts.append(b.xml())
        if len(parts) == 1:
            return parts[0]
        return "<stack>%s</stack>" % "".join(parts)

    def xml(self):
        n = len(self.panels)
        ws = []
        for p in self.panels:
            ims = [b for b in p if isinstance(b, ImageBlock)]
            if ims and len(p) == 1:
                ws.append(ims[0].pct())
            elif ims:
                ws.append(max(ims[0].pct(), 14))
            else:
                ws.append(96 // n)
        total = sum(ws)
        avail = 96
        if total > avail:
            ws = [max(5, int(w * avail / total)) for w in ws]
        widths = " ".join("%d%%" % w for w in ws)
        return '<sidebyside widths="%s" margins="0%%" valign="top">%s</sidebyside>' % (
            widths, "".join(self.panel_xml(p) for p in self.panels))


def nd_code(body):
    return "$\\begin{nd}\n%s\n\\end{nd}$" % body.strip("\n")


def tree_desc(body):
    return "Proof tree"


# --- tables -------------------------------------------------------------------

def expand_colspec(spec):
    spec = re.sub(r"\s+", "", spec)
    while True:
        m = re.search(r"\*\{(\d+)\}", spec)
        if not m:
            break
        j = match_brace(spec, m.end())
        inner = spec[m.end() + 1:j - 1]
        spec = spec[:m.start()] + inner * int(m.group(1)) + spec[j:]
    cols = []
    left_border = False
    i = 0
    while i < len(spec):
        ch = spec[i]
        if ch in "lcr":
            cols.append({"halign": {"l": "left", "c": "center", "r": "right"}[ch], "right": False})
            i += 1
        elif ch in "pmb" and i + 1 < len(spec) and spec[i + 1] == "{":
            j = match_brace(spec, i + 1)
            cols.append({"halign": "left", "right": False})
            i = j
        elif ch == "|":
            if cols:
                cols[-1]["right"] = True
            else:
                left_border = True
            i += 1
        elif ch in "@>!<" and i + 1 < len(spec) and spec[i + 1] == "{":
            j = match_brace(spec, i + 1)
            if ch == "@" and "=" in spec[i:j] and cols:
                cols[-1]["sep"] = "="
            i = j
        else:
            i += 1
    return cols, left_border


def split_top(s, sep):
    """Split raw LaTeX s on separator at brace depth 0 (and outside nested envs)."""
    parts = []
    depth = 0
    envdepth = 0
    cur = []
    i = 0
    while i < len(s):
        if s.startswith("\\begin{", i):
            envdepth += 1
        elif s.startswith("\\end{", i):
            envdepth -= 1
        if s.startswith(sep, i) and depth == 0 and envdepth == 0 and not (sep == "&" and i > 0 and s[i - 1] == "\\"):
            parts.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        c = s[i]
        if c == "\\" and i + 1 < len(s) and not s.startswith(sep, i):
            cur.append(s[i:i + 2])
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


def tabular_block(body, colspec, ctx, partial=False):
    if partial:
        cols = [{"halign": "right", "right": False, "sep": "="}, {"halign": "left", "right": False}]
        left = False
    else:
        cols, left = expand_colspec(colspec)
    rows = split_top(body, "\\\\")
    out_rows = []
    pending_top = False
    for r in rows:
        r2 = r
        hl = 0
        clines = []
        # leading \hline / \cline belong to the border above this row
        while True:
            r2s = r2.lstrip()
            if r2s.startswith("[") and out_rows is not None and r2s[:6].count("]"):
                # \\[2pt] spacing argument
                m = re.match(r"\[[^\]]*\]", r2s)
                if m:
                    r2 = r2s[m.end():]
                    continue
            m = re.match(r"\\hline", r2s)
            if m:
                hl += 1
                r2 = r2s[m.end():]
                continue
            m = re.match(r"\\cline\{(\d+)-(\d+)\}", r2s)
            if m:
                clines.append((int(m.group(1)), int(m.group(2))))
                r2 = r2s[m.end():]
                continue
            break
        if hl or clines:
            if out_rows:
                prev = out_rows[-1]
                if hl:
                    prev["bottom"] = True
                for a, b in clines:
                    prev["cbottom"].update(range(a, b + 1))
            else:
                pending_top = pending_top or bool(hl)
        if r2.strip() == "":
            if r is rows[-1]:
                continue
            if not (hl or clines):
                out_rows.append({"cells": [], "bottom": False, "cbottom": set()})
            continue
        cells = split_top(r2, "&")
        out_cells = []
        for cell in cells:
            cs = cell.strip()
            m = re.match(r"\\multicolumn\s*\{(\d+)\}\s*\{([^}]*)\}\s*\{", cs)
            span = 1
            halign = None
            if m:
                span = int(m.group(1))
                spec = m.group(2)
                halign = {"l": "left", "c": "center", "r": "right"}.get(re.sub(r"[^lcr]", "", spec)[:1] or "c")
                j = match_brace(cs, m.end() - 1)
                cs = cs[m.end():j - 1]
            out_cells.append((span, halign, cell_inline(cs, ctx)))
        out_rows.append({"cells": out_cells, "bottom": False, "cbottom": set()})
    ncols = max([sum(c[0] for c in r["cells"]) for r in out_rows] + [len(cols)])
    while len(cols) < ncols:
        cols.append({"halign": "center", "right": False})
    x = ["<tabular%s%s>" % (' top="minor"' if pending_top else "", ' left="minor"' if left else "")]
    for c in cols[:ncols]:
        x.append('<col halign="%s"%s/>' % (c["halign"], ' right="minor"' if c["right"] else ""))
    for r in out_rows:
        x.append('<row%s>' % (' bottom="minor"' if r["bottom"] else ""))
        colno = 1
        cells = r["cells"]
        if partial and len(cells) == 2:
            cells = [cells[0], (1, None, "="), cells[1]]
        for span, halign, content in cells:
            attrs = ""
            if span > 1:
                attrs += ' colspan="%d"' % span
            if halign:
                attrs += ' halign="%s"' % halign
            if any(k in r["cbottom"] for k in range(colno, colno + span)) and not r["bottom"]:
                attrs += ' bottom="minor"'
            x.append("<cell%s>%s</cell>" % (attrs, content))
            colno += span
        x.append("</row>")
    x.append("</tabular>")
    if partial:
        # rebuild column list for the 3-column layout
        xs = "".join(x)
        xs = re.sub(r"(<tabular[^>]*>)(<col[^>]*/>)+", r'\1<col halign="right"/><col halign="center"/><col halign="left"/>', xs, count=1)
        return xs
    return "".join(x)


def nested_tabular_to_array(raw):
    """A table inside a table cell (e.g. the extension of a two-place
    relation drawn as a grid) cannot be a PreTeXt tabular; typeset it as a
    math array instead."""
    out = []
    i = 0
    while True:
        m = re.compile(r"\\begin\{tabular\}\s*(\[[a-z]\])?\s*\{").search(raw, i)
        if not m:
            out.append(raw[i:])
            break
        out.append(raw[i:m.start()])
        j = match_brace(raw, m.end() - 1)
        spec = raw[m.end():j - 1]
        bend, eend = find_env_end(raw, j, "tabular")
        body = raw[j:bend].replace("$", "")
        body = re.sub(r"\\textbf\{([^}]*)\}", r"\\mathbf{\1}", body)
        body = body.replace("\\ldots", "\\ldots ")
        out.append("$\\begin{array}{%s}%s\\end{array}$" % (spec, body))
        i = eend
    return "".join(out)


def cell_inline(raw, ctx):
    raw = raw.strip()
    if "\\begin{tabular}" in raw:
        raw = nested_tabular_to_array(raw)
    nodes = parse(raw)
    return inline(nodes, ctx).strip()


# --- the main block converter ----------------------------------------------------

DIVKINDS = ("chapter", "section", "subsection", "exercises", "part")


class BlockConverter:
    def __init__(self, ctx):
        self.ctx = ctx

    def convert(self, nodes):
        """Return list of Block objects."""
        blocks = []
        para = []
        state = {"para_title": None}

        def flush():
            content = inline(para, self.ctx).strip()
            para.clear()
            content = self.extract_labels(content, blocks)
            if content == "":
                return
            p = "<p>%s</p>" % content
            if state["para_title"] is not None:
                p = "<paragraphs><title>%s</title>%s</paragraphs>" % (state["para_title"], p)
                state["para_title"] = None
            blocks.append(XmlBlock(p, "p"))

        for nd in nodes:
            if isinstance(nd, Text):
                pieces = re.split(r"\n[ \t]*\n\s*", nd.s)
                for k, piece in enumerate(pieces):
                    if k > 0:
                        flush()
                    if piece:
                        para.append(Text(piece))
                continue
            if isinstance(nd, Cmd):
                name = nd.name
                if name in ("chapter", "section", "subsection", "solutionsection"):
                    flush()
                    if name == "solutionsection":
                        self.ctx.seq = 0
                    title = inline(nd.args[0][0], self.ctx) if name != "solutionsection" else ""
                    mk = Marker(name, title)
                    self.ctx.cur_marker = mk
                    blocks.append(mk)
                    continue
                if name == "paragraph":
                    flush()
                    state["para_title"] = inline(nd.args[0][0], self.ctx).strip()
                    continue
                if name == "practiceproblems":
                    flush()
                    self.ctx.part_counter = 0
                    mk = Marker("exercises", "Practice Exercises")
                    self.ctx.cur_marker = mk
                    blocks.append(mk)
                    continue
                if name == "problempart":
                    flush()
                    self.ctx.part_counter += 1
                    mk = Marker("part", "Part %s" % chr(64 + self.ctx.part_counter))
                    self.ctx.cur_marker = mk
                    blocks.append(mk)
                    continue
                if name == "solutionpart":
                    flush()
                    self.ctx.seq = 0
                    m = Marker("solutionpart", "")
                    m.target = arg_raw(nd, 1).strip()
                    blocks.append(m)
                    continue
                if name == "label":
                    lab = arg_raw(nd, 0).strip()
                    self.attach_label(lab, blocks)
                    continue
                if name == "factoidbox":
                    flush()
                    inner = BlockConverter(self.ctx).convert(nd.args[0][0])
                    blocks.append(XmlBlock("<assemblage>%s</assemblage>" % blocks_to_xml(inner)))
                    continue
                if name == "marginpar":
                    flush()
                    blocks.extend(BlockConverter(self.ctx).convert(nd.args[0][0]))
                    continue
                if name == "\\":
                    # forced line break: treat as paragraph break in running text
                    flush()
                    continue
                if name == "parbox":
                    flush()
                    blocks.extend(BlockConverter(self.ctx).convert(nd.args[1][0]))
                    continue
                para.append(nd)
                continue
            if isinstance(nd, Group):
                # groups that contain paragraph breaks or block material
                if self.has_blocks(nd.children):
                    flush()
                    blocks.extend(BlockConverter(self.ctx).convert(nd.children))
                else:
                    para.append(nd)
                continue
            if isinstance(nd, Math):
                para.append(nd)
                continue
            if isinstance(nd, Env):
                if nd.name in ("displaymath", "equation*", "equation", "multline*", "align*"):
                    para.append(nd)
                    continue
                flush()
                blocks.extend(self.env(nd))
                continue
        flush()
        return blocks

    def has_blocks(self, children):
        for c in children:
            if isinstance(c, Env) and c.name not in ("displaymath",):
                return True
            if isinstance(c, Text) and re.search(r"\n[ \t]*\n", c.s):
                return True
            if isinstance(c, Cmd) and c.name in ("section", "paragraph", "factoidbox", "\\"):
                return True
        return False

    def extract_labels(self, content, blocks):
        def repl(m):
            self.attach_label(m.group(1), blocks, inline_=True)
            return ""
        return re.sub(r"@@LABEL:([^@]*)@@", repl, content).strip()

    def attach_label(self, lab, blocks, inline_=False):
        # attach to an immediately preceding division marker if there is no
        # block content since (paragraph text in progress is fine)
        if blocks and isinstance(blocks[-1], Marker) and blocks[-1].kind in DIVKINDS:
            blocks[-1].labels.append(lab)
            return
        # otherwise: refer to whatever division we're in
        if lab not in STATE.labels:
            STATE.labels[lab] = ("marker", self.ctx.cur_marker)

    # environments ---------------------------------------------------------
    def env(self, nd):
        name = nd.name
        ctx = self.ctx
        if name == "flushright":
            # a signature block: one line per \\\\ in print; one paragraph here
            inner = BlockConverter(ctx).convert(nd.children)
            if inner and all(b.kind == "p" and b.xml().startswith("<p>") for b in inner):
                return [XmlBlock("<p>%s</p>" % ", ".join(b.xml()[3:-4] for b in inner), "p")]
            return inner
        if name in ("center", "flushleft", "groupitems",
                    "solutioninlist", "footnotesize", "small", "adjustbox",
                    "minipage", "figure", "document", "description*"):
            return BlockConverter(ctx).convert(nd.children)
        if name in ("prooftree", "highlightprooftree"):
            code = "\\begin{%s}%s\\end{%s}" % (name, nd.body_raw, name)
            return [image_block(code, "tree", "Proof tree")]
        if name in ("ndproof", "nd"):
            return [image_block(nd_code(nd.body_raw), "proof", "Natural deduction proof")]
        if name in ("tabular", "tabular*") and "\\begin{tabular}" in nd.body_raw:
            # a layout table holding tables: show the inner tables side by side
            inner = [b for b in BlockConverter(ctx).convert(parse(nd.body_raw)) if b.kind == "tabular"]
            if len(inner) > 1:
                return [XmlBlock('<sidebyside margins="0%%" valign="top">%s</sidebyside>' % "".join(b.xml() for b in inner), "sbs")]
            return inner
        if name in ("tabular", "tabular*"):
            spec = nd.args[-1]
            return [XmlBlock(tabular_block(nd.body_raw, spec, ctx), "tabular")]
        if name == "partialmodel":
            return [XmlBlock(tabular_block(nd.body_raw, "", ctx, partial=True), "tabular")]
        if name == "array":
            return [XmlBlock("<p><me>\\begin{array}{%s}%s\\end{array}</me></p>" % (nd.args[0], math_escape(nd.body_raw)), "p")]
        if name == "multicols":
            inner = BlockConverter(ctx).convert(nd.children)
            inner = [b for b in inner if not (isinstance(b, Marker) and b.kind == "label")]
            if inner and all(isinstance(b, ImageBlock) for b in inner):
                if len(inner) == 1:
                    return inner
                # chunk into rows of at most n
                n = int(nd.args[0]) if nd.args else 2
                rows = []
                for k in range(0, len(inner), n):
                    chunk = inner[k:k + n]
                    rows.append(SideBySide(chunk) if len(chunk) > 1 else chunk[0])
                return rows
            if len(inner) == 1 and isinstance(inner[0], ListBlock) and inner[0].style == "ol":
                inner[0].cols = int(nd.args[0]) if nd.args else 2
                return inner
            n = int(nd.args[0]) if nd.args else 2
            # several lists (e.g. arguments) side by side
            if len(inner) > 1 and all(isinstance(b, ListBlock) and simple_item_list(b) for b in inner):
                return [SideBySide(inner[k:k + n]) for k in range(0, len(inner), n)]
            # images, each optionally followed by caption paragraphs
            if inner and isinstance(inner[0], ImageBlock) and all(isinstance(b, ImageBlock) or b.kind == "p" for b in inner):
                panels = []
                for b in inner:
                    if isinstance(b, ImageBlock):
                        panels.append([b])
                    else:
                        panels[-1].append(b)
                return [SideBySide(panels[k:k + n]) if len(panels[k:k + n]) > 1 else XmlBlock(blocks_to_xml(panels[k]))
                        for k in range(0, len(panels), n)]
            return inner
        if name == "quote":
            inner = BlockConverter(ctx).convert(nd.children)
            if inner and all(isinstance(b, (ImageBlock, SideBySide)) or b.kind == "tabular" for b in inner):
                return inner
            return [XmlBlock("<blockquote>%s</blockquote>" % blocks_to_xml(inner))]
        if name == "genaipractice":
            return [self.genai(nd)]
        if name in ("itemize", "enumerate"):
            items = []
            for item, body in split_items(nd.children):
                items.append((None, BlockConverter(ctx).convert(body)))
            return [ListBlock("ul" if name == "itemize" else "ol", items)]
        if name == "description":
            items = []
            for item, body in split_items(nd.children):
                lab = inline(item.opt[0], ctx) if item.opt else ""
                items.append((lab, BlockConverter(ctx).convert(body)))
            lb = ListBlock("dl", items)
            lb.width = "medium"
            return [lb]
        if name in ("earg", "ekey"):
            return [self.earg(nd)]
        if name == "table":
            return self.table(nd)
        STATE.warn("unknown environment %s" % name)
        if nd.children is not None:
            return BlockConverter(ctx).convert(nd.children)
        return []

    def earg(self, nd):
        ctx = self.ctx
        items = []
        labelled = False
        numeric_labels = True
        for pre in nd.children:
            if isinstance(pre, Cmd) and pre.name == "item":
                break
            if isinstance(pre, Cmd) and pre.name == "label":
                self.attach_label(arg_raw(pre, 0).strip(), [])
        for item, body in split_items(nd.children):
            lab = None
            if item.opt:
                lab = inline(item.opt[0], ctx).strip()
                labelled = True
                if not re.fullmatch(r"\d+\.?", lab):
                    numeric_labels = False
            elif nd.name == "ekey" and body and isinstance(body[0], Group):
                # \item{UD:} style
                lab = inline(body[0].children, ctx).strip()
                body = body[1:]
                labelled = True
                numeric_labels = False
            blocks = BlockConverter(ctx).convert(body)
            if lab is not None and nd.name == "ekey":
                lab = lab.strip()
            items.append((lab, blocks))
        if nd.name == "ekey" or (labelled and not numeric_labels):
            for k, (lab, blocks) in enumerate(items):
                if lab is None:
                    items[k] = ("", blocks)
            lb = ListBlock("dl", items)
            lb.argument = nd.name == "earg"
            return lb
        lb = ListBlock("ol", items)
        # numeric labels like "3." record the intended number (for solutions)
        lb.numbers = []
        nxt = 1
        for lab, blocks in items:
            if lab and re.fullmatch(r"\d+\.?", lab):
                nxt = int(lab.rstrip("."))
            lb.numbers.append(nxt)
            nxt += 1
        return lb

    def genai(self, nd):
        ctx = self.ctx
        intro = ""
        if nd.opt and nd.opt[0].strip():
            intro = "<p>%s</p>" % inline(parse(nd.opt[0]), ctx).strip()
        items = []
        for item, body in split_items(nd.children):
            items.append((None, BlockConverter(ctx).convert(body)))
        lst = ListBlock("ul", items).xml()
        x = ('<note component="genai"><title>GenAI prompts for further practice</title>'
             '<p>Here are some potential GenAI prompts you might use to generate further practice problems, in case you find that helpful.</p>'
             '%s%s</note>' % (intro, lst))
        return XmlBlock(x, "genai")

    def table(self, nd):
        ctx = self.ctx
        caption = ""
        labels = []
        tabs = []
        for c in nd.children:
            if isinstance(c, Cmd) and c.name == "caption":
                caption = inline(c.args[0][0], ctx).strip()
            elif isinstance(c, Cmd) and c.name == "label":
                labels.append(arg_raw(c, 0).strip())
        inner = BlockConverter(ctx).convert(nd.children)
        tabs = [b for b in inner if b.kind == "tabular"]
        lab = labels[0] if labels else "table"
        tid = STATE.new_id(lab)
        for l in labels:
            STATE.labels[l] = ("div", tid)
        if not tabs:
            return inner
        if len(tabs) == 1:
            return [XmlBlock('<table xml:id="%s"><title>%s</title>%s</table>' % (tid, caption, tabs[0].xml()))]
        sbs = "<sidebyside>%s</sidebyside>" % "".join(t.xml() for t in tabs)
        return [XmlBlock('<figure xml:id="%s"><caption>%s</caption>%s</figure>' % (tid, caption, sbs))]


# ---------------------------------------------------------------------------
# Assembly into divisions
# ---------------------------------------------------------------------------

def slug(title):
    t = re.sub(r"<[^>]+>", "", title).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:40] or "sec"


def assign_ids(blocks, prefix):
    """Assign ids to division markers and register labels."""
    for b in blocks:
        if not isinstance(b, Marker):
            continue
        if b.kind in ("chapter", "section", "subsection", "exercises", "part"):
            if b.kind == "exercises":
                base = "%s-exercises" % prefix
            elif b.kind == "part":
                base = "%s-part-%s" % (prefix, b.title[-1].lower())
            else:
                base = "%s-%s" % (prefix, slug(b.title))
            if b.labels:
                base = b.labels[0]
            if b.kind == "chapter":
                prefix = re.sub(r"^(ch|app)[-.]", "", sanitize_id(base)).lower()
            b.id = STATE.new_id(base)
            for l in b.labels:
                STATE.labels[l] = ("marker", b)


def build_division(blocks, tag="chapter"):
    """blocks begins with a chapter Marker."""
    head = blocks[0]
    body = [b for b in blocks[1:] if not (isinstance(b, Marker) and b.kind == "label")]
    # split off exercises
    ex_idx = next((k for k, b in enumerate(body) if isinstance(b, Marker) and b.kind == "exercises"), None)
    exercises = None
    if ex_idx is not None:
        exercises = body[ex_idx:]
        body = body[:ex_idx]
    out = ['<%s xml:id="%s">' % (tag, head.id), "<title>%s</title>" % head.title]
    sec_idx = [k for k, b in enumerate(body) if isinstance(b, Marker) and b.kind == "section"]
    intro = body[:sec_idx[0]] if sec_idx else body
    has_divs = bool(sec_idx) or exercises
    if intro:
        if has_divs:
            out.append("<introduction>%s</introduction>" % blocks_to_xml(intro))
        else:
            out.append(blocks_to_xml(intro))
    for k, si in enumerate(sec_idx):
        end = sec_idx[k + 1] if k + 1 < len(sec_idx) else len(body)
        out.append(build_section(body[si:end]))
    if exercises:
        out.append(build_exercises(exercises))
    out.append("</%s>" % tag)
    return "\n".join(out)


def build_section(blocks):
    head = blocks[0]
    body = blocks[1:]
    sub_idx = [k for k, b in enumerate(body) if isinstance(b, Marker) and b.kind == "subsection"]
    out = ['<section xml:id="%s">' % head.id, "<title>%s</title>" % head.title]
    if not sub_idx:
        content = blocks_to_xml(body)
        out.append(content if content.strip() else "<p/>")
    else:
        intro = body[:sub_idx[0]]
        if intro:
            out.append("<introduction>%s</introduction>" % blocks_to_xml(intro))
        for k, si in enumerate(sub_idx):
            end = sub_idx[k + 1] if k + 1 < len(sub_idx) else len(body)
            sh = body[si]
            content = blocks_to_xml(body[si + 1:end])
            out.append('<subsection xml:id="%s"><title>%s</title>%s</subsection>' % (sh.id, sh.title, content or "<p/>"))
    out.append("</section>")
    return "\n".join(out)


def nonempty(blocks):
    return [b for b in blocks if not (isinstance(b, Marker)) and b.xml().strip() not in ("", "<p/>")]


def build_exercises(blocks):
    head = blocks[0]
    body = blocks[1:]
    part_idx = [k for k, b in enumerate(body) if isinstance(b, Marker) and b.kind == "part"]
    intro = body[:part_idx[0]] if part_idx else body
    out = ['<exercises xml:id="%s">' % head.id, "<title>Practice Exercises</title>"]
    conclusion = []
    if intro and nonempty(intro):
        out.append("<introduction>%s</introduction>" % blocks_to_xml(intro))
    for k, pi in enumerate(part_idx):
        end = part_idx[k + 1] if k + 1 < len(part_idx) else len(body)
        part = body[pi:end]
        # GenAI notes at the end of the last part go in the exercises conclusion
        while len(part) > 1 and part[-1].kind == "genai":
            conclusion.insert(0, part.pop())
        out.append(build_part(part))
    if conclusion:
        out.append("<conclusion>%s</conclusion>" % blocks_to_xml(conclusion))
    out.append("</exercises>")
    return "\n".join(out)


def solution_xml(blocks):
    x = blocks_to_xml(blocks).strip()
    return "<solution>%s</solution>" % x if x else ""


def simple_item_list(lb):
    return all(simple_item(bl) and all(b.kind == "p" for b in bl) for _, bl in lb.items)


def simple_item(blocks):
    return all(b.kind in ("p", "image", "tabular", "list", "sbs") for b in blocks)


def build_part(part):
    head = part[0]
    body = [b for b in part[1:] if b.xml().strip() not in ("", "<p/>")]
    sol = None
    for l in head.labels:
        if l in STATE.solutions:
            sol = STATE.solutions.pop(l)
            break
    out = ['<subexercises xml:id="%s">' % head.id, "<title>%s</title>" % head.title]
    lists = [k for k, b in enumerate(body) if isinstance(b, ListBlock) and b.style == "ol"]
    split = None
    seq = next((STATE.seq_answers[l] for l in head.labels if l in STATE.seq_answers), None)
    if lists and all(simple_item(bl) for _, bl in body[lists[0]].items):
        li = lists[0]
        intro, main, trailing = body[:li], body[li], body[li + 1:]
        if sol is None:
            split = (intro, main, trailing, None)
        else:
            sol_ne = nonempty(sol)
            sol_lists = [b for b in sol_ne if isinstance(b, ListBlock) and b.style == "ol"]
            if len(sol_lists) == 1:
                sl = sol_lists[0]
                pre = sol_ne[:sol_ne.index(sl)]
                post = sol_ne[sol_ne.index(sl) + 1:]
                nums = getattr(sl, "numbers", list(range(1, len(sl.items) + 1)))
                ok = (not post and len(pre) <= 2 and all(b.kind in ("p", "list") for b in pre)
                      and len(set(nums)) == len(nums) and max(nums) <= len(main.items))
                if ok:
                    per = {}
                    for n, (_, bl) in zip(nums, sl.items):
                        per[n] = pre + bl
                    split = (intro, main, trailing, per)
    group = None
    if (split is None and seq and lists and len(seq[0]) == len(body[lists[0]].items)
            and all(simple_item(bl) for _, bl in body[lists[0]].items)):
        # a "\\nextSeq" answer key: one yes/no answer per item
        li = lists[0]
        yes, no = seq[1]
        per = {k: [XmlBlock("<p>%s.</p>" % (yes if ok else no), "p")] for k, ok in enumerate(seq[0], start=1)}
        split = (body[:li], body[li], body[li + 1:], per)
        group = (yes, no)
        STATE.mc_count += len(per)
    elif split:
        group = mc_group_for(split[3], len(split[1].items))
        if group:
            STATE.mc_count += len(split[3])
    if split:
        intro, main, trailing, per = split
        if intro:
            out.append("<introduction>%s</introduction>" % blocks_to_xml(intro))
        for k, (_, bl) in enumerate(main.items, start=1):
            stmt = blocks_to_xml(bl).strip() or "<p/>"
            if not stmt.startswith("<"):
                stmt = "<p>%s</p>" % stmt
            s = solution_xml(per[k]) if per and k in per else ""
            mc = ""
            if group and per and k in per:
                ans = plain_answer(per[k])
                correct = next(o for o in group if o.lower() == ans)
                mc = choices_xml(group, correct)
            out.append("<exercise><statement>%s</statement>%s%s</exercise>" % (stmt, mc, s))
        if trailing:
            out.append("<conclusion>%s</conclusion>" % blocks_to_xml(trailing))
    else:
        stmt = blocks_to_xml(body).strip() or "<p/>"
        s = solution_xml(sol) if sol else ""
        out.append("<exercise><statement>%s</statement>%s</exercise>" % (stmt, s))
    out.append("</subexercises>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Reference resolution and output
# ---------------------------------------------------------------------------

def resolve_refs(x, cur_chapter=None):
    def repl(m):
        kind, label = m.group(1), m.group(2)
        t = STATE.labels.get(label)
        if t is None:
            STATE.warn("unresolved reference %s" % label)
            return "??"
        k, v = t
        if k == "num":
            return v
        if k == "marker":
            if v is None or v.id is None:
                STATE.warn("label %s has no division" % label)
                return "??"
            if v.kind == "part":
                letter = v.title.replace("Part ", "")
                if cur_chapter is not None and getattr(v, "chapnum", None) not in (None, cur_chapter):
                    letter += " of the Chapter %s exercises" % v.chapnum
                return '<xref ref="%s" text="custom">%s</xref>' % (v.id, letter)
            v = v.id
        if kind == "ref":
            return '<xref ref="%s" text="global"/>' % v
        return '<xref ref="%s" text="type-global"/>' % v
    x = re.sub(r"@@REF:(\w+):([^@]*)@@", repl, x)
    x = re.sub(r"@@LABEL:[^@]*@@", "", x)
    return x


def preprocess(src):
    src = strip_comments(src)
    # "Table \ref{X}": let PreTeXt name the target (it may be a figure)
    src = re.sub(r"\bTable(?:~|\s+)\\ref\{([^}]*)\}", r"\\typeref{\1}", src)
    # "Part \ref{X} on p.~\pageref{X}": the link itself is enough on the web
    src = re.sub(r"(\\ref\{([^}]*)\})\s*(?:,\s*)?on\s+(?:p\.|page)\s*(?:~|\\ |\s)\s*\\pageref\{\2\}", r"\1", src)
    # page references make no sense on the web: refer to the division instead
    src = re.sub(r"\bon\s+(?:p\.|page|pp\.)\s*(?:~|\\ |\s)\s*\\pageref\{([^}]*)\}(?:--\\pageref\{[^}]*\})?", r"in \\typeref{\1}", src)
    src = re.sub(r"\(?\b(?:p\.|page|pp\.)\s*(?:~|\\ |\s)\s*\\pageref\{([^}]*)\}(?:--\\pageref\{[^}]*\})?", r"\\typeref{\1}", src)
    # remove GenAI toggles in the preface
    src = src.replace("\\ifgenaiprompts", "").replace("\\fi\n", "\n")
    return src


FIXUPS = {
    # the print edition stars exercises with solutions; on the web the
    # solutions sit under each exercise
    "forallx-ubc-1-intro.tex": [
        (r"; the problems that are solved in the appendix are marked with a \\solutions\.",
         "; in this web edition you can also reveal each of those solutions directly beneath its exercise, "
         r"and many exercises check your answer for you when you click \\emph{Check Me}."),
    ],
    # the Quick Reference is laid out for print with font-size commands;
    # turn those into real headings
    "forallx-ubc-app-quickreference.tex": [
        (r"\{\\LARGE \\bf Tree Rules\}", r"\\section*{Tree Rules}"),
        (r"\\textbf\{\\large ([^}]*)\}", r"\\subsection*{\1}"),
        (r"\\twocolumn\[\\section\*\{\\LARGE \\bf Natural Deduction Rules\}\s*\{\\large \\bf Basic Rules\}\s*\\vspace\{1em\}\]",
         r"\\section*{Natural Deduction Rules}\n\\subsection*{Basic Rules}"),
        (r"\{\\large \\bf ([^}]*)\}", r"\\subsection*{\1}"),
        (r"(?m)^\\textsc\{([^}]*)\}", r"\\textbf{\1}"),
    ],
}


def convert_file(fname, ctx):
    with open(os.path.join(LATEX, fname)) as f:
        src = f.read()
    for pat, repl in FIXUPS.get(fname, []):
        src, k = re.subn(pat, repl, src)
        if not k:
            STATE.warn("fixup did not apply in %s: %s" % (fname, pat))
    src = preprocess(src)
    nodes = parse(src)
    return BlockConverter(ctx).convert(nodes)


DIVISION_TAGS = {"chapter", "section", "subsection", "appendix", "preface",
                 "introduction", "conclusion", "solutions"}


def postprocess(x):
    """Repair constructs that are legal LaTeX but not legal PreTeXt in context."""
    from lxml import etree
    root = etree.fromstring(x.encode())
    for me in list(root.iter("me")):
        me.tag = "md"
    for a in list(root.iter("assemblage")):
        parent = a.getparent()
        if parent.tag not in DIVISION_TAGS:
            # boxes are only allowed at division level: unwrap
            idx = parent.index(a)
            for k, c in enumerate(list(a)):
                parent.insert(idx + k, c)
            if a.tail and a.tail.strip():
                STATE.warn("text lost after unwrapped assemblage")
            parent.remove(a)
    for pg in list(root.iter("paragraphs")):
        if pg.getparent().tag in DIVISION_TAGS - {"introduction", "conclusion"}:
            continue
        title = pg.find("title")
        ps = [c for c in pg if c.tag != "title"]
        parent = pg.getparent()
        idx = parent.index(pg)
        if ps and ps[0].tag == "p":
            al = etree.Element("alert")
            for c in title:
                al.append(c)
            al.text = title.text or ""
            al.tail = " " + (ps[0].text or "")
            ps[0].text = None
            ps[0].insert(0, al)
        for k, c in enumerate(ps):
            parent.insert(idx + k, c)
        parent.remove(pg)
    for row in root.iter("row"):
        if len(row) == 0:
            etree.SubElement(row, "cell")
    for sbs in list(root.iter("sidebyside")):
        if len(sbs) == 0:
            sbs.getparent().remove(sbs)
    return etree.tostring(root, encoding="unicode")


def pretty(x):
    """Light pretty-printing: newline before block-level tags."""
    x = re.sub(r"\n{2,}", "\n", x)
    x = re.sub(r"(?<!\n)(<(?:p|section|subsection|exercises|subexercises|exercise|statement|solution|introduction|conclusion|title|image|tabular|table|figure|sidebyside|assemblage|note|paragraphs|blockquote|ol|ul|dl|li|row)[ >])", r"\n\1", x)
    return x.strip() + "\n"


SEQ_PHRASES = {
    "are sentences": ("A sentence", "Not a sentence"),
    "are logically equivalent": ("Logically equivalent", "Not logically equivalent"),
    "are consistent": ("Consistent", "Inconsistent"),
    "are valid": ("Valid", "Invalid"),
    "are true": ("True", "False"),
    "are true in the model": ("True in the model", "False in the model"),
}


def read_seq_answers():
    """Solutions written as "\\nextSeq\\noSeq...\\lastSeq are valid." list the
    items that have some property.  Record them as per-item yes/no answers so
    those exercises can become self-checking multiple choice questions."""
    with open(os.path.join(LATEX, SOLUTIONS)) as f:
        src = strip_comments(f.read())
    pieces = re.split(r"\\solutionpart\{[^}]*\}\{([^}]*)\}", src)
    for label, body in zip(pieces[1::2], pieces[2::2]):
        body = re.split(r"\\solutionsection", body)[0]
        toks = re.findall(r"\\(nextSeq|noSeq|lastSeq)", body)
        if not toks:
            continue
        rest = body[body.rindex("\\lastSeq") + len("\\lastSeq"):].strip()
        m = re.match(r"(are [a-z ]+?)\.\s*$", rest)
        if not m or m.group(1) not in SEQ_PHRASES or len(re.sub(r"\\(next|no|last)Seq", "", body).strip()) > 0 and not m:
            continue
        STATE.seq_answers[label] = ([t != "noSeq" for t in toks], SEQ_PHRASES[m.group(1)])


MC_GROUPS = [
    ("Tautology", "Contradiction", "Contingent"),
    ("Consistent", "Inconsistent"),
    ("Valid", "Invalid"),
    ("True", "False"),
]


def plain_answer(blocks):
    if not blocks:
        return None
    x = blocks_to_xml(blocks)
    if "<m>" in x or "<image" in x:
        return None
    t = re.sub(r"<[^>]+>", "", x).strip().rstrip(".").strip().lower()
    return t


def mc_group_for(per, n_items):
    """If every per-item answer is a single word from one vocabulary, return it."""
    if not per:
        return None
    answers = [plain_answer(b) for b in per.values()]
    for g in MC_GROUPS:
        words = [w.lower() for w in g]
        if all(a in words for a in answers):
            return g
    return None


def choices_xml(options, correct):
    return "<choices>%s</choices>" % "".join(
        '<choice%s><statement><p>%s</p></statement><feedback><p>%s</p></feedback></choice>'
        % (' correct="yes"' if o == correct else "", o,
           "Correct." if o == correct else "Not quite. Try again, or reread the relevant section.")
        for o in options)


def main():
    STATE.ids.update(["frontmatter", "backmatter", "forallx", "solutions", "index"])
    STATE.labels["app.solutions"] = ("div", "solutions")
    read_seq_answers()
    # --- solutions first, so they can be attached to the exercises
    sctx = Ctx("solutions")
    sblocks = convert_file(SOLUTIONS, sctx)
    cur = None
    for b in sblocks:
        if isinstance(b, Marker) and b.kind == "solutionpart":
            cur = b.target
            STATE.solutions[cur] = []
            continue
        if isinstance(b, Marker) and b.kind in ("chapter", "solutionsection", "label"):
            continue
        if cur is not None:
            STATE.solutions[cur].append(b)
        else:
            STATE.solution_intro.append(b)

    # --- preface
    pctx = Ctx("preface")
    pblocks = convert_file(PREFACE, pctx)
    pblocks = [b for b in pblocks if not isinstance(b, Marker)]

    results = []
    for fname, tag in CHAPTERS:
        ctx = Ctx(fname)
        blocks = convert_file(fname, ctx)
        # discard anything before the chapter marker (page-layout commands)
        k = next(k for k, b in enumerate(blocks) if isinstance(b, Marker) and b.kind == "chapter")
        blocks = blocks[k:]
        prefix = re.sub(r"forallx-ubc-|\.tex", "", fname)
        assign_ids(blocks, prefix)
        chapnum = len(results) + 1
        for b in blocks:
            if isinstance(b, Marker):
                b.chapnum = chapnum
        results.append((fname, tag, blocks))

    os.makedirs(OUT, exist_ok=True)
    includes = []
    for fname, tag, blocks in results:
        x = build_division(blocks, tag)
        x = postprocess(resolve_refs(x, blocks[0].chapnum))
        out_name = blocks[0].id + ".ptx"
        with open(os.path.join(OUT, out_name), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write("<!-- Generated from Latex-Files/%s by pretext/scripts/latex2ptx.py -->\n" % fname)
            f.write(pretty(x))
        includes.append((tag, out_name))

    with open(os.path.join(OUT, "preface.ptx"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<!-- Generated from Latex-Files/%s by pretext/scripts/latex2ptx.py -->\n" % PREFACE)
        f.write(pretty(postprocess('<preface xml:id="preface"><title>Preface to the UBC Edition</title>%s</preface>'
                       % resolve_refs(blocks_to_xml(pblocks)))))

    with open(os.path.join(OUT, "solutions-intro.ptx"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(pretty("<introduction>%s</introduction>" % resolve_refs(blocks_to_xml(STATE.solution_intro))))

    for k in STATE.solutions:
        STATE.warn("solution part not attached: %s" % k)
    for w in sorted(set(STATE.warnings)):
        print("warning:", w, file=sys.stderr)
    print("wrote %d divisions, %d images, %d multiple-choice exercises"
          % (len(includes), len(STATE.image_labels), STATE.mc_count))


if __name__ == "__main__":
    main()
