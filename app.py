import streamlit as st
import streamlit.components.v1 as components
import os, re, io, json, base64, time
from groq import Groq
import cohere
import mammoth
from docx import Document
import PyPDF2
from bs4 import BeautifulSoup
from PIL import Image
import numpy as np

# ==================== SOZLAMALAR ====================
st.set_page_config(
    page_title="OlimpTest",
    page_icon="🏆",
    layout="wide",
)

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", os.getenv("GROQ_API_KEY", ""))
COHERE_API_KEY = st.secrets.get("COHERE_API_KEY", os.getenv("COHERE_API_KEY", ""))

# ==================== STIL ====================
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%); }
    h1,h2,h3 { color: #FFD700 !important; }
    p, li, label { color: #E0E0E0 !important; }
    .stButton>button {
        background: linear-gradient(90deg,#FF8C00,#FFA500);
        color:white; border:none; border-radius:10px;
        font-weight:bold; padding:10px 20px;
    }
    .timer-box {
        background: linear-gradient(90deg,#FF4500,#FF8C00);
        padding:15px 25px; border-radius:12px;
        color:white; font-size:24px; font-weight:bold; text-align:center;
    }
    .timer-urgent {
        background: linear-gradient(90deg,#8B0000,#FF0000);
        padding:15px 25px; border-radius:12px;
        color:white; font-size:24px; font-weight:bold; text-align:center;
    }
    .result-correct { color:#2ECC71; font-weight:bold; }
    .result-wrong   { color:#E74C3C; font-weight:bold; }
</style>
""", unsafe_allow_html=True)


# ==================== MATH RENDER (KaTeX) ====================
def render_math_html(text: str, font_size: str = "20px", bg: str = "rgba(255,255,255,0.05)") -> None:
    """KaTeX bilan formulalarni to'g'ri render qilish."""
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
  <script defer
          src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
  <script defer
          src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"
          onload="renderMathInElement(document.body, {{
            delimiters: [
              {{left:'$$', right:'$$', display:true}},
              {{left:'$',  right:'$',  display:false}}
            ],
            throwOnError: false
          }});"></script>
  <style>
    body {{
      background: {bg};
      color: #E0E0E0;
      font-size: {font_size};
      font-family: 'Segoe UI', sans-serif;
      padding: 16px 20px;
      border-radius: 12px;
      border: 2px solid rgba(255,215,0,0.3);
      margin: 0;
    }}
    .katex {{ color: #FFD700; font-size: 1.15em; }}
    .katex-display {{ color: #FFD700; }}
  </style>
</head>
<body>{text}</body>
</html>"""
    height = max(80, min(400, 80 + len(text) // 3))
    components.html(html, height=height, scrolling=False)


# ==================== OMML → LaTeX ====================
MN = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
WN = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

NARY_OPS = {'\u222b':'\\int','\u222c':'\\iint','\u222d':'\\iiint',
             '\u2211':'\\sum','\u220f':'\\prod','\u222e':'\\oint'}
PROP_TAGS = {'rPr','fPr','radPr','naryPr','dPr','sSupPr','sSubPr','sSubSupPr',
             'funcPr','sPr','limLowPr','limUppPr','eqArrPr','mPr','ctrlPr',
             'groupChrPr','borderBoxPr','barPr','accPr','phantPr','boxPr'}
FN_MAP = {'sin':'\\sin','cos':'\\cos','tan':'\\tan','cot':'\\cot',
          'sec':'\\sec','csc':'\\csc','log':'\\log','ln':'\\ln',
          'exp':'\\exp','lim':'\\lim','max':'\\max','min':'\\min',
          'det':'\\det','gcd':'\\gcd'}
ACC_MAP = {'\u0302':'\\hat','\u0303':'\\tilde','\u0307':'\\dot',
           '\u0308':'\\ddot','\u0305':'\\bar','\u20d7':'\\vec'}


def omml_to_latex(el) -> str:
    tag = el.tag.replace(MN,'').replace(WN,'')
    if tag in PROP_TAGS: return ''
    if tag in ('oMath','oMathPara','e','num','den','fName','lim','sub','sup','deg'):
        return ''.join(omml_to_latex(c) for c in el)
    if tag == 'r':
        return ''.join(t.text or '' for t in el.findall(f'{MN}t'))
    if tag == 't':
        return el.text or ''
    if tag == 'f':
        n = omml_to_latex(el.find(f'{MN}num')) if el.find(f'{MN}num') is not None else ''
        d = omml_to_latex(el.find(f'{MN}den')) if el.find(f'{MN}den') is not None else ''
        return f'\\frac{{{n}}}{{{d}}}'
    if tag == 'rad':
        pr = el.find(f'{MN}radPr'); deg_el = el.find(f'{MN}deg'); e_el = el.find(f'{MN}e')
        hide = False
        if pr is not None:
            dh = pr.find(f'{MN}degHide')
            if dh is not None: hide = dh.get(f'{MN}val','1') != '0'
        deg = omml_to_latex(deg_el).strip() if deg_el is not None else ''
        e   = omml_to_latex(e_el).strip()   if e_el   is not None else ''
        return f'\\sqrt{{{e}}}' if (hide or not deg) else f'\\sqrt[{deg}]{{{e}}}'
    if tag == 'sSup':
        b = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        s = omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        return f'{{{b}}}^{{{s}}}'
    if tag == 'sSub':
        b = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        s = omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        return f'{{{b}}}_{{{s}}}'
    if tag == 'sSubSup':
        b = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        s = omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        p = omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        return f'{{{b}}}_{{{s}}}^{{{p}}}'
    if tag == 'nary':
        pr = el.find(f'{MN}naryPr'); op = '\\sum'
        if pr is not None:
            ch_el = pr.find(f'{MN}chr')
            if ch_el is not None: op = NARY_OPS.get(ch_el.get(f'{MN}val',''), '\\sum')
        lo = omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        hi = omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        bd = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        res = op
        if lo: res += f'_{{{lo}}}'
        if hi: res += f'^{{{hi}}}'
        return res + f' {bd}'
    if tag == 'func':
        f_raw = omml_to_latex(el.find(f'{MN}fName')).strip() if el.find(f'{MN}fName') is not None else ''
        c     = omml_to_latex(el.find(f'{MN}e')).strip()     if el.find(f'{MN}e')     is not None else ''
        return f'{FN_MAP.get(f_raw, f_raw)}\\left({c}\\right)'
    if tag == 'd':
        pr = el.find(f'{MN}dPr')
        left,right = '(',')' 
        if pr is not None:
            beg = pr.find(f'{MN}begChr'); end = pr.find(f'{MN}endChr')
            if beg is not None: left  = beg.get(f'{MN}val','(') or '.'
            if end is not None: right = end.get(f'{MN}val',')') or '.'
        inner = ''.join(omml_to_latex(c) for c in el if c.tag != f'{MN}dPr')
        return f'\\left{left}{inner}\\right{right}'
    if tag == 'm':
        rows = el.findall(f'{MN}mr')
        lr = [' & '.join(omml_to_latex(c) for c in r.findall(f'{MN}e')) for r in rows]
        return '\\begin{pmatrix}' + ' \\\\ '.join(lr) + '\\end{pmatrix}'
    if tag == 'limLow':
        b = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        l = omml_to_latex(el.find(f'{MN}lim')) if el.find(f'{MN}lim') is not None else ''
        return f'{b}_{{{l}}}'
    if tag == 'limUpp':
        b = omml_to_latex(el.find(f'{MN}e'))   if el.find(f'{MN}e')   is not None else ''
        l = omml_to_latex(el.find(f'{MN}lim')) if el.find(f'{MN}lim') is not None else ''
        return f'{b}^{{{l}}}'
    if tag == 'acc':
        pr = el.find(f'{MN}accPr'); ch = ''
        if pr is not None:
            ch_el = pr.find(f'{MN}chr')
            if ch_el is not None: ch = ch_el.get(f'{MN}val','')
        inner = omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        return f'{ACC_MAP.get(ch,"\\hat")}{{{inner}}}'
    if tag == 'bar':
        e = el.find(f'{MN}e')
        return f'\\overline{{{omml_to_latex(e) if e is not None else ""}}}'
    if tag == 'eqArr':
        return '\\begin{cases}' + ' \\\\ '.join(omml_to_latex(r) for r in el.findall(f'{MN}e')) + '\\end{cases}'
    return ''.join(omml_to_latex(c) for c in el)


# ==================== PARAGRAPH MATN ====================
def get_para_text(para) -> str:
    """para.text OMML ni o'tkazib yuboradi"""
    parts = []
    for child in para._element:
        ctag = child.tag
        if ctag == f'{MN}oMathPara':
            for om in child.findall(f'{MN}oMath'):
                lat = omml_to_latex(om).strip()
                if lat: parts.append(f'$${lat}$$')
        elif ctag == f'{MN}oMath':
            lat = omml_to_latex(child).strip()
            if lat: parts.append(f'${lat}$')
        elif ctag == f'{WN}r':
            for t in child.findall(f'{WN}t'):
                if t.text: parts.append(t.text)
        elif ctag in (f'{WN}ins', f'{WN}hyperlink'):
            for r in child.findall(f'.//{WN}r'):
                for t in r.findall(f'{WN}t'):
                    if t.text: parts.append(t.text)
    return ''.join(parts)


# ==================== RASM TAHLILI ====================
def is_geometric_image(img_array) -> bool:
    """Chizma yoki diagrama ekanligini aniqlash"""
    if len(img_array.shape) == 3:
        gray = np.mean(img_array, axis=2)
    else:
        gray = img_array
    
    # Rang soni - kam bo'lsa chizma
    unique_colors = len(np.unique(gray))
    
    # Qora fonda yozuvlar - chizma belgisi
    dark_pixels = np.sum(gray < 100) / gray.size
    
    return unique_colors < 100 or dark_pixels > 0.3


def analyze_image_with_cohere(img_bytes: bytes) -> str:
    """Cohere Vision bilan rasmni tahlil qilish"""
    if not COHERE_API_KEY:
        return "Rasmni tahlil qilish kerak lekin API key yo'q"
    
    try:
        client = cohere.ClientV2(api_key=COHERE_API_KEY)
        
        # Rasmni base64 ga o'girish
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        response = client.chat(
            model="command-r-plus-vision",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Bu rasm nima? Geometrik shakllar, formulalar, chizmalar bo'lsa tavsilabi. Faqat tavsif ber, boshqa narsa yozma. O'zbek tilida yoz."
                        }
                    ],
                }
            ],
        )
        
        return response.message.content[0].text if response.message.content else "Rasm tahlil qilinmadi"
    except Exception as e:
        return f"Xatolik: {str(e)}"


# ==================== FAYL O'QISH ====================
def extract_docx(file_bytes: bytes) -> dict:
    try:
        doc = Document(io.BytesIO(file_bytes))
        lines, images = [], []

        for para in doc.paragraphs:
            t = get_para_text(para).strip()
            if t: lines.append(t)

        for table in doc.tables:
            for row in table.rows:
                row_parts = []
                for cell in row.cells:
                    ct = ' '.join(get_para_text(p).strip() for p in cell.paragraphs
                                  if get_para_text(p).strip())
                    if ct: row_parts.append(ct)
                if row_parts: lines.append(' | '.join(row_parts))

        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    ext = rel.target_ref.split('.')[-1].lower()
                    mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
                    img_bytes = rel.target_part.blob
                    images.append({'bytes': img_bytes, 'mime': mime})
                except Exception: pass

        final = '\n\n'.join(lines)
        if not final.strip():
            res = mammoth.convert_to_html(io.BytesIO(file_bytes))
            final = BeautifulSoup(res.value,'html.parser').get_text('\n',strip=True)
        return {'text': final, 'images': images}
    except Exception as e:
        st.error(f"Word xatolik: {e}")
        return {'text':'','images':[]}


def extract_pdf(file_bytes: bytes) -> dict:
    try:
        r = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        return {'text':'\n\n'.join(p.extract_text() or '' for p in r.pages),'images':[]}
    except Exception as e:
        st.error(f"PDF xatolik: {e}")
        return {'text':'','images':[]}


# ==================== JSON TUZATISH ====================
def fix_json_escapes(raw: str) -> str:
    """JSON string ichidagi yaroqsiz LaTeX backslash larni tuzatish"""
    VALID = set(r'"\\bfnrtu/')
    result, in_str, esc = [], False, False
    for ch in raw:
        if esc:
            if in_str and ch not in VALID:
                result.append('\\')
            result.append(ch)
            esc = False
            continue
        if ch == '\\':
            esc = True
            result.append(ch)
            continue
        if ch == '"':
            in_str = not in_str
        result.append(ch)
    return ''.join(result)


def safe_json(text: str):
    for fn in [json.loads,
               lambda t: json.loads(fix_json_escapes(t)),
               lambda t: json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', t))]:
        try:
            return fn(text)
        except:
            pass
    return None


# ==================== AI TAHLIL ====================
def parse_questions_with_ai(text: str, image_bytes_list: list) -> list:
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi.")
        return []

    # Rasmlarni tahlil qilish
    image_descriptions = ""
    if image_bytes_list:
        with st.spinner("🖼️ Rasmlar tahlil qilinmoqda..."):
            for idx, img_bytes in enumerate(image_bytes_list):
                try:
                    img_array = np.array(Image.open(io.BytesIO(img_bytes)))
                    if is_geometric_image(img_array):
                        desc = analyze_image_with_cohere(img_bytes)
                        image_descriptions += f"\n\n📸 Geometrik Rasm {idx+1}: {desc}"
                except Exception as e:
                    pass

    client = Groq(api_key=GROQ_API_KEY)

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    num_approx = sum(1 for l in lines if re.match(r'^\d+[\.\)]\s', l))
    num_ask = max(num_approx, 5) if num_approx else 10

    prompt = f"""Bu olimpiada test savollari. Barcha {num_ask} ta savolni ajratib ol.

MUHIM QOIDALAR:
1. Matnda formulalar ($...$) bor — ularni AYNAN ko'chir.
2. CDOT (·) belgisini \\cdot deb yoz.
3. A, B, C, D variantlar majburiy.
4. To'g'ri javobni belgilamoq kerak.
5. JSON string ichida backslash: \\\\ (ikkita) bo'lsin.
6. Faqat JSON massivi qaytar — boshqa hech narsa yozma.

[
  {{
    "number": 1,
    "question": "Savol ($\\\\frac{{a}}{{b}}$ kabi)",
    "options": {{"A":"...","B":"...","C":"...","D":"..."}},
    "correct": "B",
    "explanation": "Yechim"
  }}
]

MATN:
{text[:9000]}

{image_descriptions}"""

    try:
        resp = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role':'user','content':prompt}],
            temperature=0.1,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r'```(?:json)?\s*','',content).strip().rstrip('`').strip()

        m = re.search(r'\[.*\]', content, re.DOTALL)
        if not m:
            st.warning("JSON topilmadi")
            return []

        result = safe_json(m.group())
        if result is None:
            st.error("JSON parse muvaffaqiyatsiz")
            return []
        return result
    except Exception as e:
        st.error(f"AI xatosi: {e}")
        return []


# ==================== YORDAMCHILAR ====================
def grade(pct):
    if pct>=85: return "5 — A'lo"
    if pct>=70: return "4 — Yaxshi"
    if pct>=50: return "3 — Qoniqarli"
    return "2 — Qoniqarsiz"


def fmt_time(sec):
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ==================== SESSION STATE ====================
DEFAULTS = {
    'questions':[],'current_q':0,'answers':{},
    'started':False,'finished':False,
    'name':'','surname':'',
    'duration':90,'start_time':None,
    'uploaded_files':[],'images':[],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name = st.text_input("Ism", st.session_state.name)
    st.session_state.surname = st.text_input("Familiya", st.session_state.surname)

    st.markdown("---")
    st.markdown("### ⚙️ Sozlamalar")
    st.session_state.duration = st.number_input("⏱ Vaqt (daqiqa)", 5, 300, st.session_state.duration)

    st.markdown("---")
    st.markdown("### 📁 Test fayllari")
    uploaded = st.file_uploader("Fayl yuklang (.docx yoki .pdf)",
                                type=["docx","pdf"], accept_multiple_files=True)
    if uploaded:
        st.session_state.uploaded_files = uploaded
        for f in uploaded:
            st.success(f"✅ {f.name}")

    if st.session_state.started and not st.session_state.finished:
        st.markdown("---")
        if st.button("⛔ Testni to'xtatish", use_container_width=True):
            st.session_state.finished = True
            st.rerun()


# ==================== ASOSIY SAHIFA ====================
st.title("🏆 OlimpTest")
st.markdown("#### Olimpiada Mashq Platformasi")

# ─── BOSHLASH ────────────────────────────────────────
if not st.session_state.started:
    st.markdown("""
    <div style="background:rgba(255,255,255,0.05);padding:25px;border-radius:15px;
                border:2px solid rgba(255,215,0,0.3);margin:15px 0;">
    <h3 style="color:#FFD700;">📋 Qo'llanma</h3>
    <ul style="color:#E0E0E0;">
        <li>Ism-familiyangizni kiriting</li>
        <li>Word (.docx) yoki PDF fayl yuklang</li>
        <li>Vaqt belgilang va "Testni boshlash" tugmasini bosing</li>
        <li><b>Matematik formulalar va rasmlar avtomatik aniqlanadi</b></li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.uploaded_files and st.session_state.name.strip():
        if st.button("🚀 Testni boshlash", type="primary", use_container_width=True):
            with st.spinner("📖 Fayl o'qilmoqda..."):
                all_text, all_images = "", []
                for f in st.session_state.uploaded_files:
                    raw = f.read()
                    data = extract_docx(raw) if f.name.lower().endswith('.docx') else extract_pdf(raw)
                    all_text += data['text'] + '\n\n'
                    all_images += data.get('images', [])

            if not all_text.strip():
                st.error("❌ Fayldan matn olinmadi.")
                st.stop()

            with st.spinner("🤖 AI savollarni tahlil qilmoqda..."):
                image_bytes_list = [img['bytes'] for img in all_images]
                questions = parse_questions_with_ai(all_text, image_bytes_list)

            if not questions:
                st.error("❌ Savollar tahlil qilinmadi.")
                st.stop()

            st.session_state.questions = questions
            st.session_state.images = all_images
            st.session_state.started = True
            st.session_state.start_time = time.time()
            st.session_state.current_q = 0
            st.session_state.answers = {}
            st.rerun()
    else:
        if not st.session_state.name.strip():
            st.info("⬅️ Ismingizni kiriting")
        if not st.session_state.uploaded_files:
            st.info("⬅️ Fayl yuklang")

# ─── TEST ─────────────────────────────────────────────
elif not st.session_state.finished:
    elapsed = time.time() - st.session_state.start_time
    remaining = max(0, int(st.session_state.duration * 60 - elapsed))
    if remaining == 0:
        st.session_state.finished = True
        st.rerun()

    questions = st.session_state.questions
    total_q = len(questions)
    q_idx = st.session_state.current_q
    q = questions[q_idx]

    # Yuqori panel
    h1, h2, h3 = st.columns([2, 3, 1])
    with h1:
        st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")
    with h2:
        answered = len(st.session_state.answers)
        st.progress(answered / total_q, text=f"Javob berilgan: {answered}/{total_q}")
    with h3:
        tcls = "timer-urgent" if remaining < 60 else "timer-box"
        st.markdown(f'<div class="{tcls}">⏱ {fmt_time(remaining)}</div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### Savol {q_idx + 1} / {total_q}")

    # Savol matni — KaTeX bilan render
    q_num = q.get('number', q_idx + 1)
    q_text = q.get('question', '')
    render_math_html(f"<b>{q_num}.</b> {q_text}", font_size="20px")

    # Variantlar
    options = q.get('options', {})
    opt_keys = list(options.keys())
    prev_ans = st.session_state.answers.get(q_idx)
    prev_idx = opt_keys.index(prev_ans) if prev_ans in opt_keys else None

    st.markdown("**Javobingizni tanlang:**")
    for ki, k in enumerate(opt_keys):
        v = options[k]
        col1, col2 = st.columns([0.08, 0.92])
        with col1:
            checked = (prev_ans == k)
            if st.button("●" if checked else "○",
                         key=f"opt_{q_idx}_{k}",
                         help=k):
                st.session_state.answers[q_idx] = k
                st.rerun()
        with col2:
            render_math_html(
                f"<b>{k})</b> {v}",
                font_size="18px",
                bg="rgba(255,215,0,0.08)" if checked else "transparent"
            )

    # Navigatsiya
    nav1, nav2, nav3 = st.columns([1, 1, 1])
    with nav1:
        if q_idx > 0 and st.button("⬅️ Oldingi", use_container_width=True):
            st.session_state.current_q -= 1
            st.rerun()
    with nav2:
        if q_idx < total_q - 1 and st.button("Keyingi ➡️", use_container_width=True):
            st.session_state.current_q += 1
            st.rerun()
    with nav3:
        if st.button("✅ Yakunlash", type="primary", use_container_width=True):
            st.session_state.finished = True
            st.rerun()

    # Mini panel
    st.markdown("---")
    st.markdown("**Savollar paneli** (✓ = javob berilgan):")
    COLS = 10
    for rs in range(0, total_q, COLS):
        row_qs = list(range(rs, min(rs + COLS, total_q)))
        cols = st.columns(len(row_qs))
        for col, i in zip(cols, row_qs):
            with col:
                lbl = f"✓{i+1}" if i in st.session_state.answers else str(i+1)
                btyp = "primary" if i == q_idx else "secondary"
                if st.button(lbl, key=f"nav_{i}", type=btyp, use_container_width=True):
                    st.session_state.current_q = i
                    st.rerun()

    time.sleep(1)
    st.rerun()

# ─── NATIJA ───────────────────────────────────────────
else:
    questions = st.session_state.questions
    total_q = len(questions)
    correct = sum(1 for i, q in enumerate(questions)
                  if st.session_state.answers.get(i) == q.get('correct'))
    pct = (correct / total_q * 100) if total_q else 0.0

    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ To'g'ri", f"{correct}/{total_q}")
    c2.metric("❌ Noto'g'ri", f"{total_q-correct}/{total_q}")
    c3.metric("📊 Foiz", f"{pct:.1f}%")
    c4.metric("🎓 Baho", grade(pct))

    color = "#2ECC71" if pct >= 70 else "#E67E22" if pct >= 50 else "#E74C3C"
    st.markdown(
        f'<div style="background:#333;border-radius:10px;height:20px;margin:10px 0;">'
        f'<div style="background:{color};width:{pct:.1f}%;height:20px;border-radius:10px;"></div></div>',
        unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")
    for i, q in enumerate(questions):
        user_ans = st.session_state.answers.get(i)
        correct_ans = q.get('correct', '?')
        is_correct = user_ans == correct_ans
        icon = "✅" if is_correct else ("❌" if user_ans else "⬜")

        with st.expander(f"{icon}  Savol {i+1}  |  Sizning: {user_ans or '—'}  |  To'g'ri: {correct_ans}"):
            render_math_html(f"<b>Savol:</b> {q['question']}")
            for k, v in q.get('options', {}).items():
                if k == correct_ans:
                    render_math_html(f"✅ <b>{k})</b> {v}", bg="rgba(46,204,113,0.15)")
                elif k == user_ans:
                    render_math_html(f"❌ <b>{k})</b> {v}", bg="rgba(231,76,60,0.15)")
                else:
                    render_math_html(f"&nbsp;&nbsp;{k}) {v}", bg="transparent")
            if q.get('explanation'):
                st.info(f"💡 **Yechim:** {q['explanation']}")

    if st.button("🔄 Yangi test", type="primary", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

st.markdown("---")
st.markdown(
    "<p style='text-align:center; color:#888; font-size:14px;'>Yaratuvchi: Usmonov Sodiq</p>",
    unsafe_allow_html=True,
)
