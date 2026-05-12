"""
╔═══════════════════════════════════════════════════════════════╗
║   OlimpTest — Matematika Olimpiada Mashq Platformasi         ║
║   Taratib: LaTeX ↔ OMML ↔ formulalar, rasm tahlili, AI       ║
╚═══════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import os, re, io, json, base64, time, hashlib
from groq import Groq
from docx import Document
import PyPDF2
import mammoth
from bs4 import BeautifulSoup
from PIL import Image
import numpy as np

# ─────────────────────────────────────────────────────
# Optional: Cohere support
# ─────────────────────────────────────────────────────
try:
    import cohere
    COHERE_AVAILABLE = True
except ImportError:
    COHERE_AVAILABLE = False


# ═══════════════════════════════════════════════════════
#  SOZLAMALAR VA KONSTANTES
# ═══════════════════════════════════════════════════════

st.set_page_config(
    page_title="OlimpTest — Matematika",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API kalitlari
GROQ_API_KEY   = st.secrets.get("GROQ_API_KEY",   os.getenv("GROQ_API_KEY",   ""))
COHERE_API_KEY = st.secrets.get("COHERE_API_KEY", os.getenv("COHERE_API_KEY", ""))

# Groq parametrlari
GROQ_MAX_TOKENS = 4096
CHUNK_SIZE      = 3500
RETRY_WAIT      = 65
MAX_RETRIES     = 3

# CSS: Dark theme + golden accents
st.markdown("""
<style>
  .stApp {
    background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%);
  }
  
  h1, h2, h3, h4, h5, h6 {
    color: #FFD700 !important;
    font-weight: 700;
  }
  
  p, li, label, span {
    color: #E0E0E0 !important;
  }
  
  .stButton > button {
    background: linear-gradient(90deg, #FF8C00, #FFA500) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: bold !important;
    padding: 10px 20px !important;
    transition: all 0.3s !important;
  }
  
  .stButton > button:hover {
    transform: scale(1.05) !important;
    box-shadow: 0 0 15px rgba(255, 140, 0, 0.6) !important;
  }
  
  .timer-box {
    background: linear-gradient(90deg, #FF4500, #FF8C00);
    padding: 15px 25px;
    border-radius: 12px;
    color: white;
    font-size: 24px;
    font-weight: bold;
    text-align: center;
    border: 2px solid rgba(255, 215, 0, 0.3);
  }
  
  .timer-urgent {
    background: linear-gradient(90deg, #8B0000, #FF0000);
    padding: 15px 25px;
    border-radius: 12px;
    color: white;
    font-size: 24px;
    font-weight: bold;
    text-align: center;
    animation: blink 1s infinite;
  }
  
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }
  
  .question-panel {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 215, 0, 0.2);
    border-radius: 10px;
    padding: 15px;
    margin: 10px 0;
  }
  
  .option-selected {
    background: rgba(255, 215, 0, 0.15) !important;
    border: 2px solid rgba(255, 215, 0, 0.5) !important;
  }
  
  .option-correct {
    background: rgba(46, 204, 113, 0.15) !important;
    border: 2px solid rgba(46, 204, 113, 0.5) !important;
  }
  
  .option-wrong {
    background: rgba(231, 76, 60, 0.15) !important;
    border: 2px solid rgba(231, 76, 60, 0.5) !important;
  }

  .katex, .katex-display {
    color: #FFD700 !important;
  }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════
#  LaTeX UTILITIES
# ═══════════════════════════════════════════════════════

def fix_latex_errors(text: str) -> str:
    """
    AI yozilgan LaTeX xatolarini tuzatish.
    - \\angleA → \\angle A
    - \\overrightarrowAB → \\overrightarrow{AB}
    - \\vecA → \\vec{A}
    """
    if not text:
        return text
    
    text = re.sub(r'\\angle([A-Za-z])', r'\\angle \1', text)
    text = re.sub(r'\\overrightarrow([A-Za-z]{1,3})(?![{a-zA-Z])', r'\\overrightarrow{\1}', text)
    text = re.sub(r'\\overline([A-Za-z]{1,3})(?![{a-zA-Z])', r'\\overline{\1}', text)
    text = re.sub(r'\\vec([A-Za-z])(?![{])', r'\\vec{\1}', text)
    text = re.sub(r'\\hat([A-Za-z])(?![{])', r'\\hat{\1}', text)
    text = re.sub(r'\\tilde([A-Za-z])(?![{])', r'\\tilde{\1}', text)
    
    return text


def auto_latex(text: str) -> str:
    """
    Avtomatik LaTeX ni $ ... $ ichiga orash.
    """
    if not text:
        return text
    
    text = fix_latex_errors(text)
    
    if '$' in text:
        return text
    
    if re.search(r'\\[a-zA-Z]', text):
        return f'${text}$'
    
    return text


def render_math(text: str, font_size: str = "19px",
                bg: str = "rgba(255,255,255,0.05)", height: int = None):
    """
    KaTeX orqali matematik formulalarni render qilish.
    """
    lines = text.count('<br') + text.count('\n') + 1
    h = height or max(65, min(700, lines * 36 + len(text) // 4))
    
    html = f"""<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {{
      delimiters: [
        {{left: '$$', right: '$$', display: true}},
        {{left: '$', right: '$', display: false}}
      ],
      throwOnError: false
    }});"></script>
  <style>
    body {{
      background: {bg};
      color: #E0E0E0;
      font-size: {font_size};
      font-family: 'Segoe UI', Arial, sans-serif;
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid rgba(255,215,0,0.2);
      margin: 0;
      line-height: 1.8;
      word-wrap: break-word;
      overflow-wrap: break-word;
    }}
    .katex, .katex-display {{
      color: #FFD700;
    }}
    img {{
      max-width: 100%;
      border-radius: 8px;
      margin: 6px 0;
      display: block;
    }}
  </style>
</head>
<body>
  {text}
</body>
</html>"""
    
    components.html(html, height=h, scrolling=False)


# ═══════════════════════════════════════════════════════
#  OMML → LaTeX CONVERSION (Full)
# ═══════════════════════════════════════════════════════

MQ = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
WQ = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

NARY_OPS = {
    '\u222b': '\\int',
    '\u222c': '\\iint',
    '\u222d': '\\iiint',
    '\u2211': '\\sum',
    '\u220f': '\\prod',
    '\u222e': '\\oint'
}

PROP_TAGS = {
    'rPr', 'fPr', 'radPr', 'naryPr', 'dPr', 'sSupPr', 'sSubPr', 'sSubSupPr',
    'funcPr', 'sPr', 'limLowPr', 'limUppPr', 'eqArrPr', 'mPr', 'ctrlPr',
    'groupChrPr', 'borderBoxPr', 'barPr', 'accPr', 'phantPr', 'boxPr'
}

FN_MAP = {
    'sin': '\\sin', 'cos': '\\cos', 'tan': '\\tan', 'cot': '\\cot',
    'tg': '\\tan', 'ctg': '\\cot', 'sec': '\\sec', 'csc': '\\csc',
    'log': '\\log', 'ln': '\\ln', 'exp': '\\exp', 'lim': '\\lim',
    'max': '\\max', 'min': '\\min', 'det': '\\det', 'gcd': '\\gcd',
    'arcsin': '\\arcsin', 'arccos': '\\arccos', 'arctan': '\\arctan',
}

ACC_MAP = {
    '\u0302': '\\hat',
    '\u0303': '\\tilde',
    '\u0307': '\\dot',
    '\u0308': '\\ddot',
    '\u0305': '\\bar',
    '\u20d7': '\\vec'
}

UMATH = {
    '·': '\\cdot', '×': '\\times', '÷': '\\div', '±': '\\pm', '∓': '\\mp',
    '≤': '\\leq', '≥': '\\geq', '≠': '\\neq', '≈': '\\approx', '≡': '\\equiv',
    '∞': '\\infty', '∈': '\\in', '∉': '\\notin', '⊂': '\\subset', '⊃': '\\supset',
    '∪': '\\cup', '∩': '\\cap', '∅': '\\emptyset', '∴': '\\therefore',
    '→': '\\rightarrow', '←': '\\leftarrow', '↔': '\\leftrightarrow',
    '⇒': '\\Rightarrow', '⇔': '\\Leftrightarrow',
    'α': '\\alpha', 'β': '\\beta', 'γ': '\\gamma', 'δ': '\\delta',
    'ε': '\\varepsilon', 'ζ': '\\zeta', 'η': '\\eta', 'θ': '\\theta',
    'λ': '\\lambda', 'μ': '\\mu', 'π': '\\pi', 'ρ': '\\rho', 'σ': '\\sigma',
    'τ': '\\tau', 'φ': '\\varphi', 'ψ': '\\psi', 'ω': '\\omega',
    'Δ': '\\Delta', 'Σ': '\\Sigma', 'Π': '\\Pi', 'Ω': '\\Omega',
    'Γ': '\\Gamma', 'Λ': '\\Lambda',
}


def umath(t: str) -> str:
    """Unicode matematikamasini LaTeX ga o'girish"""
    for ch, lat in UMATH.items():
        t = t.replace(ch, lat)
    return t


def tname(el) -> str:
    """Element tagining nomini olish"""
    t = el.tag
    if t.startswith(MQ):
        return t[len(MQ):]
    if t.startswith(WQ):
        return t[len(WQ):]
    return t


def omml(el) -> str:
    """OMML → LaTeX o'girish (recursive)"""
    tn = tname(el)
    
    if tn in PROP_TAGS:
        return ''
    
    if tn in ('oMath', 'oMathPara', 'e', 'num', 'den', 'fName', 'lim', 'sub', 'sup', 'deg', 'mr'):
        return ''.join(omml(c) for c in el)
    
    if tn == 'r':
        return umath(''.join(t.text or '' for t in el.findall(f'{MQ}t')))
    
    if tn == 't':
        return umath(el.text or '')
    
    if tn == 'f':
        pr = el.find(f'{MQ}fPr')
        ftype = ''
        if pr is not None:
            ft = pr.find(f'{MQ}type')
            if ft is not None:
                ftype = ft.get(f'{MQ}val', '')
        
        n = omml(el.find(f'{MQ}num')) if el.find(f'{MQ}num') is not None else ''
        d = omml(el.find(f'{MQ}den')) if el.find(f'{MQ}den') is not None else ''
        
        if ftype == 'skw':
            return f'{n}/{d}'
        elif ftype == 'noBar':
            return f'\\binom{{{n}}}{{{d}}}'
        elif ftype == 'lin':
            return f'{n}/{d}'
        else:
            return f'\\frac{{{n}}}{{{d}}}'
    
    if tn == 'rad':
        pr = el.find(f'{MQ}radPr')
        hide = False
        if pr is not None:
            dh = pr.find(f'{MQ}degHide')
            if dh is not None:
                hide = dh.get(f'{MQ}val', '1') not in ('0', 'false')
        
        e = omml(el.find(f'{MQ}e')).strip() if el.find(f'{MQ}e') is not None else ''
        deg = omml(el.find(f'{MQ}deg')).strip() if el.find(f'{MQ}deg') is not None else ''
        
        return f'\\sqrt{{{e}}}' if (hide or not deg) else f'\\sqrt[{deg}]{{{e}}}'
    
    if tn == 'sSup':
        b = omml(el.find(f'{MQ}e')).strip() if el.find(f'{MQ}e') is not None else ''
        s = omml(el.find(f'{MQ}sup')).strip() if el.find(f'{MQ}sup') is not None else ''
        return f'{b}^{{{s}}}'
    
    if tn == 'sSub':
        b = omml(el.find(f'{MQ}e')).strip() if el.find(f'{MQ}e') is not None else ''
        s = omml(el.find(f'{MQ}sub')).strip() if el.find(f'{MQ}sub') is not None else ''
        return f'{b}_{{{s}}}'
    
    if tn == 'sSubSup':
        b = omml(el.find(f'{MQ}e')).strip() if el.find(f'{MQ}e') is not None else ''
        s = omml(el.find(f'{MQ}sub')).strip() if el.find(f'{MQ}sub') is not None else ''
        p = omml(el.find(f'{MQ}sup')).strip() if el.find(f'{MQ}sup') is not None else ''
        return f'{{{b}}}_{{{s}}}^{{{p}}}'
    
    if tn == 'nary':
        pr = el.find(f'{MQ}naryPr')
        op = '\\sum'
        if pr is not None:
            ch_el = pr.find(f'{MQ}chr')
            if ch_el is not None:
                op = NARY_OPS.get(ch_el.get(f'{MQ}val', ''), '\\sum')
        
        lo = omml(el.find(f'{MQ}sub')) if el.find(f'{MQ}sub') is not None else ''
        hi = omml(el.find(f'{MQ}sup')) if el.find(f'{MQ}sup') is not None else ''
        bd = omml(el.find(f'{MQ}e')) if el.find(f'{MQ}e') is not None else ''
        
        res = op
        if lo:
            res += f'_{{{lo}}}'
        if hi:
            res += f'^{{{hi}}}'
        return res + f'{{{bd}}}'
    
    if tn == 'func':
        fn = omml(el.find(f'{MQ}fName')).strip() if el.find(f'{MQ}fName') is not None else ''
        c = omml(el.find(f'{MQ}e')).strip() if el.find(f'{MQ}e') is not None else ''
        return f'{FN_MAP.get(fn, fn)}\\left({c}\\right)'
    
    if tn == 'd':
        pr = el.find(f'{MQ}dPr')
        left, right = '(', ')'
        if pr is not None:
            beg = pr.find(f'{MQ}begChr')
            end = pr.find(f'{MQ}endChr')
            if beg is not None:
                left = beg.get(f'{MQ}val', '(') or '.'
            if end is not None:
                right = end.get(f'{MQ}val', ')') or '.'
        
        e_els = el.findall(f'{MQ}e')
        inner = ','.join(omml(e) for e in e_els) if e_els else ''
        bmap = {'|': '|', '⌈': '\\lceil', '⌉': '\\rceil', '⌊': '\\lfloor', '⌋': '\\rfloor'}
        
        return f'\\left{bmap.get(left, left)}{inner}\\right{bmap.get(right, right)}'
    
    if tn == 'm':
        rows = el.findall(f'{MQ}mr')
        lr = [' & '.join(omml(c) for c in r.findall(f'{MQ}e')) for r in rows]
        return '\\begin{pmatrix}' + ' \\\\ '.join(lr) + '\\end{pmatrix}'
    
    if tn == 'acc':
        pr = el.find(f'{MQ}accPr')
        ch = ''
        if pr is not None:
            ce = pr.find(f'{MQ}chr')
            if ce is not None:
                ch = ce.get(f'{MQ}val', '')
        inner = omml(el.find(f'{MQ}e')) if el.find(f'{MQ}e') is not None else ''
        return f'{ACC_MAP.get(ch, "\\hat")}{{{inner}}}'
    
    if tn == 'bar':
        e = el.find(f'{MQ}e')
        return f'\\overline{{{omml(e) if e is not None else ""}}}'
    
    if tn == 'limLow':
        b = omml(el.find(f'{MQ}e')) if el.find(f'{MQ}e') is not None else ''
        l = omml(el.find(f'{MQ}lim')) if el.find(f'{MQ}lim') is not None else ''
        return f'\\underset{{{l}}}{{{b}}}'
    
    if tn == 'limUpp':
        b = omml(el.find(f'{MQ}e')) if el.find(f'{MQ}e') is not None else ''
        l = omml(el.find(f'{MQ}lim')) if el.find(f'{MQ}lim') is not None else ''
        return f'\\overset{{{l}}}{{{b}}}'
    
    if tn in ('box', 'borderBox'):
        e = el.find(f'{MQ}e')
        return f'\\boxed{{{omml(e) if e is not None else ""}}}'
    
    if tn == 'eqArr':
        return '\\begin{cases}' + ' \\\\ '.join(omml(r) for r in el.findall(f'{MQ}e')) + '\\end{cases}'
    
    if tn == 'groupChr':
        e = el.find(f'{MQ}e')
        pr = el.find(f'{MQ}groupChrPr')
        ch = ''
        if pr is not None:
            ce = pr.find(f'{MQ}chr')
            if ce is not None:
                ch = ce.get(f'{MQ}val', '')
        inner = omml(e) if e is not None else ''
        if ch == '\u23de':
            return f'\\overbrace{{{inner}}}'
        if ch == '\u23df':
            return f'\\underbrace{{{inner}}}'
        return inner
    
    return ''.join(omml(c) for c in el)


def para_text(p_el) -> str:
    """Word paragrafdagi matnni o'qish (formula + text)"""
    parts = []
    
    for child in p_el:
        tn = tname(child)
        
        if tn == 'oMathPara':
            for om in child.findall(f'{MQ}oMath'):
                lat = omml(om).strip()
                if lat:
                    parts.append(f'$${lat}$$')
        
        elif tn == 'oMath':
            lat = omml(child).strip()
            if lat:
                parts.append(f'${lat}$')
        
        elif tn == 'r':
            for t in child.findall(f'{WQ}t'):
                if t.text:
                    parts.append(umath(t.text))
        
        elif tn in ('ins', 'hyperlink', 'smartTag'):
            for r in child.findall(f'.//{WQ}r'):
                for t in r.findall(f'{WQ}t'):
                    if t.text:
                        parts.append(umath(t.text))
    
    return ''.join(parts)


# ═══════════════════════════════════════════════════════
#  RASM TAHLILI
# ═══════════════════════════════════════════════════════

def is_geometric(img_bytes: bytes) -> bool:
    """
    Rasm matematika/geometriya rasmi ekanligini aniqlash.
    Juda kichik (icon) yoki katta (background) rasmlarni filtrlash.
    """
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        w, h = img.size
        
        # Icon/bullet → skip
        if w < 30 or h < 30:
            return False
        
        # Background → skip
        if w > 3000 or h > 3000:
            return False
        
        return True
    except:
        return True


def cohere_describe(img_bytes: bytes) -> str:
    """
    Cohere vision model bilan rasm tasviri.
    O'zbek tilida geometrik shaklni, o'lchamni, burchaklarni ta'rifla.
    """
    if not COHERE_AVAILABLE or not COHERE_API_KEY:
        return ""
    
    try:
        co = cohere.ClientV2(api_key=COHERE_API_KEY)
        b64 = base64.b64encode(img_bytes).decode()
        
        r = co.chat(
            model="command-r-plus-vision",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "Bu matematika masalasi rasmi. Geometrik shakl, "
                            "o'lcham, burchak, yorliqlarni batafsil O'zbek tilida ta'rifla. "
                            "Faqat rasm tavsifini yoz, soru yozma."
                        )
                    }
                ]
            }]
        )
        
        return r.message.content[0].text if r.message.content else ""
    
    except Exception as e:
        return ""


