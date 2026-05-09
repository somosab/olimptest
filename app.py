import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import os, re, io, json, base64, time
from groq import Groq
from docx import Document
import PyPDF2
import mammoth
from bs4 import BeautifulSoup
from PIL import Image
import numpy as np

try:
    import cohere
    COHERE_AVAILABLE = True
except ImportError:
    COHERE_AVAILABLE = False

# ══════════════════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════════════════
st.set_page_config(page_title="OlimpTest — Matematika", page_icon="🏆", layout="wide")

GROQ_API_KEY   = st.secrets.get("GROQ_API_KEY",   os.getenv("GROQ_API_KEY",   ""))
COHERE_API_KEY = st.secrets.get("COHERE_API_KEY",  os.getenv("COHERE_API_KEY", ""))

st.markdown("""
<style>
  .stApp{background:linear-gradient(135deg,#0f0f23 0%,#1a1a3e 100%);}
  h1,h2,h3{color:#FFD700!important;}
  p,li,label{color:#E0E0E0!important;}
  .stButton>button{background:linear-gradient(90deg,#FF8C00,#FFA500);
      color:white;border:none;border-radius:10px;font-weight:bold;padding:10px 20px;}
  .timer-box{background:linear-gradient(90deg,#FF4500,#FF8C00);
      padding:15px 25px;border-radius:12px;color:white;font-size:24px;
      font-weight:bold;text-align:center;}
  .timer-urgent{background:linear-gradient(90deg,#8B0000,#FF0000);
      padding:15px 25px;border-radius:12px;color:white;font-size:24px;
      font-weight:bold;text-align:center;animation:blink 1s infinite;}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.6}}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
#  KaTeX RENDER  (components.html — skriptlar ishlaydi)
# ══════════════════════════════════════════════════════
def render_math(text: str, font_size: str = "19px",
                bg: str = "rgba(255,255,255,0.05)", height: int = None):
    lines  = text.count('<br') + text.count('\n') + 1
    h      = height or max(65, min(700, lines * 36 + len(text) // 4))
    html   = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
<script defer
  src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
<script defer
  src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{
    delimiters:[
      {{left:'$$',right:'$$',display:true}},
      {{left:'$',right:'$',display:false}}
    ],throwOnError:false}});"></script>
<style>
  body{{background:{bg};color:#E0E0E0;font-size:{font_size};
       font-family:'Segoe UI',Arial,sans-serif;padding:12px 16px;
       border-radius:10px;border:1px solid rgba(255,215,0,0.2);
       margin:0;line-height:1.8;word-wrap:break-word;}}
  .katex,.katex-display{{color:#FFD700;}}
  img{{max-width:100%;border-radius:8px;margin:6px 0;display:block;}}
</style></head><body>{text}</body></html>"""
    components.html(html, height=h, scrolling=False)


# ══════════════════════════════════════════════════════
#  OMML → LaTeX  (to'liq versiya)
# ══════════════════════════════════════════════════════
MQ = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
WQ = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

NARY_OPS = {'\u222b':'\\int','\u222c':'\\iint','\u222d':'\\iiint',
            '\u2211':'\\sum','\u220f':'\\prod','\u222e':'\\oint'}
PROP_TAGS = {'rPr','fPr','radPr','naryPr','dPr','sSupPr','sSubPr','sSubSupPr',
             'funcPr','sPr','limLowPr','limUppPr','eqArrPr','mPr','ctrlPr',
             'groupChrPr','borderBoxPr','barPr','accPr','phantPr','boxPr'}
FN_MAP = {
    'sin':'\\sin','cos':'\\cos','tan':'\\tan','cot':'\\cot','tg':'\\tan','ctg':'\\cot',
    'sec':'\\sec','csc':'\\csc','log':'\\log','ln':'\\ln','exp':'\\exp',
    'lim':'\\lim','max':'\\max','min':'\\min','det':'\\det','gcd':'\\gcd',
    'arcsin':'\\arcsin','arccos':'\\arccos','arctan':'\\arctan',
}
ACC_MAP = {'\u0302':'\\hat','\u0303':'\\tilde','\u0307':'\\dot',
           '\u0308':'\\ddot','\u0305':'\\bar','\u20d7':'\\vec'}
UMATH = {
    '·':'\\cdot','×':'\\times','÷':'\\div','±':'\\pm','∓':'\\mp',
    '≤':'\\leq','≥':'\\geq','≠':'\\neq','≈':'\\approx','≡':'\\equiv',
    '∞':'\\infty','∈':'\\in','∉':'\\notin','⊂':'\\subset','⊃':'\\supset',
    '∪':'\\cup','∩':'\\cap','∅':'\\emptyset','∴':'\\therefore',
    '→':'\\rightarrow','←':'\\leftarrow','↔':'\\leftrightarrow',
    '⇒':'\\Rightarrow','⇔':'\\Leftrightarrow',
    'α':'\\alpha','β':'\\beta','γ':'\\gamma','δ':'\\delta','ε':'\\varepsilon',
    'ζ':'\\zeta','η':'\\eta','θ':'\\theta','λ':'\\lambda','μ':'\\mu',
    'π':'\\pi','ρ':'\\rho','σ':'\\sigma','τ':'\\tau','φ':'\\varphi',
    'ψ':'\\psi','ω':'\\omega','Δ':'\\Delta','Σ':'\\Sigma','Π':'\\Pi',
    'Ω':'\\Omega','Γ':'\\Gamma','Λ':'\\Lambda',
}

def umath(t: str) -> str:
    for ch, lat in UMATH.items():
        t = t.replace(ch, lat)
    return t

def tname(el) -> str:
    t = el.tag
    if t.startswith(MQ): return t[len(MQ):]
    if t.startswith(WQ): return t[len(WQ):]
    return t

def omml(el) -> str:
    tn = tname(el)
    if tn in PROP_TAGS: return ''
    if tn in ('oMath','oMathPara','e','num','den','fName','lim','sub','sup','deg','mr'):
        return ''.join(omml(c) for c in el)
    if tn == 'r':
        return umath(''.join(t.text or '' for t in el.findall(f'{MQ}t')))
    if tn == 't':
        return umath(el.text or '')
    if tn == 'f':
        pr = el.find(f'{MQ}fPr'); ftype = ''
        if pr is not None:
            ft = pr.find(f'{MQ}type')
            if ft is not None: ftype = ft.get(f'{MQ}val', '')
        n = omml(el.find(f'{MQ}num')) if el.find(f'{MQ}num') is not None else ''
        d = omml(el.find(f'{MQ}den')) if el.find(f'{MQ}den') is not None else ''
        if ftype == 'skw':   return f'{n}/{d}'
        if ftype == 'noBar': return f'\\binom{{{n}}}{{{d}}}'
        if ftype == 'lin':   return f'{n}/{d}'
        return f'\\frac{{{n}}}{{{d}}}'
    if tn == 'rad':
        pr = el.find(f'{MQ}radPr'); hide = False
        if pr is not None:
            dh = pr.find(f'{MQ}degHide')
            if dh is not None: hide = dh.get(f'{MQ}val', '1') not in ('0','false')
        e   = omml(el.find(f'{MQ}e')).strip()   if el.find(f'{MQ}e')   is not None else ''
        deg = omml(el.find(f'{MQ}deg')).strip() if el.find(f'{MQ}deg') is not None else ''
        return f'\\sqrt{{{e}}}' if (hide or not deg) else f'\\sqrt[{deg}]{{{e}}}'
    if tn == 'sSup':
        b = omml(el.find(f'{MQ}e')).strip()   if el.find(f'{MQ}e')   is not None else ''
        s = omml(el.find(f'{MQ}sup')).strip() if el.find(f'{MQ}sup') is not None else ''
        return f'{b}^{{{s}}}'
    if tn == 'sSub':
        b = omml(el.find(f'{MQ}e')).strip()   if el.find(f'{MQ}e')   is not None else ''
        s = omml(el.find(f'{MQ}sub')).strip() if el.find(f'{MQ}sub') is not None else ''
        return f'{b}_{{{s}}}'
    if tn == 'sSubSup':
        b = omml(el.find(f'{MQ}e')).strip()   if el.find(f'{MQ}e')   is not None else ''
        s = omml(el.find(f'{MQ}sub')).strip() if el.find(f'{MQ}sub') is not None else ''
        p = omml(el.find(f'{MQ}sup')).strip() if el.find(f'{MQ}sup') is not None else ''
        return f'{{{b}}}_{{{s}}}^{{{p}}}'
    if tn == 'nary':
        pr = el.find(f'{MQ}naryPr'); op = '\\sum'
        if pr is not None:
            ch_el = pr.find(f'{MQ}chr')
            if ch_el is not None: op = NARY_OPS.get(ch_el.get(f'{MQ}val',''),'\\sum')
        lo = omml(el.find(f'{MQ}sub')) if el.find(f'{MQ}sub') is not None else ''
        hi = omml(el.find(f'{MQ}sup')) if el.find(f'{MQ}sup') is not None else ''
        bd = omml(el.find(f'{MQ}e'))   if el.find(f'{MQ}e')   is not None else ''
        res = op
        if lo: res += f'_{{{lo}}}'
        if hi: res += f'^{{{hi}}}'
        return res + f'{{{bd}}}'
    if tn == 'func':
        fn = omml(el.find(f'{MQ}fName')).strip() if el.find(f'{MQ}fName') is not None else ''
        c  = omml(el.find(f'{MQ}e')).strip()     if el.find(f'{MQ}e')     is not None else ''
        return f'{FN_MAP.get(fn, fn)}\\left({c}\\right)'
    if tn == 'd':
        pr = el.find(f'{MQ}dPr'); left, right = '(', ')'
        if pr is not None:
            beg = pr.find(f'{MQ}begChr'); end = pr.find(f'{MQ}endChr')
            if beg is not None: left  = beg.get(f'{MQ}val','(') or '.'
            if end is not None: right = end.get(f'{MQ}val',')') or '.'
        e_els = el.findall(f'{MQ}e')
        inner = ','.join(omml(e) for e in e_els) if e_els else ''
        bmap  = {'|':'|','⌈':'\\lceil','⌉':'\\rceil','⌊':'\\lfloor','⌋':'\\rfloor'}
        return f'\\left{bmap.get(left,left)}{inner}\\right{bmap.get(right,right)}'
    if tn == 'm':
        rows = el.findall(f'{MQ}mr')
        lr   = [' & '.join(omml(c) for c in r.findall(f'{MQ}e')) for r in rows]
        return '\\begin{pmatrix}' + ' \\\\ '.join(lr) + '\\end{pmatrix}'
    if tn == 'acc':
        pr = el.find(f'{MQ}accPr'); ch = ''
        if pr is not None:
            ce = pr.find(f'{MQ}chr')
            if ce is not None: ch = ce.get(f'{MQ}val','')
        inner = omml(el.find(f'{MQ}e')) if el.find(f'{MQ}e') is not None else ''
        return f'{ACC_MAP.get(ch,"\\hat")}{{{inner}}}'
    if tn == 'bar':
        e = el.find(f'{MQ}e')
        return f'\\overline{{{omml(e) if e is not None else ""}}}'
    if tn == 'limLow':
        b = omml(el.find(f'{MQ}e'))   if el.find(f'{MQ}e')   is not None else ''
        l = omml(el.find(f'{MQ}lim')) if el.find(f'{MQ}lim') is not None else ''
        return f'\\underset{{{l}}}{{{b}}}'
    if tn == 'limUpp':
        b = omml(el.find(f'{MQ}e'))   if el.find(f'{MQ}e')   is not None else ''
        l = omml(el.find(f'{MQ}lim')) if el.find(f'{MQ}lim') is not None else ''
        return f'\\overset{{{l}}}{{{b}}}'
    if tn in ('box','borderBox'):
        e = el.find(f'{MQ}e')
        return f'\\boxed{{{omml(e) if e is not None else ""}}}'
    if tn == 'eqArr':
        return ('\\begin{cases}'
                + ' \\\\ '.join(omml(r) for r in el.findall(f'{MQ}e'))
                + '\\end{cases}')
    if tn == 'groupChr':
        e  = el.find(f'{MQ}e')
        pr = el.find(f'{MQ}groupChrPr'); ch = ''
        if pr is not None:
            ce = pr.find(f'{MQ}chr')
            if ce is not None: ch = ce.get(f'{MQ}val','')
        inner = omml(e) if e is not None else ''
        if ch == '\u23de': return f'\\overbrace{{{inner}}}'
        if ch == '\u23df': return f'\\underbrace{{{inner}}}'
        return inner
    return ''.join(omml(c) for c in el)


# ══════════════════════════════════════════════════════
#  PARAGRAPH MATN  (tartibda: matn + formulalar)
# ══════════════════════════════════════════════════════
def para_text(p_el) -> str:
    parts = []
    for child in p_el:
        tn = tname(child)
        if tn == 'oMathPara':
            for om in child.findall(f'{MQ}oMath'):
                lat = omml(om).strip()
                if lat: parts.append(f'$${lat}$$')
        elif tn == 'oMath':
            lat = omml(child).strip()
            if lat: parts.append(f'${lat}$')
        elif tn == 'r':
            for t in child.findall(f'{WQ}t'):
                if t.text: parts.append(umath(t.text))
        elif tn in ('ins','hyperlink','smartTag'):
            for r in child.findall(f'.//{WQ}r'):
                for t in r.findall(f'{WQ}t'):
                    if t.text: parts.append(umath(t.text))
    return ''.join(parts)


# ══════════════════════════════════════════════════════
#  RASM TAHLILI
# ══════════════════════════════════════════════════════
def is_geometric(img_bytes: bytes) -> bool:
    """Geometrik/matematik rasm ekanligini aniqlash"""
    try:
        arr  = np.array(Image.open(io.BytesIO(img_bytes)).convert('RGB'))
        gray = np.mean(arr, axis=2)
        # Oz rang turli → geometrik chizma (oddiy qora-oq chiziqlar)
        unique_ratio = len(np.unique(gray.astype(np.uint8))) / 256
        dark_ratio   = np.sum(gray < 100) / gray.size
        return unique_ratio < 0.5 or dark_ratio > 0.2
    except:
        return True  # Noma'lum → qabul qilish

def cohere_describe(img_bytes: bytes) -> str:
    """Cohere vision bilan rasm tavsifi"""
    if not COHERE_AVAILABLE or not COHERE_API_KEY:
        return ""
    try:
        co  = cohere.ClientV2(api_key=COHERE_API_KEY)
        b64 = base64.b64encode(img_bytes).decode()
        r   = co.chat(
            model="command-r-plus-vision",
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64",
                 "media_type":"image/jpeg","data":b64}},
                {"type":"text","text":
                 "Bu matematika masalasi rasmi. Geometrik shakl, o'lcham, "
                 "burchak, yorliqlarni batafsil O'zbek tilida ta'rifla."}
            ]}]
        )
        return r.message.content[0].text if r.message.content else ""
    except:
        return ""


