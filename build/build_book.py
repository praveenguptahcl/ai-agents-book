"""Assemble the world-class rebuild book into a print PDF. Part 1: parsing."""
import re, html, textwrap, os

W = '/home/hatch/workspace/book-rebuild'
FIGS = W + '/figures'
OUT = W + '/build/ai-agents-book-final.pdf'

ORDER = [
    'front-matter/preface.md',
    'front-matter/production-standard.md',
    'chapters/ch01-maya-opening.md',
    'chapters/ch02-odav-loop.md',
    'chapters/ch03-system-intent.md',
    'chapters/ch04-tool-contracts.md',
    'chapters/ch05-provider-integration.md',
    'chapters/ch06-tenant-isolation.md',
    'chapters/ch07-mcp.md',
    'chapters/ch08-multi-agent.md',
    'chapters/ch09-evidence-routing.md',
    'chapters/ch10-action-plane.md',
    'chapters/ch11-kill-switches.md',
    'chapters/ch12-injection.md',
    'chapters/ch13-sandbox.md',
    'chapters/ch14-ops.md',
    'chapters/ch15-evaluators.md',
    'chapters/ch16-walk-forward.md',
    'chapters/ch17-psr-dsr.md',
    'chapters/ch18-frameworks.md',
    'chapters/ch19-compliance.md',
    'chapters/ch20-lab1.md',
    'chapters/ch21-lab2.md',
    'chapters/ch22-lab3.md',
    'chapters/ch23-lab4.md',
    'appendices/app-a-a2a.md',
    'appendices/app-b-answer-keys.md',
    'appendices/app-c-prompts.md',
    'appendices/app-d-failure-semantics.md',
    'appendices/app-e-production-gate.md',
    'appendices/glossary.md',
]

# ---------------------------------------------------------------- math
MATH_SET = {
    'K', 'T', 't', 'q', 'K = 250', 'T = 5040', 't{+}1', 'k=11, n=12', '2/5',
    '(2/5)(3/5) = 6/25', '(3/5)(2/5) = 6/25', 'p_e = 12/25 = 0.48',
    '(g_4-1)/4', '(1.6449/0.1)^2 = 270.57', '(1.6449 / 0.3)^2 = 30.06',
    '3.8406 / 1.2247 = 3.1358', '= 1 + 0.5(0.36) = 1.18',
    'DSR = PSR(SR_0)', 'SR_0 = 0.5675', 'SR_0',
    'minTRL = 1 + 1.18 \\times 270.57 = 320.25',
    'minTRL = 1 + 1.32 \\times 30.06 = 40.68',
    'z = 1.6449', 'z = 1.96',
}

def _brace(s, i):
    """Parse a {...} group starting at s[i]=='{'. Returns (content, next_i)."""
    assert s[i] == '{'
    depth, j = 0, i
    while j < len(s):
        if s[j] == '{':
            depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)

def _convert_math(s):
    out, i = [], 0
    while i < len(s):
        if s.startswith('\\frac', i):
            j = i + 5
            while j < len(s) and s[j] in ' \t':
                j += 1
            a, j = _brace(s, j)
            while j < len(s) and s[j] in ' \t':
                j += 1
            b, j = _brace(s, j)
            out.append('(%s)/(%s)' % (_convert_math(a), _convert_math(b)))
            i = j
        elif s.startswith('\\sqrt', i):
            j = i + 5
            while j < len(s) and s[j] in ' \t':
                j += 1
            a, j = _brace(s, j)
            out.append('\u221a(%s)' % _convert_math(a))
            i = j
        elif s.startswith('\\hat', i):
            j = i + 4
            while j < len(s) and s[j] in ' \t':
                j += 1
            a, j = _brace(s, j)
            out.append(_convert_math(a) + '\u0302')
            i = j
        elif s.startswith('\\left', i):
            i += 5
        elif s.startswith('\\right', i):
            i += 6
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)