# ═══════════════════════════════════════════════════════
#  DOCX EXTRACTION (Strukturali)
# ═══════════════════════════════════════════════════════

def detect_q_num(text: str):
    """Savolning raqamini aniqlash (1. / 1) / 1-...)"""
    m = re.match(r'^\s*(\d+)\s*[\.\):\-]\s+\S', text)
    return int(m.group(1)) if m else None


def extract_docx(raw: bytes) -> tuple:
    """
    Word faylini o'qish.
    
    Qaytaradi:
    - elements: [{'type':'text'/'image', ...}]
    - question_images: {savol_raqami: [bytes, ...]}
    """
    try:
        doc = Document(io.BytesIO(raw))
        
        # Barcha rasmlar: rel_id → bytes
        img_map = {}
        
        def _collect_imgs(part):
            for rid, rel in part.rels.items():
                if 'image' in rel.target_ref and rid not in img_map:
                    try:
                        img_map[rid] = rel.target_part.blob
                    except:
                        pass
        
        _collect_imgs(doc.part)
        for _part in list(doc.part.related_parts.values()):
            try:
                _collect_imgs(_part)
            except:
                pass
        
        elements = []
        question_images = {}
        current_q_num = None
        
        NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        NS_V = 'urn:schemas-microsoft-com:vml'
        NS_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        
        def para_imgs(p_el):
            """Paragrafda rasmlarni topish"""
            imgs = []
            
            # 1. Modern DrawingML (a:blip)
            for blip in p_el.findall(f'.//{{{NS_A}}}blip'):
                rid = blip.get(f'{{{NS_R}}}embed') or blip.get(f'{{{NS_R}}}link')
                if rid and rid in img_map:
                    b = img_map[rid]
                    if is_geometric(b):
                        imgs.append(b)
            
            # 2. Legacy VML (v:imagedata)
            for imgdata in p_el.findall(f'.//{{{NS_V}}}imagedata'):
                rid = imgdata.get(f'{{{NS_R}}}id') or imgdata.get(f'{{{NS_R}}}href')
                if rid and rid in img_map:
                    b = img_map[rid]
                    if is_geometric(b):
                        imgs.append(b)
            
            # 3. w:pict ichidagi rasmlar
            for pict in p_el.findall(f'.//{{{NS_W}}}pict'):
                for imgdata in pict.findall(f'.//{{{NS_V}}}imagedata'):
                    rid = imgdata.get(f'{{{NS_R}}}id')
                    if rid and rid in img_map:
                        b = img_map[rid]
                        if is_geometric(b):
                            imgs.append(b)
            
            return imgs
        
        def process_para(p_el):
            nonlocal current_q_num
            
            text = para_text(p_el).strip()
            imgs = para_imgs(p_el)
            
            # Savolning raqamini aniqlash
            qn = detect_q_num(text)
            if qn:
                current_q_num = qn
            
            if text:
                elements.append({'type': 'text', 'content': text})
            
            for b in imgs:
                elements.append({'type': 'image', 'bytes': b})
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
                    if ct:
                        parts.append(ct)
                
                if parts:
                    combined = ' | '.join(parts)
                    qn = detect_q_num(combined)
                    if qn:
                        current_q_num = qn
                    elements.append({'type': 'text', 'content': combined})
        
        # Barcha elementlarni o'qish
        for child in doc.element.body:
            tn = tname(child)
            if tn == 'p':
                process_para(child)
            elif tn == 'tbl':
                process_table(child)
            elif tn == 'sdt':
                for p in child.findall(f'.//{WQ}p'):
                    process_para(p)
        
        # Fallback: agar matn bo'lmasa mammoth ishlatish
        full_text = '\n'.join(e['content'] for e in elements if e['type'] == 'text')
        if not full_text.strip():
            res = mammoth.convert_to_html(io.BytesIO(raw))
            full_text = BeautifulSoup(res.value, 'html.parser').get_text('\n', strip=True)
            elements = [{'type': 'text', 'content': full_text}]
        
        return elements, question_images
    
    except Exception as e:
        st.error(f"❌ Word xatolik: {str(e)[:100]}")
        return [], {}