# ══════════════════════════════════════════════════════
#  DOCX STRUKTURALI O'QISH (pozitsion rasm bog'lash)
# ══════════════════════════════════════════════════════
def detect_q_num(text: str):
    m = re.match(r'^\s*(\d+)\s*[\.\)]\s+\S', text)
    return int(m.group(1)) if m else None

def extract_docx(raw: bytes) -> tuple:
    """
    Qaytaradi: (elements_list, question_images_dict)
    elements: [{'type':'text'/'image', ...}]
    question_images: {savol_raqami: [bytes, ...]}
    """
    try:
        doc = Document(io.BytesIO(raw))

        # Barcha rasmlar: rel_id → bytes
        img_map = {}
        for rel_id, rel in doc.part.rels.items():
            if "image" in rel.target_ref:
                try:
                    img_map[rel_id] = rel.target_part.blob
                except:
                    pass

        elements        = []
        question_images = {}   # {q_num: [bytes,...]}
        current_q_num   = None

        NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'

        def para_imgs(p_el):
            imgs = []
            for blip in p_el.findall(f'.//{{{NS_A}}}blip'):
                rid = blip.get(f'{{{NS_R}}}embed') or blip.get(f'{{{NS_R}}}link')
                if rid and rid in img_map:
                    b = img_map[rid]
                    if is_geometric(b):
                        imgs.append(b)
            return imgs

        def process_para(p_el):
            nonlocal current_q_num
            text = para_text(p_el).strip()
            imgs = para_imgs(p_el)

            qn = detect_q_num(text)
            if qn: current_q_num = qn

            if text:
                elements.append({'type':'text','content':text})

            for b in imgs:
                elements.append({'type':'image','bytes':b})
                if current_q_num is not None:
                    question_images.setdefault(current_q_num, []).append(b)

        def process_table(tbl_el):
            nonlocal current_q_num
            for row in tbl_el.findall(f'{WQ}tr'):
                parts = []
                for cell in row.findall(f'{WQ}tc'):
                    ct = ' '.join(
                        para_text(p).strip()
                        for p in cell.findall(f'.//{WQ}p')
                        if para_text(p).strip()
                    )
                    if ct: parts.append(ct)
                if parts:
                    combined = ' | '.join(parts)
                    qn = detect_q_num(combined)
                    if qn: current_q_num = qn
                    elements.append({'type':'text','content':combined})

        for child in doc.element.body:
            tn = tname(child)
            if tn == 'p':
                process_para(child)
            elif tn == 'tbl':
                process_table(child)
            elif tn == 'sdt':
                for p in child.findall(f'.//{WQ}p'):
                    process_para(p)

        # Agar pozitsion bog'lash hech narsa bermasa — mammoth fallback
        full_text = '\n'.join(e['content'] for e in elements if e['type']=='text')
        if not full_text.strip():
            res       = mammoth.convert_to_html(io.BytesIO(raw))
            full_text = BeautifulSoup(res.value,'html.parser').get_text('\n',strip=True)
            elements  = [{'type':'text','content':full_text}]

        return elements, question_images

    except Exception as e:
        st.error(f"Word xatolik: {e}")
        return [], {}