def tex2uni(s):
    s = _convert_math(s)
    s = s.replace('\\!', '').replace('\\,', ' ').replace('\\;', ' ')
    s = s.replace('\\:', ' ')
    for k, v in {'\\kappa': '\u03ba', '\\Phi': '\u03a6',
                 '\\gamma': '\u03b3', '\\alpha': '\u03b1',
                 '\\approx': '\u2248', '\\times': '\u00d7',
                 '\\cdot': '\u00b7', '\\geq': '\u2265',
                 '\\leq': '\u2264', '\\infty': '\u221e'}.items():
        s = s.replace(k, v)
    s = s.replace('^{-1}', '\u207b\u00b9').replace('^*', '\u2217')
    sup = {'0': '\u2070', '1': '\u00b9', '2': '\u00b2', '3': '\u00b3',
           '4': '\u2074', '5': '\u2075', '6': '\u2076', '7': '\u2077',
           '8': '\u2078', '9': '\u2079', '-': '\u207b'}
    s = re.sub(r'\^\{(-?[0-9]+)\}',
               lambda m: ''.join(sup[c] for c in m.group(1)), s)
    s = s.replace('^2', '\u00b2').replace('_3', '\u2083').replace('_4', '\u2084')
    s = s.replace('{+}1', '+1').replace('{+}', '+')
    s = s.replace('\\', '')
    return re.sub(r'\s+', ' ', s).strip()

# ---------------------------------------------------------------- inline
CODE_PH = '\x00C%d\x00'

def inline_md(text):
    codes = []
    def stash(m):
        codes.append(m.group(1))
        return CODE_PH % (len(codes) - 1)
    text = re.sub(r'`([^`]+)`', stash, text)
    # math spans: contain a backslash, or are known math tokens.
    # (Bare `$` = currency; left literal.)
    math_alt = '|'.join(sorted((re.escape(m) for m in MATH_SET),
                               key=len, reverse=True))
    math_re = re.compile(r'\$([^$]*\\[^$]*|' + math_alt + r')\$')
    text = math_re.sub(lambda m: '\x00M' + tex2uni(m.group(1)) + '\x00', text)
    text = _inline_fmt(text)
    def unstash(m):
        return '<font face="Mono">%s</font>' % html.escape(codes[int(m.group(1))])
    text = re.sub('\x00C(\\d+)\x00', unstash, text)
    text = re.sub('\x00M(.+?)\x00',
                  lambda m: '<i>%s</i>' % html.escape(m.group(1)), text)
    return text