def extract_pdf(raw: bytes) -> tuple:
    """
    PDF faylini o'qish (matn + rasmlar).
    """
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(raw))
        elements = []
        
        for page_num, page in enumerate(reader.pages):
            # Matnni o'qish
            text = page.extract_text() or ''
            if text.strip():
                elements.append({'type': 'text', 'content': text})
            
            # Rasmlarni o'qish
            if "/XObject" in page["/Resources"]:
                xobject = page["/Resources"]["/XObject"].get_object()
                for obj_name in xobject:
                    obj = xobject[obj_name].get_object()
                    if obj["/Subtype"] == "/Image":
                        try:
                            if "/Filter" in obj:
                                if obj["/Filter"] == "/DCTDecode":
                                    img_bytes = obj.get_data()
                                    if is_geometric(img_bytes):
                                        elements.append({'type': 'image', 'bytes': img_bytes})
                        except:
                            pass
        
        return elements, {}
    
    except Exception as e:
        st.error(f"❌ PDF xatolik: {str(e)[:100]}")
        return [], {}


# ═══════════════════════════════════════════════════════
#  JSON UTILITIES
# ═══════════════════════════════════════════════════════

LATEX_CMDS = sorted([
    'right', 'rho', 'rightarrow', 'Rightarrow', 'rightharpoonup',
    'beta', 'bar', 'begin', 'big', 'bigg', 'binom', 'boldsymbol',
    'frac', 'dfrac', 'tfrac', 'cfrac', 'forall',
    'nu', 'nabla', 'neq', 'notin',
    'theta', 'tau', 'times', 'text', 'tilde', 'top',
    'left', 'leq', 'geq', 'sqrt', 'sum', 'int', 'prod', 'oint',
    'alpha', 'gamma', 'delta', 'epsilon', 'zeta', 'eta',
    'iota', 'kappa', 'lambda', 'mu', 'xi', 'pi', 'sigma', 'phi',
    'chi', 'psi', 'omega', 'Gamma', 'Delta', 'Theta', 'Lambda',
    'Xi', 'Pi', 'Sigma', 'Phi', 'Psi', 'Omega',
    'cdot', 'div', 'pm', 'mp', 'infty', 'partial',
    'in', 'subset', 'supset', 'cup', 'cap', 'emptyset',
    'overline', 'underline', 'hat', 'vec', 'dot', 'ddot',
    'pmatrix', 'bmatrix', 'vmatrix', 'cases', 'matrix', 'aligned',
    'mathrm', 'mathbf', 'mathit', 'mathcal',
    'lim', 'max', 'min', 'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
    'log', 'ln', 'exp', 'det', 'gcd', 'deg', 'angle', 'triangle',
    'parallel', 'perp', 'Leftrightarrow', 'leftrightarrow',
    'leftarrow', 'Leftarrow', 'uparrow', 'downarrow',
    'quad', 'qquad', 'ldots', 'cdots', 'vdots', 'ddots',
    'not', 'neg', 'land', 'lor', 'mathbb', 'mathfrak',
    'overset', 'underset', 'overbrace', 'underbrace', 'boxed',
], key=len, reverse=True)