def extract_pdf(raw: bytes) -> tuple:
    try:
        r    = PyPDF2.PdfReader(io.BytesIO(raw))
        text = '\n\n'.join(p.extract_text() or '' for p in r.pages)
        return [{'type':'text','content':text}], {}
    except Exception as e:
        st.error(f"PDF xatolik: {e}")
        return [], {}


# ══════════════════════════════════════════════════════
#  JSON TUZATISH  (LaTeX backslash himoyasi)
# ══════════════════════════════════════════════════════
LATEX_CMDS = sorted([
    'right','rho','rightarrow','Rightarrow','rightharpoonup',
    'beta','bar','begin','big','bigg','binom','boldsymbol',
    'frac','dfrac','tfrac','cfrac','forall',
    'nu','nabla','neq','notin',
    'theta','tau','times','text','tilde','top',
    'left','leq','geq','sqrt','sum','int','prod','oint',
    'alpha','gamma','delta','epsilon','zeta','eta',
    'iota','kappa','lambda','mu','xi','pi','sigma','phi',
    'chi','psi','omega','Gamma','Delta','Theta','Lambda',
    'Xi','Pi','Sigma','Phi','Psi','Omega',
    'cdot','div','pm','mp','infty','partial',
    'in','subset','supset','cup','cap','emptyset',
    'overline','underline','hat','vec','dot','ddot',
    'pmatrix','bmatrix','vmatrix','cases','matrix','aligned',
    'mathrm','mathbf','mathit','mathcal',
    'lim','max','min','sin','cos','tan','cot','sec','csc',
    'log','ln','exp','det','gcd','deg','angle','triangle',
    'parallel','perp','Leftrightarrow','leftrightarrow',
    'leftarrow','Leftarrow','uparrow','downarrow',
    'quad','qquad','ldots','cdots','vdots','ddots',
    'not','neg','land','lor','mathbb','mathfrak',
    'overset','underset','overbrace','underbrace','boxed',
], key=len, reverse=True)