def _inline_fmt(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    return text

# ---------------------------------------------------------------- blocks
REF = r'`figs/[a-z0-9\-]+-figspec\.md`'

def clean_fig_caption(qtext):
    c = qtext
    # (see REF for the full layout spec: DESC) -> (DESC)
    c = re.sub(r'\(see\s+' + REF + r'\s+for the full layout spec:\s*',
               '(', c, flags=re.I)
    # (see REF for the full specification). -> ''
    c = re.sub(r'\(\s*see\s+' + REF + r'\s+for the full specification\s*\)\.?',
               '', c, flags=re.I)
    # (Layout direction: REF.) -> ''
    c = re.sub(r'\(\s*layout direction:\s*' + REF + r'\s*\)\.?',
               '', c, flags=re.I)
    # (one-line reference; full spec in REF). -> ''
    c = re.sub(r'\(\s*one-line reference;\s*full spec in\s*' + REF + r'\s*\)\.?',
               '', c, flags=re.I)
    # Full visual spec: REF. -> ''
    c = re.sub(r'full visual spec:\s*' + REF + r'\.?',
               '', c, flags=re.I)
    # Full layout spec: REF. -> ''
    c = re.sub(r'full layout spec:\s*' + REF + r'\.?',
               '', c, flags=re.I)
    # Full specification in REF: -> ':'
    c = re.sub(r'\.?\s*full specification in\s*' + REF + r'\s*:',
               ':', c, flags=re.I)
    # For the figure specification (REF): -> ''
    c = re.sub(r'for the figure specification\s*\(\s*' + REF + r'\s*\)\s*:\s*',
               '', c, flags=re.I)
    # any remaining bare REF
    c = re.sub(REF, '', c)
    # tidy
    c = re.sub(r'\s+', ' ', c).strip()
    c = re.sub(r'\(\s*\)', '', c)
    c = re.sub(r'\s+([.,;:])', r'\1', c)
    c = re.sub(r'\s+', ' ', c).strip()
    if c and c[0].islower():
        c = c[0].upper() + c[1:]
    return c

def parse_md(path):
    text = open(path, encoding='utf-8').read()
    lines = text.split('\n')
    blocks = []
    i, n = 0, len(lines)
    in_code = False
    code_lang, code_buf = '', []
    while i < n:
        ln = lines[i]
        if in_code:
            if ln.strip().startswith('```'):
                blocks.append({'t': 'code', 'lang': code_lang,
                               'code': '\n'.join(code_buf)})
                in_code = False
                code_buf = []
            else:
                code_buf.append(ln)
            i += 1
            continue
        if ln.strip().startswith('```'):
            in_code = True
            code_lang = ln.strip()[3:].strip()
            i += 1
            continue
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith('# '):
            blocks.append({'t': 'h1', 'x': s[2:].strip()})
        elif s.startswith('## '):
            blocks.append({'t': 'h2', 'x': s[3:].strip()})
        elif s.startswith('### '):
            blocks.append({'t': 'h3', 'x': s[4:].strip()})
        elif s.startswith('#### '):
            blocks.append({'t': 'h4', 'x': s[5:].strip()})
        elif s == '---':
            blocks.append({'t': 'hr'})
        elif s.startswith('>'):
            buf = []
            while i < n and lines[i].strip().startswith('>'):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            qtext = ' '.join(buf)
            qm = re.search(r'figs/([a-z0-9\-]+)-figspec\.md', qtext)
            if qm:
                blocks.append({'t': 'figcall', 'base': qm.group(1),
                               'caption': clean_fig_caption(qtext)})
            else:
                blocks.append({'t': 'quote', 'x': qtext})
            continue
        elif re.match(r'^(\-|\*) ', s):
            buf = []
            while i < n and re.match(r'^(\-|\*) ', lines[i].strip()):
                buf.append(re.sub(r'^(\-|\*) ', '', lines[i].strip()))
                i += 1
            blocks.append({'t': 'ul', 'items': buf})
            continue
        elif re.match(r'^\d+\. ', s):
            buf = []
            while i < n and re.match(r'^\d+\. ', lines[i].strip()):
                buf.append(re.sub(r'^\d+\. ', '', lines[i].strip()))
                i += 1
            blocks.append({'t': 'ol', 'items': buf})
            continue
        elif s.startswith('|'):
            buf = []
            while i < n and lines[i].strip().startswith('|'):
                row = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.match(r'^:?-{2,}:?$', c) for c in row):
                    buf.append(row)
                i += 1
            if buf:
                blocks.append({'t': 'table', 'rows': buf,
                               'src': path.split('/')[-1]})
            continue
        else:
            buf = []
            while i < n:
                t2 = lines[i].strip()
                if (not t2 or t2.startswith('#') or t2 == '---'
                        or t2.startswith('>') or t2.startswith('|')
                        or t2.startswith('```')
                        or re.match(r'^(\-|\*) ', t2)
                        or re.match(r'^\d+\. ', t2)):
                    break
                buf.append(t2)
                i += 1
            para = ' '.join(buf)
            dm = re.fullmatch(r'\$\$(.+)\$\$', para)
            if dm:
                blocks.append({'t': 'math', 'x': tex2uni(dm.group(1))})
                continue
            m = re.search(r'figs/([a-z0-9\-]+)-figspec\.md', para)
            if m:
                base = m.group(1)
                blocks.append({'t': 'figcall', 'base': base,
                               'caption': clean_fig_caption(para)})
            else:
                blocks.append({'t': 'p', 'x': para})
            continue
        i += 1
    return blocks