def protect_latex(raw: str) -> str:
    """JSON parse qilinishdan oldin LaTeX backslash'larni himoya qilish"""
    for cmd in LATEX_CMDS:
        # \\command → \\\\command (JSON'da `\` uchun `\\` kerak)
        pattern = r'(?<!\\)\\(?!\\)' + re.escape(cmd) + r'(?=[^a-zA-Z]|$)'
        raw = re.sub(pattern, r'\\\\' + cmd, raw)
    return raw


def fix_escapes(raw: str) -> str:
    """Yaroqsiz JSON escape larni tuzatish"""
    VALID = set('"\\\/bfnrtu')
    res, in_s, esc = [], False, False
    
    for ch in raw:
        if esc:
            if in_s and ch not in VALID:
                res.append('\\')
            res.append(ch)
            esc = False
            continue
        
        if ch == '\\':
            esc = True
            res.append(ch)
            continue
        
        if ch == '"':
            in_s = not in_s
        
        res.append(ch)
    
    return ''.join(res)


def manual_extract(text: str) -> list:
    """
    Har bir {...} blokni alohida parse qilish.
    Oxirgi fallback usuli.
    """
    questions = []
    depth = 0
    start = -1
    blocks = []
    
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                blocks.append(text[start:i+1])
                start = -1
    
    for block in blocks:
        for fn in [
            json.loads,
            lambda t: json.loads(protect_latex(t)),
            lambda t: json.loads(fix_escapes(t)),
        ]:
            try:
                obj = fn(block)
                if 'question' in obj and 'options' in obj:
                    obj.setdefault('correct', 'A')
                    obj.setdefault('number', len(questions) + 1)
                    obj.setdefault('explanation', '')
                    obj.setdefault('has_image', False)
                    questions.append(obj)
                    break
            except:
                pass
    
    return questions