def protect_latex(raw: str) -> str:
    """JSON parse oldidan LaTeX backslash larni himoya qilish"""
    for cmd in LATEX_CMDS:
        pattern = r'(?<!\\)\\(?!\\)' + re.escape(cmd) + r'(?=[^a-zA-Z]|$)'
        raw = re.sub(pattern, r'\\\\' + cmd, raw)
    return raw

def fix_escapes(raw: str) -> str:
    """Yaroqsiz JSON escape larni tuzatish"""
    VALID = set('"\\\/bfnrtu')
    res, in_s, esc = [], False, False
    for ch in raw:
        if esc:
            if in_s and ch not in VALID: res.append('\\')
            res.append(ch); esc = False; continue
        if ch == '\\': esc = True; res.append(ch); continue
        if ch == '"': in_s = not in_s
        res.append(ch)
    return ''.join(res)

def manual_extract(text: str) -> list:
    """Har bir {...} blokni alohida parse qilish — oxirgi fallback"""
    questions = []
    depth = 0; start = -1; blocks = []
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                blocks.append(text[start:i+1]); start = -1
    for block in blocks:
        for fn in [json.loads,
                   lambda t: json.loads(protect_latex(t)),
                   lambda t: json.loads(fix_escapes(t))]:
            try:
                obj = fn(block)
                if 'question' in obj and 'options' in obj:
                    obj.setdefault('correct', 'A')
                    obj.setdefault('number', len(questions)+1)
                    obj.setdefault('explanation', '')
                    obj.setdefault('has_image', False)
                    questions.append(obj)
                    break
            except:
                pass
    return questions