def collect():
    blocks = []
    for rel in ORDER:
        path = W + '/' + rel
        assert os.path.exists(path), path
        blocks.extend(parse_md(path))
    # resolve figure callouts -> concrete figure files, in callout order
    counters = {}
    out = []
    for b in blocks:
        if b['t'] == 'figcall':
            base = b['base']
            counters[base] = counters.get(base, 0) + 1
            k = counters[base]
            multi = [f for f in os.listdir(FIGS)
                     if re.match(r'^%s-\d+\.png$' % re.escape(base), f)]
            if multi:
                fname = '%s-%d.png' % (base, k)
            else:
                fname = '%s.png' % base
            assert os.path.exists(FIGS + '/' + fname), fname
            out.append({'t': 'fig', 'file': fname, 'caption': b['caption']})
        else:
            out.append(b)
    return out

# ============================================================ Part 2: render
from reportlab.lib.units import inch as IN
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, PageBreak, Table, TableStyle,
                                KeepTogether, XPreformatted, HRFlowable)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage

PAGE = (6 * IN, 9 * IN)
ML = MR = 0.75 * IN
COLW = PAGE[0] - ML - MR

_L = '/usr/share/fonts/truetype/liberation/'
pdfmetrics.registerFont(TTFont('Body', _L + 'LiberationSans-Regular.ttf'))
pdfmetrics.registerFont(TTFont('BodyB', _L + 'LiberationSans-Bold.ttf'))
pdfmetrics.registerFont(TTFont('BodyI', _L + 'LiberationSans-Italic.ttf'))
pdfmetrics.registerFont(TTFont('BodyBI', _L + 'LiberationSans-BoldItalic.ttf'))
pdfmetrics.registerFont(TTFont('Mono', _L + 'LiberationMono-Regular.ttf'))
pdfmetrics.registerFont(TTFont('MonoB', _L + 'LiberationMono-Bold.ttf'))
pdfmetrics.registerFont(TTFont('MonoI', _L + 'LiberationMono-Italic.ttf'))
pdfmetrics.registerFont(TTFont('MonoBI', _L + 'LiberationMono-BoldItalic.ttf'))
pdfmetrics.registerFontFamily('Body', normal='Body', bold='BodyB',
                              italic='BodyI', boldItalic='BodyBI')
pdfmetrics.registerFontFamily('Mono', normal='Mono', bold='MonoB',
                              italic='MonoI', boldItalic='MonoBI')

INK = HexColor('#1a1a1a')
GREY = HexColor('#555555')
ACCENT = HexColor('#1f4e79')
CODEBG = HexColor('#f4f4f4')

def st(name, **kw):
    base = dict(fontName='Body', fontSize=10, leading=14.5, textColor=INK,
                spaceBefore=4, spaceAfter=4, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    'h1': st('h1', fontName='BodyB', fontSize=17, leading=22, textColor=ACCENT,
             spaceBefore=0, spaceAfter=10),
    'h2': st('h2', fontName='BodyB', fontSize=13.5, leading=17.5,
             textColor=ACCENT, spaceBefore=10, spaceAfter=6),
    'h3': st('h3', fontName='BodyB', fontSize=11.5, leading=15,
             spaceBefore=8, spaceAfter=4),
    'h4': st('h4', fontName='BodyB', fontSize=10.5, leading=14,
             spaceBefore=7, spaceAfter=3),
    'p': st('p'),
    'kicker': st('kicker', fontName='BodyI', fontSize=9.5, leading=13,
                 textColor=GREY, spaceBefore=0, spaceAfter=10),
    'quote': st('quote', fontName='BodyI', fontSize=9.5, leading=13.5,
                textColor=HexColor('#333333'), leftIndent=14,
                borderPadding=(4, 0, 4, 10), spaceBefore=6, spaceAfter=6),
    'caption': st('caption', fontSize=8.5, leading=11.5, textColor=GREY,
                  alignment=TA_CENTER, spaceBefore=3, spaceAfter=10),
    'bullet': st('bullet', leftIndent=14, bulletIndent=4, spaceBefore=2,
                 spaceAfter=2),
    'math': st('math', fontName='BodyI', fontSize=10.5, leading=15,
               alignment=TA_CENTER, spaceBefore=8, spaceAfter=8,
               textColor=INK),
    'cell': st('cell', fontSize=8.5, leading=11.5),
    'cellH': st('cellH', fontName='BodyB', fontSize=8.5, leading=11.5,
                textColor=HexColor('#ffffff')),
}
SCODE = ParagraphStyle('code', fontName='Mono', fontSize=7.4, leading=10.2,
                       textColor=INK, spaceBefore=4, spaceAfter=6,
                       backColor=CODEBG, borderPadding=6)

