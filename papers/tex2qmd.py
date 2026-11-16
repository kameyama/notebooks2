#!/usr/bin/env python3
"""Regenerate papers/<name>/index.qmd from a multi-file LaTeX parent.

Usage: python3 papers/tex2qmd.py <parent>/main.tex papers/<name>

Keeps the front matter of an existing index.qmd up to (not including) the
`abstract: |` line, and regenerates the abstract, the body and the tikz figures.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# LaTeX theorem environment -> Quarto cross-reference prefix.
# Quarto has no custom theorem types, so Hypothesis and (Computational) Result
# borrow exm / exr; their titles are renamed in the front matter (crossref:).
THEOREMS = {
    "theorem": "thm", "proposition": "prp", "lemma": "lem", "corollary": "cor",
    "conjecture": "cnj", "definition": "def", "remark": "rem",
    "hypothesis": "exm", "compresult": "exr", "result": "exr",
}
MATH_ENVS = {"equation", "align", "gather", "multline"}
LABEL_PREFIXES = "thm|prop|lem|cor|conj|def|hyp|cr|rem|eq|tab|fig|sec"

SPELLING = [  # British -> American (word stems; case of the first letter is kept)
    ("colour", "color"), ("behaviour", "behavior"), ("neighbour", "neighbor"),
    ("favour", "favor"), ("analogue", "analog"), ("centre", "center"),
    ("labelled", "labeled"), ("labelling", "labeling"), ("modelled", "modeled"),
    ("cancelled", "canceled"), ("cancelling", "canceling"),
    ("formulae", "formulas"), ("artefact", "artifact"), ("grey", "gray"),
    ("analyse", "analyze"), (r"programme(s?)\b", r"program\1"),
]
ISE_STEMS = (
    "normal|general|regular|special|real|organ|summar|character|recogn|factor|"
    "symmetr|parametr|diagonal|minim|maxim|optim|emphas|categor|local|stabil|"
    "linear|polar|rational|specif|util|initial|final|formal|visual|standard|"
    "quant|renormal|reorgan|antisymmetr|symmetr|rigid|digit|item|central"
)


def strip_comments(tex):
    return re.sub(r"(?<!\\)%.*", "", tex)


def flatten(path):
    """Inline \\input recursively (paths relative to the main file's directory)."""
    root = path.parent

    def load(p):
        tex = strip_comments(p.read_text())
        tex = re.sub(r"\\cmidrule(\([^)]*\))?\{[^}]*\}", "", tex)  # pandoc misreads the trim argument
        # pandoc drops the labels of \item[(N)]: keep them as text in a bullet list
        tex = re.sub(r"\\begin\{enumerate\}((?:(?!\\end\{enumerate\}).)*?\\item\[.*?)\\end\{enumerate\}",
                     r"\\begin{itemize}\1\\end{itemize}", tex, flags=re.S)
        tex = re.sub(r"\\item\[(.*?)\]", r"\\item \1 ", tex)
        # tables scaled to the text width: keep the table only
        tex = re.sub(r"\\resizebox\{\\textwidth\}\{!\}\{\s*(\\begin\{tabular\}.*?\\end\{tabular\})\s*\}", r"\1", tex, flags=re.S)
        tex = re.sub(r"\\sbox\\tabbox\{(\\input\{[^}]*\})\}\\resizebox\{\\textwidth\}\{!\}\{\\usebox\\tabbox\}", r"\1", tex)
        return re.sub(r"\\input\{([^}]*)\}", lambda m: load(tex_path(root, m.group(1))), tex)

    return load(path)


def tex_path(root, name):
    p = root / name
    return p if p.suffix == ".tex" else p.with_name(p.name + ".tex")


def scan_labels(tex):
    """Map each LaTeX label to a Quarto id, from the environment it sits in."""
    ids, stack, appendix, used = {}, [], False, set()
    token = re.compile(r"\\(begin|end)\{(\w+)\*?\}|\\(appendix)\b|\\label\{([^}]*)\}")
    for m in token.finditer(tex):
        if m.group(1) == "begin":
            stack.append(m.group(2))
        elif m.group(1) == "end":
            if stack and stack[-1] == m.group(2):
                stack.pop()
        elif m.group(3):
            appendix = True
        else:
            label = m.group(4)
            prefix = "sec"
            for env in reversed(stack):
                if env in THEOREMS:
                    prefix = THEOREMS[env]
                elif env in MATH_ENVS:
                    prefix = "eq"
                elif env == "table":
                    prefix = "tbl"
                elif env == "figure":
                    prefix = "fig"
                else:
                    continue
                break
            stem = re.sub(rf"^({LABEL_PREFIXES}):", "", label)
            new = prefix + "-" + re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")
            assert new not in used, f"duplicate id {new}"
            used.add(new)
            ids[label] = new
    return ids


def extract_figures(tex, preamble, outdir):
    """Compile each tikzpicture to fig<N>.svg and replace it by \\includegraphics."""
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        name = f"fig{count}.svg"
        with tempfile.TemporaryDirectory() as tmp:
            src = "\\documentclass[dvisvgm]{standalone}\n" + preamble + "\\begin{document}\n" + m.group(0) + "\n\\end{document}\n"
            Path(tmp, "fig.tex").write_text(src)
            subprocess.run(["latex", "-interaction=nonstopmode", "fig.tex"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(["dvisvgm", "--no-fonts", "--exact-bbox", "fig.dvi", "-o", "fig.svg"], cwd=tmp, check=True, capture_output=True)
            svg = Path(tmp, "fig.svg").read_text()
        # white background: the site theme is dark
        svg = re.sub(r"(<svg[^>]*>)", r"\1\n<rect x='-1000' y='-1000' width='3000' height='3000' fill='white'/>", svg, count=1)
        (outdir / name).write_text(svg)
        return f"\\includegraphics{{{name}}}"

    tex = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", repl, tex, flags=re.S)
    # pandoc writes a figure environment as raw HTML; pass it as a marked paragraph instead
    tex = re.sub(r"\\begin\{figure\}.*?\\includegraphics\{([^}]*)\}\s*\\caption\{(.*?)\}\\label\{([^}]*)\}\s*\\end\{figure\}",
                 r"\n\nFIGURE(\1)(\3) \2\n\n", tex, flags=re.S)
    return tex, count


def pandoc(tex, cwd):
    r = subprocess.run(["quarto", "pandoc", "-f", "latex", "-t", "markdown", "--wrap=none"],
                       input=tex, cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout


def young(m):
    """\\yng(2,1) -> \\ydBA (macros defined in the hidden block at the top of the page)."""
    return "\\yd" + "".join(chr(64 + int(r)) for r in m.group(1).split(","))


def young_macros(names):
    lines = []
    for name in sorted(names):
        rows = [ord(c) - 64 for c in name[3:]]
        body = r"\\[-0.55em]".join("&" + r"\!\!\;".join([r"\square"] * r) for r in rows)
        lines.append(rf"\newcommand{{{name}}}{{{{\scriptsize\begin{{aligned}}{body}\end{{aligned}}}}}}")
    return "::: {.hidden}\n$$\n" + "\n".join(lines) + "\n$$\n:::\n"


def split_title(line):
    """'**Theorem 3** (name). body' -> (name or None, body)."""
    m = re.match(r"\*\*[A-Za-z ]+ \d+\*\*", line)
    if not m:
        return None, line
    rest = line[m.end():]
    if rest.startswith(" ("):
        depth = 0
        for i, c in enumerate(rest):
            depth += (c == "(") - (c == ")")
            if c == ")" and depth == 0:
                return rest[2:i], rest[i + 1:].lstrip(". ")
    return None, rest.lstrip(". ")


def convert_theorems(md, ids):
    out, auto = [], 0
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(:{3,}) (?:\{#(\S+) \.(\w+)\}|(\w+))\s*$", line)
        colons, label, env = (m.group(1), m.group(2), m.group(3) or m.group(4)) if m else ("", None, None)
        if env in THEOREMS:
            if label:
                new = ids[label]
            else:
                auto += 1
                new = f"{THEOREMS[env]}-unlabeled-{auto}"
            name, body = split_title(lines[i + 1])
            out.append(f"{colons} {{#{new}}}")
            if name:
                out += [f"## {name}", ""]
            out.append(body)
            i += 2
        elif env == "proof":
            m2 = re.match(r"\*(.*?)\.\* ?", lines[i + 1])
            title = m2.group(1)
            out.append(colons + (" {.proof}" if title == "Proof" else f' {{.proof name="{title}"}}'))
            out.append(lines[i + 1][m2.end():])
            i += 2
        else:
            out.append(line)
            i += 1
    return re.sub(r"\s*◻$", "", "\n".join(out), flags=re.M)


def convert_math(md, ids):
    # pandoc's whitespace is kept: display math inside a list item is indented
    def strip_labels(body):
        labels = re.findall(r"\\label\{([^}]*)\}", body)
        body = re.sub(r"\\label\{[^}]*\}\n?", "", body)
        return labels, re.sub(r"\\nonumber\b", "", body)

    def tag(labels):
        return f" {{#{ids[labels[0]]}}}" if labels else ""

    def repl(m):
        env, body = m.group(1), m.group(2)
        indent = re.search(r"[ \t]*$", body).group(0)
        labels, clean = strip_labels(body)
        if env == "equation":
            return f"$${clean}$$" + tag(labels)
        if len(labels) > 1:  # one display per row (Quarto allows one label per display)
            rows = []
            for row in re.split(r"\\\\\s*", body):
                ls, r = strip_labels(row)
                rows.append(f"$${r.replace('&', '').rstrip()}\n{indent}$$" + tag(ls))
            return f"\n\n{indent}".join(rows)
        inner = {"align": "aligned", "gather": "gathered"}[env]
        return f"$$\\begin{{{inner}}}{clean}\\end{{{inner}}}$$" + tag(labels)

    return re.sub(r"\$\$\\begin\{(equation|align|gather)\}(.*?)\\end\{\1\}\$\$", repl, md, flags=re.S)


def convert_refs(md, ids):
    def repl(m):
        ref = f"[-@{ids[m.group(1)]}]"
        return f"({ref})" if m.group(2) == "eqref" else ref

    md = re.sub(r'\[[^\]\[]*(?:\\\[[^\]]*\\\])?\]\(#([^)]+)\)\{reference-type="(ref|eqref)" reference="[^"]*"\}', repl, md)
    assert "reference-type" not in md, "unconverted reference"
    return md


def convert_headings(md, ids, tex):
    """Section ids; appendices are lettered by hand (Quarto would continue the section numbers)."""
    appendix_labels = set(re.findall(r"\\section\{[^\n]*\}\\label\{([^}]*)\}", tex.split("\\appendix", 1)[-1]))
    out, letter, sub, numbers = [], 0, 0, {}
    for line in md.split("\n"):
        m = re.match(r"^(#+) (.*?)(?: \{#([^ }]+)[^}]*\})?$", line)
        if m:
            level, title, label = len(m.group(1)), m.group(2), m.group(3)
            new = ids.get(label, label)
            if level == 1 and label in appendix_labels:
                letter, sub = letter + 1, 0
                number = chr(64 + letter)
                line = f"# Appendix {number}: {title} {{#{new} .appendix .unnumbered}}"
            elif level == 2 and letter:
                sub += 1
                number = f"{chr(64 + letter)}.{sub}"
                line = f"## {number} {title} {{#{new} .unnumbered}}" if new else f"## {number} {title} {{.unnumbered}}"
            else:
                number = None
                if label in ids:
                    line = f"{m.group(1)} {title} {{#{new}}}"
            if number and new:
                numbers[new] = number
        out.append(line)
    md = "\n".join(out)
    return re.sub(r"\[-@(sec-[\w-]+)\]", lambda m: f"[{numbers[m.group(1)]}](#{m.group(1)})" if m.group(1) in numbers else m.group(0), md)


def american(md):
    def fix(text):
        for uk, us in SPELLING:
            text = re.sub(uk, us, text)
            text = re.sub(uk.capitalize(), us.capitalize(), text)
        text = re.sub(rf"\b((?:un|re|anti)?(?:{ISE_STEMS})\w*?)is(e|es|ed|ing|ation|ations|able)\b", r"\1iz\2", text, flags=re.I)
        return text

    # leave citations, cross-references, attributes and math untouched
    parts = re.split(r"(\$\$.*?\$\$|\$[^$\n]*\$|\[[^\]]*@[^\]]*\]|\{[#.][^}]*\}|\]\([^)]*\))", md, flags=re.S)
    return "".join(p if i % 2 else fix(p) for i, p in enumerate(parts))


def convert(md, ids, tex):
    md = convert_refs(md, ids)
    md = convert_headings(md, ids, tex)  # before the theorems, whose titles are also written as ## lines
    md = convert_theorems(md, ids)
    md = convert_math(md, ids)
    md = re.sub(r"^FIGURE\(([^)]*)\)\(([^)]*)\) (.*)$", lambda m: f"![{m.group(3)}]({m.group(1)}){{#{ids[m.group(2)]}}}", md, flags=re.M)
    # tables: ids on captions
    md = re.sub(r"\{#((?:fig|tab):[^ }]+)([^}]*)\}", lambda m: f"{{#{ids[m.group(1)]}}}", md)
    md = md.replace("\\bm{", "\\boldsymbol{").replace("\\protect", "")
    md = re.sub(r"\\yng\(([\d,]+)\)", young, md)
    return american(md)


def main():
    main_tex, outdir = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    tex = flatten(main_tex)
    ids = scan_labels(tex)
    preamble = tex.split("\\documentclass", 1)[1].split("\n", 1)[1].split("\\title", 1)[0]
    preamble = re.sub(r"\\(usepackage\[[^\]]*\]\{(biblatex|hyperref|geometry)\}|addbibresource\{[^}]*\}|DeclareFieldInputHandler.*|AtEveryBibitem.*)", "", preamble)
    tex, _ = extract_figures(tex, preamble, outdir)
    # upright theorem bodies: Quarto applies its own theorem styling
    tex = tex.replace("\\newtheorem{theorem}", "\\theoremstyle{definition}\n\\newtheorem{theorem}", 1)

    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", tex, re.S).group(1)
    head = tex.split("\\begin{document}")[0]
    body = tex.split("\\tableofcontents", 1)[1].replace("\\printbibliography", "")
    md = convert(pandoc(head + "\\begin{document}" + body, main_tex.parent), ids, tex)
    abstract_md = convert(pandoc(head + "\\begin{document}" + abstract + "\\end{document}", main_tex.parent), ids, tex).strip()

    index = outdir / "index.qmd"
    front = index.read_text().split("abstract: |", 1)[0]
    macros = young_macros(set(re.findall(r"\\yd[A-Z]+", md + abstract_md)))
    abstract_block = "\n".join("  " + line if line else "" for line in abstract_md.split("\n"))
    index.write_text(f"{front}abstract: |\n{abstract_block}\n---\n\n{macros}\n{md}")


if __name__ == "__main__":
    main()