def safe_json(raw: str):
    raw = re.sub(r'```(?:json)?\s*','',raw).strip().rstrip('`').strip()
    s = raw.find('['); e = raw.rfind(']')
    if s == -1 or e <= s: return manual_extract(raw)
    chunk = raw[s:e+1]
    for fn in [
        json.loads,
        lambda t: json.loads(protect_latex(t)),
        lambda t: json.loads(fix_escapes(t)),
        lambda t: json.loads(re.sub(r'\\(?!["\\/bfnrtu])',r'\\\\',t)),
    ]:
        try: return fn(chunk)
        except: pass
    return manual_extract(raw)


# ══════════════════════════════════════════════════════
#  AI: Savollarni tahlil qilish (chunk bo'lib)
# ══════════════════════════════════════════════════════
def call_ai_chunk(chunk: str, client, img_desc: str,
                  chunk_num: int, total: int) -> list:
    prompt = f"""Matematika olimpiada testi (bo'lak {chunk_num}/{total}).
Bu bo'lakdagi BARCHA savollarni ajratib ol.

QOIDALAR:
1. Faqat JSON massivi qaytar — boshqa matn YOZMA.
2. LaTeX: \\\\frac, \\\\sqrt, \\\\cdot, \\\\left, \\\\right, \\\\leq (IKKI backslash!).
3. has_image: savol matnida rasm/shakl/chizma/berilgan so'zlari bo'lsa TRUE.
4. correct: faqat "A", "B", "C" yoki "D".
5. Agar bo'lakda savol yo'q — [] qaytar.

[{{
  "number":1,
  "question":"Savol ($\\\\frac{{a}}{{b}}$, $\\\\sqrt{{x}}$)",
  "options":{{"A":"...","B":"...","C":"...","D":"..."}},
  "correct":"B",
  "explanation":"Yechim",
  "has_image":false
}}]

MATN:
{chunk}
{("\\nRASM TAVSIFI:\\n" + img_desc) if img_desc else ""}"""

    try:
        resp = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role':'user','content':prompt}],
            temperature=0.05, max_tokens=8192,
        )
        raw    = resp.choices[0].message.content.strip()
        result = safe_json(raw)
        return result if result else []
    except Exception as e:
        st.warning(f"Bo'lak {chunk_num} xatosi: {e}")
        return []