def fig_flowable(fname):
    img = RLImage(FIGS + '/' + fname)
    iw, ih = img.imageWidth, img.imageHeight
    scale = min(COLW / iw, 4.6 * IN / ih)
    img.drawWidth, img.drawHeight = iw * scale, ih * scale
    img.hAlign = 'CENTER'
    return img

def code_flowable(code):
    wrapped = []
    for ln in code.split('\n'):
        ln = ln.expandtabs(4)
        if len(ln) <= 72:
            wrapped.append(ln)
        else:
            parts = textwrap.wrap(ln, width=72, break_long_words=True,
                                  break_on_hyphens=False,
                                  replace_whitespace=False,
                                  drop_whitespace=False)
            wrapped.extend(parts if parts else [''])
    return XPreformatted(html.escape('\n'.join(wrapped)), SCODE)

def table_flowable(rows, widths=None):
    ncols = max(len(r) for r in rows)
    norm = [r + [''] * (ncols - len(r)) for r in rows]
    data = []
    for ri, r in enumerate(norm):
        sty = S['cellH'] if ri == 0 else S['cell']
        data.append([Paragraph(inline_md(c), sty) for c in r])
    cw = widths if widths else [COLW / ncols] * ncols
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), ACCENT),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('GRID', (0, 0), (-1, -1), 0.4, HexColor('#999999')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [HexColor('#ffffff'), HexColor('#f7f7f7')]),
    ]))
    return t

GLOSS_W = [1.0 * IN, 1.7 * IN, 1.1 * IN, 0.7 * IN]

