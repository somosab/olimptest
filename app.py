import streamlit as st
import os
import re
import io
import json
import base64
import time
from groq import Groq
import mammoth
from docx import Document
import PyPDF2
from bs4 import BeautifulSoup

# ==================== SOZLAMALAR ====================
st.set_page_config(
    page_title="OlimpTest - Olimpiada Mashq Platformasi",
    page_icon="🏆",
    layout="wide",
)

GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", os.getenv("GROQ_API_KEY", ""))

# ==================== STIL ====================
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%); }
    h1, h2, h3 { color: #FFD700 !important; }
    .stButton>button {
        background: linear-gradient(90deg, #FF8C00, #FFA500);
        color: white; border: none; border-radius: 10px;
        font-weight: bold; padding: 10px 20px;
    }
    .question-box {
        background: rgba(255,255,255,0.05);
        padding: 25px; border-radius: 15px;
        border: 2px solid rgba(255,215,0,0.3);
        margin: 15px 0;
    }
    .timer-box {
        background: linear-gradient(90deg, #FF4500, #FF8C00);
        padding: 15px 25px; border-radius: 12px;
        color: white; font-size: 24px; font-weight: bold;
        text-align: center;
    }
    .timer-urgent {
        background: linear-gradient(90deg, #8B0000, #FF0000);
        padding: 15px 25px; border-radius: 12px;
        color: white; font-size: 24px; font-weight: bold;
        text-align: center;
    }
    .MathJax { color: #FFFFFF !important; font-size: 1.2em !important; }
    .question-box p, .question-box li { color: #E0E0E0; font-size: 18px; }
    .question-box img { max-width: 100%; border-radius: 8px; margin: 10px 0; }
    .result-correct { color: #2ECC71; font-weight: bold; }
    .result-wrong   { color: #E74C3C; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

MATHJAX_SCRIPT = """
<script>
if(!window._mjLoaded){
  window._mjLoaded=true;
  window.MathJax={
    tex:{inlineMath:[['$','$'],['\\\\(','\\\\)']],
         displayMath:[['$$','$$'],['\\\\[','\\\\]']],
         processEscapes:true},
    svg:{fontCache:'global'}
  };
  var s=document.createElement('script');
  s.src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';
  s.async=true; document.head.appendChild(s);
}else if(window.MathJax&&window.MathJax.typesetPromise){
  setTimeout(()=>window.MathJax.typesetPromise(),100);
}
</script>
"""

# ==================== OMML → LaTeX ====================
MN = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
WN = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

NARY_OPS = {
    '\u222b': '\\int',
    '\u222c': '\\iint',
    '\u222d': '\\iiint',
    '\u2211': '\\sum',
    '\u220f': '\\prod',
    '\u222e': '\\oint',
}

PROP_TAGS = {
    'rPr','fPr','radPr','naryPr','dPr','sSupPr','sSubPr',
    'sSubSupPr','funcPr','sPr','limLowPr','limUppPr','eqArrPr',
    'mPr','ctrlPr','groupChrPr','borderBoxPr','barPr','accPr',
    'phantPr','boxPr',
}

FN_MAP = {
    'sin':'\\sin','cos':'\\cos','tan':'\\tan','cot':'\\cot',
    'sec':'\\sec','csc':'\\csc','log':'\\log','ln':'\\ln',
    'exp':'\\exp','lim':'\\lim','max':'\\max','min':'\\min',
    'det':'\\det','gcd':'\\gcd',
}

ACC_MAP = {
    '\u0302':'\\hat', '\u0303':'\\tilde', '\u0307':'\\dot',
    '\u0308':'\\ddot','\u0305':'\\bar',   '\u20d7':'\\vec',
}


def omml_to_latex(el) -> str:
    """OMML elementini rekursiv LaTeX ga aylantirish"""
    tag = el.tag.replace(MN, '').replace(WN, '')

    if tag in PROP_TAGS:
        return ''

    if tag in ('oMath','oMathPara','e','num','den','fName','lim','sub','sup','deg'):
        return ''.join(omml_to_latex(c) for c in el)

    if tag == 'r':
        return ''.join(t.text or '' for t in el.findall(f'{MN}t'))

    if tag == 't':
        return el.text or ''

    if tag == 'f':
        num = el.find(f'{MN}num')
        den = el.find(f'{MN}den')
        n = omml_to_latex(num) if num is not None else ''
        d = omml_to_latex(den) if den is not None else ''
        return f'\\frac{{{n}}}{{{d}}}'

    if tag == 'rad':
        pr     = el.find(f'{MN}radPr')
        deg_el = el.find(f'{MN}deg')
        e_el   = el.find(f'{MN}e')
        hide   = False
        if pr is not None:
            dh = pr.find(f'{MN}degHide')
            if dh is not None:
                hide = dh.get(f'{MN}val', '1') != '0'
        deg = omml_to_latex(deg_el).strip() if deg_el is not None else ''
        e   = omml_to_latex(e_el).strip()   if e_el   is not None else ''
        if hide or not deg:
            return f'\\sqrt{{{e}}}'
        return f'\\sqrt[{deg}]{{{e}}}'

    if tag == 'sSup':
        base = el.find(f'{MN}e')
        sup  = el.find(f'{MN}sup')
        b = omml_to_latex(base) if base is not None else ''
        s = omml_to_latex(sup)  if sup  is not None else ''
        return f'{{{b}}}^{{{s}}}'

    if tag == 'sSub':
        base = el.find(f'{MN}e')
        sub  = el.find(f'{MN}sub')
        b = omml_to_latex(base) if base is not None else ''
        s = omml_to_latex(sub)  if sub  is not None else ''
        return f'{{{b}}}_{{{s}}}'

    if tag == 'sSubSup':
        base = el.find(f'{MN}e')
        sub  = el.find(f'{MN}sub')
        sup  = el.find(f'{MN}sup')
        b = omml_to_latex(base) if base is not None else ''
        s = omml_to_latex(sub)  if sub  is not None else ''
        p = omml_to_latex(sup)  if sup  is not None else ''
        return f'{{{b}}}_{{{s}}}^{{{p}}}'

    if tag == 'nary':
        pr  = el.find(f'{MN}naryPr')
        sub = el.find(f'{MN}sub')
        sup = el.find(f'{MN}sup')
        e   = el.find(f'{MN}e')
        op  = '\\sum'
        if pr is not None:
            chr_el = pr.find(f'{MN}chr')
            if chr_el is not None:
                ch = chr_el.get(f'{MN}val', '')
                op = NARY_OPS.get(ch, f'\\operatorname{{{ch}}}')
        lo   = omml_to_latex(sub) if sub is not None else ''
        hi   = omml_to_latex(sup) if sup is not None else ''
        body = omml_to_latex(e)   if e   is not None else ''
        res  = op
        if lo: res += f'_{{{lo}}}'
        if hi: res += f'^{{{hi}}}'
        return res + f' {body}'

    if tag == 'func':
        fname = el.find(f'{MN}fName')
        e     = el.find(f'{MN}e')
        f_raw = omml_to_latex(fname).strip() if fname is not None else ''
        c     = omml_to_latex(e).strip()     if e     is not None else ''
        f_cmd = FN_MAP.get(f_raw, f_raw)
        return f'{f_cmd}\\left({c}\\right)'

    if tag == 'd':
        pr    = el.find(f'{MN}dPr')
        left  = '('
        right = ')'
        if pr is not None:
            beg = pr.find(f'{MN}begChr')
            end = pr.find(f'{MN}endChr')
            if beg is not None: left  = beg.get(f'{MN}val', '(') or '.'
            if end is not None: right = end.get(f'{MN}val', ')') or '.'
        inner = ''.join(omml_to_latex(c) for c in el if c.tag != f'{MN}dPr')
        return f'\\left{left}{inner}\\right{right}'

    if tag == 'm':
        rows = el.findall(f'{MN}mr')
        latex_rows = []
        for row in rows:
            cells = row.findall(f'{MN}e')
            latex_rows.append(' & '.join(omml_to_latex(c) for c in cells))
        return '\\begin{pmatrix}' + ' \\\\ '.join(latex_rows) + '\\end{pmatrix}'

    if tag == 'limLow':
        e   = el.find(f'{MN}e')
        lim = el.find(f'{MN}lim')
        b = omml_to_latex(e)   if e   is not None else ''
        l = omml_to_latex(lim) if lim is not None else ''
        return f'{b}_{{{l}}}'

    if tag == 'limUpp':
        e   = el.find(f'{MN}e')
        lim = el.find(f'{MN}lim')
        b = omml_to_latex(e)   if e   is not None else ''
        l = omml_to_latex(lim) if lim is not None else ''
        return f'{b}^{{{l}}}'

    if tag == 'acc':
        pr = el.find(f'{MN}accPr')
        e  = el.find(f'{MN}e')
        ch = ''
        if pr is not None:
            chr_el = pr.find(f'{MN}chr')
            if chr_el is not None:
                ch = chr_el.get(f'{MN}val', '')
        acc_cmd = ACC_MAP.get(ch, '\\hat')
        inner   = omml_to_latex(e) if e is not None else ''
        return f'{acc_cmd}{{{inner}}}'

    if tag == 'bar':
        e = el.find(f'{MN}e')
        return f'\\overline{{{omml_to_latex(e) if e is not None else ""}}}'

    if tag == 'groupChr':
        e  = el.find(f'{MN}e')
        pr = el.find(f'{MN}groupChrPr')
        inner = omml_to_latex(e) if e is not None else ''
        ch = ''
        if pr is not None:
            chr_el = pr.find(f'{MN}chr')
            if chr_el is not None:
                ch = chr_el.get(f'{MN}val', '')
        if ch == '\u23de': return f'\\overbrace{{{inner}}}'
        if ch == '\u23df': return f'\\underbrace{{{inner}}}'
        return inner

    if tag == 'eqArr':
        rows  = el.findall(f'{MN}e')
        lines = [omml_to_latex(r) for r in rows]
        return '\\begin{cases}' + ' \\\\ '.join(lines) + '\\end{cases}'

    # Default: bolalarni yig'ish
    return ''.join(omml_to_latex(c) for c in el)


# ==================== PARAGRAPH MATN OLISH ====================
def get_para_text(para) -> str:
    """
    Paragraf elementidan matn + inline OMML formulalarini to'g'ri tartibda olish.
    MUHIM: para.text faqat w:r/w:t ni oladi — m:oMath ni butunlay o'tkazib yuboradi!
    """
    parts = []
    for child in para._element:
        ctag = child.tag

        if ctag == f'{MN}oMathPara':
            for omath in child.findall(f'{MN}oMath'):
                latex = omml_to_latex(omath).strip()
                if latex:
                    parts.append(f'$${latex}$$')

        elif ctag == f'{MN}oMath':
            latex = omml_to_latex(child).strip()
            if latex:
                parts.append(f'${latex}$')

        elif ctag == f'{WN}r':
            for t in child.findall(f'{WN}t'):
                if t.text:
                    parts.append(t.text)

        elif ctag == f'{WN}ins':
            for r in child.findall(f'.//{WN}r'):
                for t in r.findall(f'{WN}t'):
                    if t.text:
                        parts.append(t.text)

        elif ctag == f'{WN}hyperlink':
            for r in child.findall(f'.//{WN}r'):
                for t in r.findall(f'{WN}t'):
                    if t.text:
                        parts.append(t.text)

    return ''.join(parts)


# ==================== FAYL O'QISH ====================
def extract_docx_with_math(file_bytes: bytes) -> dict:
    try:
        doc       = Document(io.BytesIO(file_bytes))
        full_text = []
        images    = []

        # Paragraflar
        for para in doc.paragraphs:
            text = get_para_text(para).strip()
            if text:
                full_text.append(text)

        # Jadvallar
        for table in doc.tables:
            for row in table.rows:
                row_parts = []
                for cell in row.cells:
                    cell_parts = [get_para_text(p).strip() for p in cell.paragraphs]
                    cell_text  = ' '.join(x for x in cell_parts if x)
                    if cell_text:
                        row_parts.append(cell_text)
                if row_parts:
                    full_text.append(' | '.join(row_parts))

        # Rasmlar
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    ext  = rel.target_ref.split('.')[-1].lower()
                    mime = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
                    b64  = base64.b64encode(rel.target_part.blob).decode()
                    images.append({'b64': b64, 'mime': mime})
                except Exception:
                    pass

        final = '\n\n'.join(full_text)

        # Fallback: mammoth
        if not final.strip():
            res   = mammoth.convert_to_html(io.BytesIO(file_bytes))
            final = BeautifulSoup(res.value, 'html.parser').get_text('\n', strip=True)

        return {'text': final, 'images': images}

    except Exception as e:
        st.error(f"Word faylni o'qishda xatolik: {e}")
        return {'text': '', 'images': []}


def extract_pdf(file_bytes: bytes) -> dict:
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages  = [p.extract_text() or '' for p in reader.pages]
        return {'text': '\n\n'.join(pages), 'images': []}
    except Exception as e:
        st.error(f"PDF xatolik: {e}")
        return {'text': '', 'images': []}


# ==================== AI SAVOL TAHLILI ====================
def parse_questions_with_ai(text: str, num_questions: int = 10) -> list:
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi. Streamlit Secrets ga qo'shing.")
        return []

    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""Quyidagi matn olimpiada test savollaridan iborat.
Undan {num_questions} ta savolni ajratib ol.

QOIDALAR:
1. Matnda allaqachon LaTeX formulalar ($...$, $$...$$) bor — ularni AYNAN saqlash.
2. Agar qo'shimcha formulalar kerak bo'lsa LaTeX ga o'gir.
3. Har bir savolda A, B, C, D variantlar majburiy.
4. To'g'ri javobni aniq belgilamoq kerak.
5. Faqat sof JSON qaytar — markdown, ``` yoki boshqa hech narsa qo'shma.

JSON struktura:
[
  {{
    "number": 1,
    "question": "Savol matni (LaTeX formulalar $...$ ichida)",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "A",
    "explanation": "Qisqa yechim"
  }}
]

MATN:
{text[:9000]}"""

    try:
        resp = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r'```(?:json)?', '', content).strip().rstrip('`')

        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return json.loads(match.group())

        st.warning("AI dan JSON olinmadi. Xom javob:\n" + content[:500])
        return []
    except json.JSONDecodeError as e:
        st.error(f"JSON parse xatosi: {e}")
        return []
    except Exception as e:
        st.error(f"AI xatosi: {e}")
        return []


# ==================== YORDAMCHILAR ====================
def grade(pct: float) -> str:
    if pct >= 85: return "5 — A'lo"
    if pct >= 70: return "4 — Yaxshi"
    if pct >= 50: return "3 — Qoniqarli"
    return "2 — Qoniqarsiz"

def fmt_time(sec: int) -> str:
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ==================== SESSION STATE ====================
DEFAULTS = {
    'questions': [], 'current_q': 0, 'answers': {},
    'started': False, 'finished': False,
    'name': '', 'surname': '',
    'duration': 90, 'num_questions': 10,
    'start_time': None, 'uploaded_files': [], 'images': [],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name    = st.text_input("Ism",      st.session_state.name)
    st.session_state.surname = st.text_input("Familiya", st.session_state.surname)

    st.markdown("---")
    st.markdown("### ⚙️ Sozlamalar")
    st.session_state.duration      = st.number_input("⏱ Vaqt (daqiqa)", 5, 300, st.session_state.duration)
    st.session_state.num_questions = st.number_input("📊 Savollar soni", 1, 50,  st.session_state.num_questions)

    st.markdown("---")
    st.markdown("### 📁 Test fayllari")
    uploaded = st.file_uploader(
        "Fayl yuklang (.docx yoki .pdf)",
        type=["docx","pdf"],
        accept_multiple_files=True,
    )
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

# ─── BOSHLASH ─────────────────────────────────────────
if not st.session_state.started:
    st.markdown("""
    <div class="question-box">
    <h3>📋 Qo'llanma</h3>
    <ul>
        <li>Chap paneldan ism-familiya kiriting</li>
        <li>Word (.docx) yoki PDF fayl yuklang</li>
        <li>Savollar soni va vaqt belgilang</li>
        <li><b>Word ichidagi matematik formulalar (OMML) avtomatik LaTeX ga o'giriladi</b></li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.uploaded_files and st.session_state.name.strip():
        debug_mode = st.checkbox("🔍 Debug: fayldan o'qilgan matnni ko'rish (test boshlashdan oldin)")

        if st.button("🚀 Testni boshlash", type="primary", use_container_width=True):
            with st.spinner("📖 Fayl o'qilmoqda..."):
                all_text, all_images = "", []
                for f in st.session_state.uploaded_files:
                    raw  = f.read()
                    data = (extract_docx_with_math(raw)
                            if f.name.lower().endswith('.docx')
                            else extract_pdf(raw))
                    all_text   += data['text'] + '\n\n'
                    all_images += data.get('images', [])

            if debug_mode:
                st.subheader("O'qilgan matn:")
                st.text_area("", all_text[:4000], height=400)
                st.info("Debug rejimida test boshlanmaydi. Checkbox ni olib tashlang.")
                st.stop()

            if not all_text.strip():
                st.error("❌ Fayldan matn olinmadi.")
                st.stop()

            with st.spinner("🤖 AI savollarni tahlil qilmoqda..."):
                questions = parse_questions_with_ai(all_text, st.session_state.num_questions)

            if not questions:
                st.error("❌ Savollar tahlil qilinmadi.")
                st.stop()

            st.session_state.questions  = questions
            st.session_state.images     = all_images
            st.session_state.started    = True
            st.session_state.start_time = time.time()
            st.session_state.current_q  = 0
            st.session_state.answers    = {}
            st.rerun()
    else:
        if not st.session_state.name.strip():
            st.info("⬅️ Iltimos, ismingizni kiriting")
        if not st.session_state.uploaded_files:
            st.info("⬅️ Iltimos, fayl yuklang")

# ─── TEST ─────────────────────────────────────────────
elif not st.session_state.finished:
    elapsed   = time.time() - st.session_state.start_time
    remaining = max(0, int(st.session_state.duration * 60 - elapsed))

    if remaining == 0:
        st.session_state.finished = True
        st.rerun()

    questions = st.session_state.questions
    total_q   = len(questions)
    q_idx     = st.session_state.current_q
    q         = questions[q_idx]

    # Yuqori panel
    h1, h2, h3 = st.columns([2, 3, 1])
    with h1:
        st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")
    with h2:
        answered = len(st.session_state.answers)
        st.progress(answered / total_q, text=f"Javob berilgan: {answered}/{total_q}")
    with h3:
        tcls = "timer-urgent" if remaining < 60 else "timer-box"
        st.markdown(f'<div class="{tcls}">⏱ {fmt_time(remaining)}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### Savol {q_idx + 1} / {total_q}")

    # Savol matni (MathJax bilan)
    q_html = f"""
    <div class="question-box">
        <p style="font-size:20px;color:#FFFFFF;">
            <b>{q.get('number', q_idx+1)}.</b> {q['question']}
        </p>
    </div>{MATHJAX_SCRIPT}"""
    st.markdown(q_html, unsafe_allow_html=True)

    # Variantlar
    options  = q.get('options', {})
    opt_keys = list(options.keys())
    prev_ans = st.session_state.answers.get(q_idx)
    prev_idx = opt_keys.index(prev_ans) if prev_ans in opt_keys else None

    selected = st.radio(
        "Javobingizni tanlang:",
        opt_keys,
        format_func=lambda x: f"{x})  {options[x]}",
        key=f"radio_{q_idx}",
        index=prev_idx,
    )
    if selected:
        st.session_state.answers[q_idx] = selected

    st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    # Navigatsiya tugmalari
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

    # Mini navigatsiya paneli
    st.markdown("---")
    st.markdown("**Savollar paneli** (✓ = javob berilgan):")
    COLS = 10
    for rs in range(0, total_q, COLS):
        row_qs = list(range(rs, min(rs + COLS, total_q)))
        cols   = st.columns(len(row_qs))
        for col, i in zip(cols, row_qs):
            with col:
                lbl  = f"✓{i+1}" if i in st.session_state.answers else str(i+1)
                btyp = "primary" if i == q_idx else "secondary"
                if st.button(lbl, key=f"nav_{i}", type=btyp, use_container_width=True):
                    st.session_state.current_q = i
                    st.rerun()

    # Timer avtomatik yangilanishi
    time.sleep(1)
    st.rerun()

# ─── NATIJA ───────────────────────────────────────────
else:
    questions = st.session_state.questions
    total_q   = len(questions)
    correct   = sum(
        1 for i, q in enumerate(questions)
        if st.session_state.answers.get(i) == q.get('correct')
    )
    pct = (correct / total_q * 100) if total_q else 0.0

    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ To'g'ri",   f"{correct}/{total_q}")
    c2.metric("❌ Noto'g'ri", f"{total_q-correct}/{total_q}")
    c3.metric("📊 Foiz",      f"{pct:.1f}%")
    c4.metric("🎓 Baho",      grade(pct))

    color = "#2ECC71" if pct >= 70 else "#E67E22" if pct >= 50 else "#E74C3C"
    st.markdown(
        f'<div style="background:#333;border-radius:10px;height:20px;margin:10px 0;">'
        f'<div style="background:{color};width:{pct:.1f}%;height:20px;border-radius:10px;"></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")
    for i, q in enumerate(questions):
        user_ans    = st.session_state.answers.get(i)
        correct_ans = q.get('correct', '?')
        is_correct  = user_ans == correct_ans
        icon        = "✅" if is_correct else ("❌" if user_ans else "⬜")

        with st.expander(f"{icon}  Savol {i+1}  |  Sizning: {user_ans or '—'}  |  To'g'ri: {correct_ans}"):
            st.markdown(
                f"<div class='question-box'><b>Savol:</b> {q['question']}</div>{MATHJAX_SCRIPT}",
                unsafe_allow_html=True,
            )
            for k, v in q.get('options', {}).items():
                if k == correct_ans:
                    st.markdown(f"<span class='result-correct'>✅ {k}) {v}</span>", unsafe_allow_html=True)
                elif k == user_ans:
                    st.markdown(f"<span class='result-wrong'>❌ {k}) {v}</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"&nbsp;&nbsp;{k}) {v}")
            if q.get('explanation'):
                st.info(f"💡 **Yechim:** {q['explanation']}")
            st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    if st.button("🔄 Yangi test", type="primary", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