def parse_questions(elements: list, img_desc: str = "") -> list:
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi."); return []

    lines     = [e['content'] for e in elements if e['type'] == 'text']
    full_text = '\n'.join(lines)
    if not full_text.strip(): return []

    client    = Groq(api_key=GROQ_API_KEY)
    CHUNK     = 7000

    if len(full_text) <= CHUNK:
        chunks = [full_text]
    else:
        chunks, cur, cur_len = [], [], 0
        for line in lines:
            if cur_len + len(line) > CHUNK and cur:
                chunks.append('\n'.join(cur))
                cur = cur[-3:]; cur_len = sum(len(l) for l in cur)
            cur.append(line); cur_len += len(line)
        if cur: chunks.append('\n'.join(cur))

    all_qs, seen = [], set()
    pb = st.progress(0, text="AI savollarni tahlil qilmoqda...")
    for i, chunk in enumerate(chunks):
        pb.progress((i+1)/len(chunks), text=f"Bo'lak {i+1}/{len(chunks)}...")
        for q in call_ai_chunk(chunk, client, img_desc, i+1, len(chunks)):
            num = q.get('number')
            if num not in seen:
                seen.add(num); all_qs.append(q)
    pb.empty()

    all_qs.sort(key=lambda q: q.get('number', 999))

    # Natija
    if all_qs:
        st.success(f"✅ {len(all_qs)} ta savol muvaffaqiyatli olindi!")
    else:
        st.error("❌ Savollar tahlil qilinmadi.")
    return all_qs


# ══════════════════════════════════════════════════════
#  RASM-SAVOL BOG'LASH  (pozitsion BIRINCHI, has_image ZAHIRA)
# ══════════════════════════════════════════════════════
def build_image_map(questions: list, pos_images: dict,
                    geo_imgs_all: list) -> dict:
    """
    Birlamchi: pozitsion bog'lash (docx dagi joylashuvga ko'ra).
    Zahira:   has_image=True bo'lgan savollar navbatma-navbat rasm oladi.
    """
    # Birlamchi: pozitsion
    if pos_images:
        return {
            # Savol indeksini savol raqami bo'yicha topish
            next((i for i,q in enumerate(questions) if q.get('number')==qn), -1): imgs
            for qn, imgs in pos_images.items()
            if any(i for i,q in enumerate(questions) if q.get('number')==qn)
        }

    # Zahira: has_image asosida
    if not geo_imgs_all: return {}
    IMG_KW = re.compile(r'rasm|shakl|chizma|rasmda|figura|berilgan|ko\'rsatilgan',re.I)
    img_qs = [i for i,q in enumerate(questions)
              if q.get('has_image') or IMG_KW.search(q.get('question',''))]
    if not img_qs:
        return {0: geo_imgs_all[:1]}

    result = {}
    for j, q_idx in enumerate(img_qs):
        if j < len(geo_imgs_all):
            result[q_idx] = [geo_imgs_all[j]]
    # Oxirgi savol — qolgan rasmlar
    if img_qs and len(geo_imgs_all) > len(img_qs):
        result[img_qs[-1]] = geo_imgs_all[len(img_qs)-1:]
    return result


# ══════════════════════════════════════════════════════
#  YORDAMCHILAR
# ══════════════════════════════════════════════════════
def grade(pct):
    if pct>=85: return "5 — A'lo 🥇"
    if pct>=70: return "4 — Yaxshi 🥈"
    if pct>=50: return "3 — Qoniqarli 🥉"
    return "2 — Qoniqarsiz 📚"

def fmt_time(sec):
    h,r = divmod(sec,3600); m,s = divmod(r,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ══════════════════════════════════════════════════════
#  SESSION STATE
# ══════════════════════════════════════════════════════
DEFAULTS = {
    'questions':[],'current_q':0,'answers':{},
    'started':False,'finished':False,
    'name':'','surname':'','duration':90,
    'start_time':None,'file_data':[],'image_map':{},
}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k] = v


# ══════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name    = st.text_input("Ism",      st.session_state.name)
    st.session_state.surname = st.text_input("Familiya", st.session_state.surname)
    st.markdown("---")
    st.markdown("### ⚙️ Sozlamalar")
    st.session_state.duration = st.number_input("⏱ Vaqt (daqiqa)",5,300,
                                                st.session_state.duration)
    st.markdown("---")
    st.markdown("### 📁 Test fayli")

    if not st.session_state.started:
        uploaded = st.file_uploader("Fayl yuklang (.docx yoki .pdf)",
                                    type=["docx","pdf"], accept_multiple_files=True)
        if uploaded:
            st.session_state.file_data = [
                {'name':f.name,'bytes':f.read()} for f in uploaded
            ]
    for fd in st.session_state.file_data:
        st.success(f"✅ {fd['name']}")

    if st.session_state.started and not st.session_state.finished:
        st.markdown("---")
        if st.button("⛔ Testni to'xtatish", use_container_width=True):
            st.session_state.finished = True; st.rerun()


# ══════════════════════════════════════════════════════
#  ASOSIY SAHIFA
# ══════════════════════════════════════════════════════
st.title("🏆 OlimpTest — Matematika")
st.markdown("#### Matematika Olimpiada Mashq Platformasi")