def make_story(blocks):
    story = []
    # ---- title page
    story.append(Spacer(1, 1.9 * IN))
    story.append(Paragraph('AI Agents', st('tp', fontName='BodyB', fontSize=34,
                                          leading=38, alignment=TA_CENTER,
                                          textColor=ACCENT)))
    story.append(Spacer(1, 0.2 * IN))
    story.append(Paragraph('Systems, Safety, and Practice',
                           st('tp2', fontSize=16, leading=20,
                              alignment=TA_CENTER, textColor=INK)))
    story.append(Spacer(1, 0.35 * IN))
    story.append(Paragraph('A field guide for users, builders, operators, '
                           'and decision-makers',
                           st('tp3', fontSize=11, leading=15,
                              alignment=TA_CENTER, textColor=GREY)))
    story.append(Spacer(1, 0.5 * IN))
    story.append(Paragraph('World-Class Rebuild \u00b7 2026',
                           st('tp4', fontSize=10, alignment=TA_CENTER,
                              textColor=GREY)))
    story.append(PageBreak())
    # ---- TOC
    story.append(Paragraph('Contents', st('toctitle', fontName='BodyB',
                                          fontSize=17, leading=22,
                                          textColor=ACCENT, spaceBefore=0,
                                          spaceAfter=10)))
    toc = TableOfContents()
    toc.levelStyles = [
        st('toc0', fontSize=11, leading=15.5, spaceBefore=4, textColor=INK,
           rightIndent=0.55 * IN),
    ]
    story.append(toc)

    for b in blocks:
        t = b['t']
        if t == 'h1':
            story.append(PageBreak())
            story.append(Paragraph(inline_md(b['x']), S['h1']))
        elif t == 'h2':
            story.append(Paragraph(inline_md(b['x']), S['h2']))
        elif t == 'h3':
            story.append(Paragraph(inline_md(b['x']), S['h3']))
        elif t == 'h4':
            story.append(Paragraph(inline_md(b['x']), S['h4']))
        elif t == 'p':
            if b['x'].startswith('*Part '):
                story.append(Paragraph(inline_md(b['x']), S['kicker']))
            else:
                story.append(Paragraph(inline_md(b['x']), S['p']))
        elif t == 'math':
            story.append(Paragraph(html.escape(b['x']), S['math']))
        elif t == 'quote':
            story.append(Paragraph(inline_md(b['x']), S['quote']))
        elif t == 'hr':
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width='100%', thickness=0.5,
                                    color=HexColor('#cccccc')))
            story.append(Spacer(1, 6))
        elif t == 'ul':
            for it in b['items']:
                story.append(Paragraph(inline_md(it), S['bullet'],
                                       bulletText='\u2022'))
        elif t == 'ol':
            for k, it in enumerate(b['items'], 1):
                story.append(Paragraph(inline_md(it), S['bullet'],
                                       bulletText='%d.' % k))
        elif t == 'table':
            story.append(Spacer(1, 4))
            widths = GLOSS_W if b.get('src') == 'glossary.md' else None
            story.append(table_flowable(b['rows'], widths))
            story.append(Spacer(1, 6))
        elif t == 'code':
            story.append(code_flowable(b['code']))
        elif t == 'fig':
            story.append(KeepTogether([
                Spacer(1, 4),
                fig_flowable(b['file']),
                Paragraph(inline_md(b['caption']), S['caption']),
            ]))

    return story


def make_doc(story, recorded, mode):
    """mode 'record': collect (page, h1) pairs.
    mode 'final': draw running heads from the recorded pairs."""
    def header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Body', 8)
        canvas.setFillColor(GREY)
        if doc.page > 1:
            if mode == 'final':
                ch = None
                for pg, tx in recorded:
                    if pg <= doc.page:
                        ch = tx
                if ch:
                    canvas.drawString(ML, PAGE[1] - 0.55 * IN, ch[:70])
            canvas.drawRightString(PAGE[0] - MR, 0.55 * IN, str(doc.page))
        canvas.restoreState()

    class Doc(BaseDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph):
                if flowable.style.name == 'h1':
                    if mode == 'record':
                        recorded.append((self.page,
                                         flowable.getPlainText()))
                    self.notify('TOCEntry', (0, flowable.getPlainText(),
                                             self.page))

    frame = Frame(ML, 0.85 * IN, COLW, PAGE[1] - 1.7 * IN, id='f')
    doc = Doc(OUT, pagesize=PAGE, leftMargin=ML, rightMargin=MR,
              topMargin=0.85 * IN, bottomMargin=0.85 * IN,
              title='AI Agents: Systems, Safety, and Practice')
    doc.addPageTemplates([PageTemplate(id='p', frames=[frame],
                                       onPage=header_footer)])
    doc.multiBuild(story)
    return doc


def build():
    blocks = collect()
    recorded = []
    make_doc(make_story(blocks), recorded, 'record')
    # multiBuild records every pass; later passes are authoritative.
    # Dedupe by title, keeping the last (final-pass) page number.
    last_page = {}
    for pg, tx in recorded:
        last_page[tx] = pg
    final_recorded = sorted(last_page.items(), key=lambda kv: kv[1])
    final_recorded = [(pg, tx) for tx, pg in final_recorded]
    make_doc(make_story(blocks), final_recorded, 'final')
    print('built', OUT, os.path.getsize(OUT), 'bytes')

if __name__ == '__main__':
    build()