def safe_json(raw: str):
    """Xavfsiz JSON o'qish (LaTeX + escape xatolarini tuzatish)"""
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip().rstrip('`').strip()
    
    s = raw.find('[')
    e = raw.rfind(']')
    
    if s == -1 or e <= s:
        return manual_extract(raw)
    
    chunk = raw[s:e+1]
    
    for fn in [
        json.loads,
        lambda t: json.loads(protect_latex(t)),
        lambda t: json.loads(fix_escapes(t)),
        lambda t: json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', t)),
    ]:
        try:
            return fn(chunk)
        except:
            pass
    
    return manual_extract(raw)


# ═══════════════════════════════════════════════════════
#  AI: SAVOLLARNI TAHLIL QILISH
# ��══════════════════════════════════════════════════════

def call_ai_chunk(chunk: str, client, img_desc: str,
                  chunk_num: int, total: int) -> list:
    """
    Groq API orqali matn qismini tahlil qilish.
    Rate-limit bilan shug'ullanadi.
    """
    
    prompt = f"""Matematika olimpiada testi (bolak {chunk_num}/{total}).
Bu bolakdagi BARCHA savollarni tahlil qilb, JSON massivida qaytari.

QOIDALAR:
1. **FAQAT JSON massivi** — boshqa matn YOZMA!
2. **LaTeX**: \\\\ + command (ikki backslash). Masalan: \\\\frac, \\\\sqrt, \\\\sin
3. **has_image**: rasm/shakl/chizma/geometriya bo'lsa TRUE
4. **correct**: faqat "A", "B", "C" yoki "D" (bosh harf!)
5. **Agar bolakda savol yoq bolsa**: [] qaytari

NAMUNA:
[{{"number":1,"question":"$a^2+b^2=?$","options":{{"A":"$c^2$","B":"$2ab$","C":"$a+b$","D":"$ab$"}},"correct":"A","explanation":"Pifagor teoremasi","has_image":false}}]

MATN:
{chunk}
{("RASM TAVSIFI: " + img_desc[:300]) if img_desc else ""}"""
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.05,
                max_tokens=GROQ_MAX_TOKENS,
            )
            
            raw = resp.choices[0].message.content.strip()
            result = safe_json(raw)
            return result if isinstance(result, list) else []
        
        except Exception as e:
            err = str(e)
            
            # Rate limit
            if any(x in err for x in ['rate_limit', '429', 'TPM', 'tokens per minute']):
                m = re.search(r'try again in ([0-9.]+)s', err)
                wait = int(float(m.group(1))) + 5 if m else RETRY_WAIT * attempt
                wait = min(wait, 300)  # Max 5 minut
                
                ph = st.empty()
                for sec in range(wait, 0, -1):
                    ph.warning(
                        f"⏳ Groq rate limit — {sec}s kutilmoqda "
                        f"(bolak {chunk_num}/{total}, urinish {attempt}/{MAX_RETRIES})..."
                    )
                    time.sleep(1)
                ph.empty()
            else:
                st.warning(f"⚠️ Bolak {chunk_num} xatosi: {err[:150]}")
                return []
    
    st.warning(f"⚠️ Bolak {chunk_num}: {MAX_RETRIES}x urinildi, otkazib yuborildi.")
    return []