# ─── BOSHLASH ───────────────────────────────────────
if not st.session_state.started:
    st.markdown("""
<div style="background:rgba(255,255,255,0.05);padding:22px;border-radius:12px;
            border:1px solid rgba(255,215,0,0.3);">
<h3 style="color:#FFD700;">📋 Qo'llanma</h3>
<ul style="color:#E0E0E0;font-size:16px;line-height:2.2;">
  <li>Ism-familiyangizni kiriting va fayl yuklang</li>
  <li>✅ Kasir, ildiz, daraja, integral — barcha formulalar o'qiladi</li>
  <li>✅ Rasmlar hujjatdagi joylashuviga ko'ra to'g'ri savolga biriktiriladi</li>
  <li>✅ Ko'p savollik fayllar bo'laklarga bo'linib tahlil qilinadi</li>
  <li>✅ Geometrik rasmlar avtomatik aniqlanadi va tahlil qilinadi</li>
</ul>
</div>""", unsafe_allow_html=True)

    if not st.session_state.name.strip(): st.info("⬅️ Ismingizni kiriting")
    if not st.session_state.file_data:   st.info("⬅️ Fayl yuklang")

    debug_mode = st.checkbox("🔍 Debug: o'qilgan matnni ko'rish")
    ready = bool(st.session_state.file_data and st.session_state.name.strip())

    if ready and st.button("🚀 Testni boshlash", type="primary", use_container_width=True):

        with st.spinner("📖 Fayl o'qilmoqda..."):
            all_elements, all_pos_imgs = [], {}
            all_geo_bytes = []

            for fd in st.session_state.file_data:
                raw = fd['bytes']
                if fd['name'].lower().endswith('.docx'):
                    els, pos_imgs = extract_docx(raw)
                else:
                    els, pos_imgs = extract_pdf(raw)

                all_elements += els
                for qn, imgs in pos_imgs.items():
                    all_pos_imgs.setdefault(qn, []).extend(imgs)

            # Tüm geometrik rasmlar (zahira uchun)
            for el in all_elements:
                if el['type'] == 'image':
                    all_geo_bytes.append(el['bytes'])

        if debug_mode:
            st.subheader("O'qilgan elementlar (debug):")
            for i,el in enumerate(all_elements[:60]):
                if el['type']=='text':
                    st.text(f"[{i}] {el['content'][:150]}")
                else:
                    try:
                        st.image(Image.open(io.BytesIO(el['bytes'])),
                                 caption=f"[{i}] RASM", width=200)
                    except:
                        st.text(f"[{i}] RASM (ko'rsatilmadi)")
            st.subheader("Pozitsion rasm-savol bog'liqligi:")
            for qn,imgs in all_pos_imgs.items():
                st.text(f"Savol {qn}: {len(imgs)} ta rasm")
            st.info("Debug — boshlash uchun checkboxni olib tashlang."); st.stop()

        # Matn bo'sh tekshiruvi
        text_els = [e for e in all_elements if e['type']=='text']
        if not text_els: st.error("❌ Fayldan matn olinmadi."); st.stop()

        # Cohere bilan rasm tavsifi
        img_desc = ""
        if all_geo_bytes and COHERE_API_KEY:
            with st.spinner("🖼️ Rasmlar tahlil qilinmoqda (Cohere)..."):
                for idx, b in enumerate(all_geo_bytes[:5]):  # max 5 ta
                    desc = cohere_describe(b)
                    if desc: img_desc += f"\nRasm {idx+1}: {desc}"
            st.info(f"📊 {len(all_geo_bytes)} ta geometrik rasm aniqlandi")

        # AI tahlil
        questions = parse_questions(all_elements, img_desc)
        if not questions: st.stop()

        # Rasm-savol xaritasi
        image_map = build_image_map(questions, all_pos_imgs, all_geo_bytes)

        st.session_state.questions   = questions
        st.session_state.image_map   = image_map
        st.session_state.started     = True
        st.session_state.start_time  = time.time()
        st.session_state.current_q   = 0
        st.session_state.answers     = {}
        st.rerun()


