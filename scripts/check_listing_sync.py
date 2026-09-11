import re, pathlib, sys
import os
os.chdir(pathlib.Path(__file__).resolve().parent.parent)
root = pathlib.Path("chapters")
code = pathlib.Path("code")
bad = []
for md in sorted(root.glob("ch*.md")) + sorted(pathlib.Path("appendices").glob("*.md")):
    # find code dir: chapters/chNN-*.md -> code/chNN ; appendices/app-x-*.md -> code/app_x
    m = re.match(r"ch(\d+)-", md.name)
    d = code / (f"ch{int(m.group(1)):02d}" if m else "")
    m2 = re.match(r"app-([a-e])-", md.name)
    if m2: d = code / f"app_{m2.group(1)}"
    src = ""
    if d.exists():
        for f in sorted(d.glob("*.py")):
            # tests included: listings may mirror test files
            src += f.read_text() + "\n"
    blocks = re.findall(r"```python\n(.*?)```", md.read_text(), re.S)
    for b in blocks:
        b = b.strip()
        if len(b) < 60: continue  # skip tiny snippets
        if b in src: continue
        # allow marked illustrative snippets
        bad.append((md.name, b[:70].replace("\n"," ")))
print(f"{len(bad)} non-verbatim listings")
for name, preview in bad[:30]: print(" -", name, "|", preview)