def parse_questions(elements: list, img_desc: str = "") -> list:
    """
    Fayldan o'qilgan elementlarni AI yordamida savollarga ajratish.
    """
    if not GROQ_API_KEY:
        st.error("❌ GROQ_API_KEY topilmadi. .streamlit/secrets.toml ni tekshiring.")
        return []
    
    # Matnni o'qish
    lines = [e['content'] for e in elements if e['type'] == 'text']
    full_text = '\n'.join(lines)
    
    if not full_text.strip():
        st.error("❌ Fayldan matn olinmadi.")
        return []
    
    # Bo'laklash (TPM limit uchun)
    client = Groq(api_key=GROQ_API_KEY)
    
    if len(full_text) <= CHUNK_SIZE:
        chunks = [full_text]
    else:
        chunks, cur, cur_len = [], [], 0
        
        for line in lines:
            if cur_len + len(line) > CHUNK_SIZE and cur:
                chunks.append('\n'.join(cur))
                cur = cur[-2:]  # 2 qator overlap
                cur_len = sum(len(l) for l in cur)
            
            cur.append(line)
            cur_len += len(line)
        
        if cur:
            chunks.append('\n'.join(cur))
    
    # AI orqali tahlil
    all_qs = []
    seen = set()
    
    pb = st.progress(0, text="🤖 AI savollarni tahlil qilmoqda...")
    
    for i, chunk in enumerate(chunks):
        pb.progress(
            (i + 1) / len(chunks),
            text=f"📖 Bolak {i+1}/{len(chunks)} tahlil qilinyapti..."
        )
        
        for q in call_ai_chunk(chunk, client, img_desc, i + 1, len(chunks)):
            num = q.get('number')
            if num not in seen:
                seen.add(num)
                all_qs.append(q)
        
        # Chunklar orasida pauza
        if i < len(chunks) - 1:
            time.sleep(2)
    
    pb.empty()
    all_qs.sort(key=lambda q: q.get('number', 999))
    
    if all_qs:
        st.success(f"✅ {len(all_qs)} ta savol muvaffaqiyatli olindi!")
    else:
        st.error("❌ Savollar tahlil qilinmadi. Faylni tekshiring.")
    
    return all_qs


def build_image_map(questions: list, pos_images: dict,
                    geo_imgs_all: list) -> dict:
    """
    Savol indeksi (0-based) → [bytes, ...] xaritasi.
    1. Birlamchi: pozitsion bog'lash (docx joylashuvi)
    2. Zahira: has_image + kalit so'z
    """
    result = {}
    
    # 1. Pozitsion bog'lash
    if pos_images:
        num_to_idx = {q.get('number'): i for i, q in enumerate(questions)}
        for qn, imgs in pos_images.items():
            idx = num_to_idx.get(qn)
            if idx is not None and imgs:
                result[idx] = imgs
        
        if result:
            return result
    
    # 2. Zahira bog'lash
    if not geo_imgs_all:
        return {}
    
    IMG_KW = re.compile(
        r'rasm|shakl|chizma|rasmda|rasmdan|figura'
        r'|ko\'rsatilgan|berilgan|grafikda',
        re.IGNORECASE
    )
    
    img_qs = [
        i for i, q in enumerate(questions)
        if q.get('has_image') or IMG_KW.search(q.get('question', ''))
    ]
    
    if not img_qs:
        return {0: geo_imgs_all}
    
    for j, q_idx in enumerate(img_qs):
        if j < len(geo_imgs_all):
            result[q_idx] = [geo_imgs_all[j]]
    
    if len(geo_imgs_all) > len(img_qs):
        result[img_qs[-1]] = geo_imgs_all[len(img_qs) - 1:]
    
    return result


# ═══════════════════════════════════════════════════════
#  YORDAMCHILAR
# ═══════════════════════════════════════════════════════

def grade(pct):
    """Foizga qarab baho berish"""
    if pct >= 85:
        return "5 — A'lo 🥇"
    elif pct >= 70:
        return "4 — Yaxshi 🥈"
    elif pct >= 50:
        return "3 — Qoniqarli 🥉"
    else:
        return "2 — Qoniqarsiz 📚"


def fmt_time(sec):
    """Vaqtni HH:MM:SS formatida ko'rsatish"""
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ═══════════════════════════════════════════════════════
#  SESSION STATE
# ═══════════════════════════════════════════════════════