# ─── TEST ───────────────────────────────────────────
elif not st.session_state.finished:
    # streamlit-autorefresh — timer uchun (time.sleep+rerun o'rniga)
    st_autorefresh(interval=1000, key="timer_refresh")

    elapsed   = time.time() - st.session_state.start_time
    remaining = max(0, int(st.session_state.duration * 60 - elapsed))
    if remaining == 0:
        st.session_state.finished = True; st.rerun()

    questions = st.session_state.questions
    image_map = st.session_state.image_map
    total_q   = len(questions)
    q_idx     = st.session_state.current_q
    q         = questions[q_idx]

    # Header
    h1, h2, h3 = st.columns([2,3,1])
    with h1: st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")
    with h2:
        ac = len(st.session_state.answers)
        st.progress(ac/total_q, text=f"Javob berilgan: {ac}/{total_q}")
    with h3:
        tcls = "timer-urgent" if remaining<60 else "timer-box"
        st.markdown(f'<div class="{tcls}">⏱ {fmt_time(remaining)}</div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### Savol {q_idx+1} / {total_q}")

    # Savol matni
    render_math(f"<b>{q.get('number',q_idx+1)}.</b> {q.get('question','')}", "20px")

    # Rasm (faqat shu savolniki)
    if q_idx in image_map:
        imgs = image_map[q_idx]
        cols = st.columns(min(2, len(imgs)))
        for ci, b in enumerate(imgs):
            with cols[ci % 2]:
                try:
                    st.image(Image.open(io.BytesIO(b)), use_container_width=True)
                except:
                    st.warning("Rasm ko'rsatilmadi")

    st.markdown("---")

    # Variantlar (radio + KaTeX expander)
    options   = q.get('options', {})
    opt_keys  = list(options.keys())
    opt_labels= [f"{k}) {options[k]}" for k in opt_keys]
    prev_ans  = st.session_state.answers.get(q_idx)
    prev_idx  = opt_keys.index(prev_ans) if prev_ans in opt_keys else None

    st.markdown("**Javobingizni tanlang:**")
    chosen = st.radio("", options=opt_labels, index=prev_idx,
                      label_visibility="collapsed", key=f"r_{q_idx}")
    if chosen:
        st.session_state.answers[q_idx] = chosen.split(")")[0].strip()

    with st.expander("🔢 Formulalar bilan variantlarni ko'rish"):
        for k in opt_keys:
            bg = "rgba(255,215,0,0.1)" if st.session_state.answers.get(q_idx)==k \
                 else "rgba(255,255,255,0.03)"
            render_math(f"<b>{k})</b> {options[k]}", "17px", bg)

    # Navigatsiya
    n1,n2,n3 = st.columns(3)
    with n1:
        if q_idx>0 and st.button("⬅️ Oldingi", use_container_width=True):
            st.session_state.current_q -= 1; st.rerun()
    with n2:
        if q_idx<total_q-1 and st.button("Keyingi ➡️", use_container_width=True):
            st.session_state.current_q += 1; st.rerun()
    with n3:
        if st.button("✅ Yakunlash", type="primary", use_container_width=True):
            st.session_state.finished = True; st.rerun()

    # Mini panel
    st.markdown("---")
    st.markdown("**Savollar paneli:**")
    for rs in range(0, total_q, 10):
        row  = list(range(rs, min(rs+10, total_q)))
        cols = st.columns(len(row))
        for col, i in zip(cols, row):
            with col:
                lbl = f"✓{i+1}" if i in st.session_state.answers else str(i+1)
                bt  = "primary" if i==q_idx else "secondary"
                if st.button(lbl, key=f"nav_{i}", type=bt, use_container_width=True):
                    st.session_state.current_q = i; st.rerun()


# ─── NATIJA ─────────────────────────────────────────
else:
    questions = st.session_state.questions
    total_q   = len(questions)
    correct   = sum(1 for i,q in enumerate(questions)
                    if st.session_state.answers.get(i)==q.get('correct'))
    pct = (correct/total_q*100) if total_q else 0.0

    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}**")

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("✅ To'g'ri",   f"{correct}/{total_q}")
    c2.metric("❌ Noto'g'ri", f"{total_q-correct}/{total_q}")
    c3.metric("📊 Foiz",      f"{pct:.1f}%")
    c4.metric("🎓 Baho",      grade(pct))

    color = "#2ECC71" if pct>=70 else "#E67E22" if pct>=50 else "#E74C3C"
    st.markdown(
        f'<div style="background:{color};padding:18px;border-radius:12px;'
        f'text-align:center;color:white;font-size:22px;font-weight:bold;'
        f'margin:16px 0;">Natija: {pct:.1f}% — {grade(pct)}</div>',
        unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")
    image_map = st.session_state.image_map
    for i,q in enumerate(questions):
        user_ans = st.session_state.answers.get(i)
        corr     = q.get('correct','?')
        ok       = user_ans == corr
        icon     = "✅" if ok else ("❌" if user_ans else "⬜")
        with st.expander(f"{icon} Savol {i+1}  |  Siz: {user_ans or '—'}  |  To'g'ri: {corr}"):
            render_math(f"<b>Savol:</b> {q['question']}")
            if i in image_map:
                for b in image_map[i]:
                    try: st.image(Image.open(io.BytesIO(b)), width=300)
                    except: pass
            for k,v in q.get('options',{}).items():
                if k==corr:
                    render_math(f"✅ <b>{k})</b> {v}", bg="rgba(46,204,113,0.15)")
                elif k==user_ans:
                    render_math(f"❌ <b>{k})</b> {v}", bg="rgba(231,76,60,0.15)")
                else:
                    render_math(f"&nbsp;&nbsp;{k}) {v}", bg="transparent")
            if q.get('explanation'):
                st.info(f"💡 **Yechim:** {q['explanation']}")

    if st.button("🔄 Yangi test", type="primary", use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

st.markdown("---")
st.markdown(
    "<p style='text-align:center;color:#888;font-size:12px;'>"
    "Yaratuvchi: Usmonov Sodiq</p>",
    unsafe_allow_html=True)