DEFAULTS = {
    'questions': [],
    'current_q': 0,
    'answers': {},
    'started': False,
    'finished': False,
    'name': '',
    'surname': '',
    'duration': 90,
    'start_time': None,
    'file_data': [],
    'image_map': {},
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name = st.text_input(
        "Ism",
        st.session_state.name,
        placeholder="Ismingiz"
    )
    st.session_state.surname = st.text_input(
        "Familiya",
        st.session_state.surname,
        placeholder="Familiyangiz"
    )
    
    st.markdown("---")
    st.markdown("### ⚙️ Sozlamalar")
    st.session_state.duration = st.number_input(
        "⏱ Vaqt (daqiqa)",
        min_value=5,
        max_value=300,
        value=st.session_state.duration,
        step=5
    )
    
    st.markdown("---")
    st.markdown("### 📁 Test fayli")
    
    if not st.session_state.started:
        uploaded = st.file_uploader(
            "Fayl yuklang (.docx yoki .pdf)",
            type=["docx", "pdf"],
            accept_multiple_files=True,
            disabled=st.session_state.started
        )
        
        if uploaded:
            st.session_state.file_data = [
                {'name': f.name, 'bytes': f.read()}
                for f in uploaded
            ]
    
    if st.session_state.file_data:
        st.markdown("**✅ Yuklangan fayllar:**")
        for fd in st.session_state.file_data:
            st.success(f"✓ {fd['name']}")
    
    if st.session_state.started and not st.session_state.finished:
        st.markdown("---")
        if st.button("⛔ Testni to'xtatish", use_container_width=True):
            st.session_state.finished = True
            st.rerun()


# ═══════════════════════════════════════════════════════
#  MAIN PAGE
# ═══════════════════════════════════════════════════════

st.title("🏆 OlimpTest — Matematika")
st.markdown("#### Matematika Olimpiada Mashq Platformasi v2.0")


# ─────────────────────────────────────────────────────
# 1. BOSHLASH EKRANI
# ─────────────────────────────────────────────────────

if not st.session_state.started:
    
    st.markdown("""
    <div style="background:rgba(255,255,255,0.05);padding:22px;border-radius:12px;
                border:1px solid rgba(255,215,0,0.3);">
    <h3 style="color:#FFD700;">📋 Qo'llanma</h3>
    <ul style="color:#E0E0E0;font-size:16px;line-height:2.2;">
      <li>✅ Ism-familiyangizni kiriting va fayl yuklang</li>
      <li>✅ Kasir, ildiz, daraja, integral — barcha formulalar o'qiladi</li>
      <li>✅ Rasmlar hujjatdagi joylashuviga ko'ra to'g'ri savolga biriktiriladi</li>
      <li>✅ Ko'p savollik fayllar bo'laklarga bo'linib tahlil qilinadi</li>
      <li>✅ Geometrik rasmlar avtomatik aniqlanadi va tahlil qilinadi</li>
      <li>✅ Vaqt tugagach, test avtomatik yakunlanadi</li>
    </ul>
    </div>""", unsafe_allow_html=True)
    
    st.markdown("---")
    
    if not st.session_state.name.strip():
        st.info("⬅️ **Ismingizni kiriting (sidebar)**")
    
    if not st.session_state.file_data:
        st.info("⬅️ **Fayl yuklang (sidebar)**")
    
    debug_mode = st.checkbox("🔍 Debug: o'qilgan matnni ko'rish")
    ready = bool(st.session_state.file_data and st.session_state.name.strip())
    
    if ready and st.button("🚀 Testni boshlash", type="primary", use_container_width=True):
        
        with st.spinner("📖 Fayl o'qilmoqda..."):
            all_elements = []
            all_pos_imgs = {}
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
            
            # Barcha geometrik rasmlar
            for el in all_elements:
                if el['type'] == 'image':
                    all_geo_bytes.append(el['bytes'])
        
        if debug_mode:
            st.subheader("🔍 O'qilgan elementlar (debug)")
            
            st.write(f"**Jami elementlar:** {len(all_elements)}")
            st.write(f"**Jami rasmlar:** {len(all_geo_bytes)}")
            st.write(f"**Pozitsion bog'lashlar:** {len(all_pos_imgs)}")
            
            for i, el in enumerate(all_elements[:50]):
                if el['type'] == 'text':
                    st.text(f"[{i}] TEXT: {el['content'][:120]}")
                else:
                    try:
                        st.image(
                            Image.open(io.BytesIO(el['bytes'])),
                            caption=f"[{i}] RASM",
                            width=200
                        )
                    except:
                        st.text(f"[{i}] RASM (ko'rsatilmadi)")
            
            st.info("Debug tugadi. Boshlash uchun checkboxni olib tashlang.")
            st.stop()
        
        # Matn tekshiruvi
        text_els = [e for e in all_elements if e['type'] == 'text']
        if not text_els:
            st.error("❌ Fayldan matn olinmadi.")
            st.stop()
        
        # Cohere bilan rasm tavsifi
        img_desc = ""
        if all_geo_bytes and COHERE_AVAILABLE and COHERE_API_KEY:
            with st.spinner("🖼️ Rasmlar Cohere bilan tahlil qilinmoqda..."):
                for idx, b in enumerate(all_geo_bytes[:3]):  # max 3 ta
                    desc = cohere_describe(b)
                    if desc:
                        img_desc += f"\nRasm {idx+1}: {desc}"
            
            if img_desc:
                st.info(f"📊 {len(all_geo_bytes)} ta geometrik rasm aniqlandi")
        
        # AI tahlil
        questions = parse_questions(all_elements, img_desc)
        if not questions:
            st.stop()
        
        # Rasm-savol xaritasi
        image_map = build_image_map(questions, all_pos_imgs, all_geo_bytes)
        
        st.session_state.questions = questions
        st.session_state.image_map = image_map
        st.session_state.started = True
        st.session_state.start_time = time.time()
        st.session_state.current_q = 0
        st.session_state.answers = {}
        
        st.rerun()


# ─────────────────────────────────────────────────────
# 2. TEST EKRANI
# ─────────────────────────────────────────────────────

elif not st.session_state.finished:
    
    # Auto-refresh timer
    st_autorefresh(interval=500, key="timer_refresh")
    
    elapsed = time.time() - st.session_state.start_time
    remaining = max(0, int(st.session_state.duration * 60 - elapsed))
    
    if remaining == 0:
        st.session_state.finished = True
        st.rerun()
    
    questions = st.session_state.questions
    image_map = st.session_state.image_map
    total_q = len(questions)
    q_idx = st.session_state.current_q
    q = questions[q_idx]
    
    # Header
    h1, h2, h3 = st.columns([2, 3, 1])
    
    with h1:
        st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")
    
    with h2:
        ac = len(st.session_state.answers)
        st.progress(ac / total_q, text=f"Javob berilgan: {ac}/{total_q}")
    
    with h3:
        tcls = "timer-urgent" if remaining < 60 else "timer-box"
        st.markdown(
            f'<div class="{tcls}">⏱ {fmt_time(remaining)}</div>',
            unsafe_allow_html=True
        )
    
    st.markdown("---")
    st.markdown(f"### 📝 Savol {q_idx + 1} / {total_q}")
    
    # Savol matni
    _q_text = fix_latex_errors(q.get('question', ''))
    render_math(
        f"<b>{q.get('number', q_idx + 1)}.</b> {_q_text}",
        font_size="20px"
    )
    
    # Rasmlar (faqat shu savolniki)
    if q_idx in image_map:
        imgs = image_map[q_idx]
        st.markdown("**Rasmlar:**")
        cols = st.columns(min(2, len(imgs)))
        for ci, b in enumerate(imgs):
            with cols[ci % 2]:
                try:
                    st.image(Image.open(io.BytesIO(b)), use_container_width=True)
                except:
                    st.warning("⚠️ Rasm ko'rsatilmadi")
    
    st.markdown("---")
    
    # Variantlar
    options = q.get('options', {})
    opt_keys = list(options.keys())
    prev_ans = st.session_state.answers.get(q_idx)
    
    st.markdown("**Javobingizni tanlang:**")
    
    for k in opt_keys:
        checked = (prev_ans == k)
        bg = "rgba(255,215,0,0.12)" if checked else "rgba(255,255,255,0.03)"
        opt_text = auto_latex(options[k])
        h = max(58, min(120, 58 + len(opt_text) // 8))
        
        c1, c2 = st.columns([0.08, 0.92])
        
        with c1:
            icon = "🟡" if checked else "⚪"
            if st.button(icon, key=f"sel_{q_idx}_{k}", use_container_width=True):
                st.session_state.answers[q_idx] = k
                st.rerun()
        
        with c2:
            render_math(
                f"<b>{k})</b>&nbsp;&nbsp;{opt_text}",
                font_size="17px",
                bg=bg,
                height=h
            )
    
    st.markdown("---")
    
    # Navigatsiya
    n1, n2, n3 = st.columns(3)
    
    with n1:
        if q_idx > 0 and st.button("⬅️ Oldingi", use_container_width=True):
            st.session_state.current_q -= 1
            st.rerun()
    
    with n2:
        if q_idx < total_q - 1 and st.button("Keyingi ➡️", use_container_width=True):
            st.session_state.current_q += 1
            st.rerun()
    
    with n3:
        if st.button("✅ Yakunlash", type="primary", use_container_width=True):
            st.session_state.finished = True
            st.rerun()
    
    # Mini panel — Savollar
    st.markdown("---")
    st.markdown("**📌 Savollar paneli:**")
    
    for rs in range(0, total_q, 10):
        row = list(range(rs, min(rs + 10, total_q)))
        cols = st.columns(len(row))
        
        for col, i in zip(cols, row):
            with col:
                lbl = f"✓{i+1}" if i in st.session_state.answers else str(i+1)
                bt = "primary" if i == q_idx else "secondary"
                
                if st.button(
                    lbl,
                    key=f"nav_{i}",
                    type=bt,
                    use_container_width=True
                ):
                    st.session_state.current_q = i
                    st.rerun()


# ─────────────────────────────────────────────────────
# 3. NATIJA EKRANI
# ─────────────────────────────────────────────────────

else:
    questions = st.session_state.questions
    total_q = len(questions)
    
    correct = sum(
        1 for i, q in enumerate(questions)
        if st.session_state.answers.get(i) == q.get('correct')
    )
    
    pct = (correct / total_q * 100) if total_q else 0.0
    
    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}**")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ To'g'ri", f"{correct}/{total_q}")
    c2.metric("❌ Noto'g'ri", f"{total_q - correct}/{total_q}")
    c3.metric("📊 Foiz", f"{pct:.1f}%")
    c4.metric("🎓 Baho", grade(pct))
    
    color = "#2ECC71" if pct >= 70 else "#E67E22" if pct >= 50 else "#E74C3C"
    st.markdown(
        f'<div style="background:{color};padding:18px;border-radius:12px;'
        f'text-align:center;color:white;font-size:22px;font-weight:bold;'
        f'margin:16px 0;">Natija: {pct:.1f}% — {grade(pct)}</div>',
        unsafe_allow_html=True
    )
    
    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")
    
    image_map = st.session_state.image_map
    
    for i, q in enumerate(questions):
        user_ans = st.session_state.answers.get(i)
        corr = q.get('correct', '?')
        ok = user_ans == corr
        icon = "✅" if ok else ("❌" if user_ans else "⬜")
        
        with st.expander(
            f"{icon} Savol {i+1}  |  Siz: {user_ans or '—'}  |  To'g'ri: {corr}",
            expanded=False
        ):
            render_math(
                f"<b>Savol:</b> {fix_latex_errors(q.get('question', ''))}",
                font_size="18px"
            )
            
            if i in image_map:
                for b in image_map[i]:
                    try:
                        st.image(Image.open(io.BytesIO(b)), width=300)
                    except:
                        pass
            
            st.markdown("**Variantlar:**")
            
            for k, v in q.get('options', {}).items():
                if k == corr:
                    render_math(
                        f"✅ <b>{k})</b>&nbsp;&nbsp;{auto_latex(v)}",
                        bg="rgba(46, 204, 113, 0.15)",
                        height=max(58, min(120, 58 + len(v) // 8))
                    )
                elif k == user_ans:
                    render_math(
                        f"❌ <b>{k})</b>&nbsp;&nbsp;{auto_latex(v)}",
                        bg="rgba(231, 76, 60, 0.15)",
                        height=max(58, min(120, 58 + len(v) // 8))
                    )
                else:
                    render_math(
                        f"<b>{k})</b>&nbsp;&nbsp;{auto_latex(v)}",
                        bg="rgba(255, 255, 255, 0.02)",
                        height=max(58, min(120, 58 + len(v) // 8))
                    )
            
            if q.get('explanation'):
                st.info(f"💡 **Yechim:** {q['explanation']}")
    
    if st.button("🔄 Yangi test", type="primary", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


st.markdown("---")
st.markdown(
    "<p style='text-align:center;color:#888;font-size:12px;'>"
    "OlimpTest v2.0 | Taratib: Usmonov Sodiq | 2026</p>",
    unsafe_allow_html=True
)
