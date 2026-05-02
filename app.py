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
        animation: pulse 1s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.7} }
    .nav-btn { min-width: 40px; }
    .answered-btn { background: #2ECC71 !important; }
    .MathJax { color: #FFFFFF !important; font-size: 1.2em !important; }
    .question-box p, .question-box li { color: #E0E0E0; font-size: 18px; }
    .question-box img { max-width: 100%; border-radius: 8px; margin: 10px 0; }
    .result-correct { color: #2ECC71; font-weight: bold; }
    .result-wrong   { color: #E74C3C; font-weight: bold; }
    div[data-testid="stExpander"] { border: 1px solid rgba(255,215,0,0.2); border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# ==================== MathJax (bir marta, HEAD'da) ====================
MATHJAX_SCRIPT = """
<script>
if(!window._mathJaxLoaded){
  window._mathJaxLoaded = true;
  window.MathJax = {
    tex: {
      inlineMath: [['$','$'],['\\\\(','\\\\)']],
      displayMath: [['$$','$$'],['\\\\[','\\\\]']],
      processEscapes: true
    },
    svg: { fontCache: 'global' },
    startup: { typeset: true }
  };
  var s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';
  s.async = true;
  document.head.appendChild(s);
}
if(window.MathJax && window.MathJax.typesetPromise){
  window.MathJax.typesetPromise();
}
</script>
"""


# ==================== FAYL O'QISH ====================
def omml_to_latex(omml_element):
    """OMML → LaTeX (asosiy strukturalar)"""
    try:
        ns = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
        parts = []

        def walk(el, ctx=""):
            tag = el.tag.replace(ns, '')
            if tag == 'frac':
                num_els = el.findall(f'.//{ns}num/{ns}e')
                den_els = el.findall(f'.//{ns}den/{ns}e')
                num = walk_children(num_els[0]) if num_els else walk_text(el, 'num')
                den = walk_children(den_els[0]) if den_els else walk_text(el, 'den')
                return f"\\frac{{{num}}}{{{den}}}"
            elif tag == 'rad':
                deg_els = el.findall(f'.//{ns}deg')
                e_els   = el.findall(f'.//{ns}e')
                deg = "".join(c.text or "" for c in deg_els[0].iter() if c.text) if deg_els else ""
                e   = "".join(c.text or "" for c in e_els[0].iter()   if c.text) if e_els   else ""
                return f"\\sqrt[{deg}]{{{e}}}" if deg.strip() else f"\\sqrt{{{e}}}"
            elif tag == 'sSup':
                base = el.find(f'{ns}e')
                sup  = el.find(f'{ns}sup')
                b = walk_children(base) if base is not None else ""
                s = walk_children(sup)  if sup  is not None else ""
                return f"{{{b}}}^{{{s}}}"
            elif tag == 'sSub':
                base = el.find(f'{ns}e')
                sub  = el.find(f'{ns}sub')
                b = walk_children(base) if base is not None else ""
                s = walk_children(sub)  if sub  is not None else ""
                return f"{{{b}}}_{{{s}}}"
            elif tag == 't' and el.text:
                return el.text
            return ""

        def walk_children(el):
            return "".join(walk(c) for c in el)

        def walk_text(el, child_tag):
            els = el.findall(f'.//{ns}{child_tag}//{ns}t')
            return "".join(e.text or "" for e in els)

        return walk_children(omml_element).strip()
    except Exception:
        return ""


def extract_docx_with_math(file_bytes: bytes) -> dict:
    """Word faylidan matn + formulalar + rasmlarni ajratib olish"""
    try:
        # Mammoth → HTML (inline rasm data-URI sifatida)
        result = mammoth.convert_to_html(io.BytesIO(file_bytes))
        html   = result.value

        # python-docx bilan paragraflar + OMML formulalar
        doc = Document(io.BytesIO(file_bytes))
        full_text = []
        images    = []

        for para in doc.paragraphs:
            para_text = para.text.strip()
            math_ns   = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
            for omml in para._element.findall(f'.//{math_ns}oMath'):
                latex = omml_to_latex(omml)
                if latex:
                    para_text += f" ${latex}$ "
            if para_text:
                full_text.append(para_text)

        # Rasmlarni base64 ga aylantirish
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    img_b64 = base64.b64encode(rel.target_part.blob).decode()
                    ext     = rel.target_ref.split(".")[-1].lower()
                    mime    = f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
                    images.append({"b64": img_b64, "mime": mime})
                except Exception:
                    pass

        final_text = "\n\n".join(full_text)
        # Agar python-docx bo'sh qaytarsa, mammoth matni ishlatiladi
        if not final_text.strip():
            final_text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)

        return {"text": final_text, "html": html, "images": images}

    except Exception as e:
        st.error(f"Word faylni o'qishda xatolik: {e}")
        return {"text": "", "html": "", "images": []}


def extract_pdf(file_bytes: bytes) -> dict:
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages  = [p.extract_text() or "" for p in reader.pages]
        return {"text": "\n\n".join(pages), "html": "", "images": []}
    except Exception as e:
        st.error(f"PDF xatolik: {e}")
        return {"text": "", "html": "", "images": []}


# ==================== AI SAVOL TAHLILI ====================
def parse_questions_with_ai(text: str, num_questions: int = 10) -> list:
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi. Streamlit Secrets ga qo'shing.")
        return []

    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""Quyidagi matn olimpiada test savollaridan iborat.
Undan {num_questions} ta savolni ajratib ol.

QOIDALAR:
1. Matematik formulalar LaTeX formatida ($...$) bo'lsin.
2. Har bir savolda A, B, C, D variantlar majburiy.
3. To'g'ri javobni aniqla yoki o'zing yech.
4. Faqat JSON, boshqa hech narsa yozma.

JSON struktura:
[
  {{
    "number": 1,
    "question": "Savol matni (LaTeX bilan)",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "A",
    "explanation": "Qisqa yechim"
  }}
]

MATN:
{text[:8000]}"""

    try:
        resp    = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()

        # Markdown kod blokini tozalash
        content = re.sub(r"```(?:json)?", "", content).strip().rstrip("`")

        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        st.warning("AI dan JSON olinmadi. Xom javob:\n" + content[:500])
        return []

    except json.JSONDecodeError as e:
        st.error(f"JSON parse xatosi: {e}")
        return []
    except Exception as e:
        st.error(f"AI tahlil xatosi: {e}")
        return []


# ==================== YORDAMCHI ====================
def render_math(text: str):
    """Matnni MathJax bilan ko'rsatish"""
    st.markdown(f"<div>{text}</div>{MATHJAX_SCRIPT}", unsafe_allow_html=True)


def grade(pct: float) -> str:
    if pct >= 85: return "5 (A'lo)"
    if pct >= 70: return "4 (Yaxshi)"
    if pct >= 50: return "3 (Qoniqarli)"
    return "2 (Qoniqarsiz)"


def format_time(seconds: int) -> str:
    h, r  = divmod(seconds, 3600)
    m, s  = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ==================== SESSION STATE ====================
DEFAULTS = {
    "questions":      [],
    "current_q":      0,
    "answers":        {},
    "started":        False,
    "finished":       False,
    "name":           "",
    "surname":        "",
    "duration":       90,
    "start_time":     None,
    "uploaded_files": [],
    "images":         [],        # FIX: avval yo'q edi → KeyError
    "num_questions":  10,
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
    st.markdown("### ⚙️ Test sozlamalari")
    st.session_state.duration      = st.number_input("⏱ Vaqt (daqiqa)", 5, 300, st.session_state.duration)
    st.session_state.num_questions = st.number_input("📊 Savollar soni", 1, 50,  st.session_state.num_questions)

    st.markdown("---")
    st.markdown("### 📁 Test fayllari")
    uploaded = st.file_uploader(
        "Fayl yuklang (.docx yoki .pdf)",
        type=["docx", "pdf"],
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

# ─── BOSHLASH EKRANI ──────────────────────────────────────────────────────────
if not st.session_state.started:
    st.markdown("""
    <div class="question-box">
    <h3>📋 Qo'llanma</h3>
    <ul>
        <li>Chap paneldan ism-familiyangizni kiriting</li>
        <li>Word (.docx) yoki PDF test faylini yuklang</li>
        <li>Savollar soni va vaqtni belgilang</li>
        <li>"Testni boshlash" tugmasini bosing</li>
        <li>Matematik formulalar (LaTeX) va rasmlar avtomatik ko'rinadi</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    ready = bool(st.session_state.uploaded_files and st.session_state.name.strip())

    if ready:
        if st.button("🚀 Testni boshlash", type="primary", use_container_width=True):
            with st.spinner("📖 Fayl o'qilmoqda va AI savollarni tahlil qilmoqda..."):
                all_text   = ""
                all_images = []

                for f in st.session_state.uploaded_files:
                    raw = f.read()
                    if f.name.lower().endswith(".docx"):
                        data = extract_docx_with_math(raw)
                    else:
                        data = extract_pdf(raw)
                    all_text   += data["text"] + "\n\n"
                    all_images += data.get("images", [])

                if not all_text.strip():
                    st.error("❌ Fayldan matn olinmadi. Fayl to'g'ri formatda ekanini tekshiring.")
                    st.stop()

                questions = parse_questions_with_ai(all_text, st.session_state.num_questions)
                if not questions:
                    st.error("❌ Savollar ajratib olinmadi. Fayl mazmunini yoki API kalitini tekshiring.")
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
            st.info("⬅️ Iltimos, test faylini yuklang")

# ─── TEST JARAYONI ─────────────────────────────────────────────────────────────
elif not st.session_state.finished:
    elapsed   = time.time() - st.session_state.start_time
    total_sec = st.session_state.duration * 60
    remaining = max(0, total_sec - int(elapsed))

    # Vaqt tugadi
    if remaining == 0:
        st.session_state.finished = True
        st.rerun()

    questions = st.session_state.questions
    total_q   = len(questions)
    q_idx     = st.session_state.current_q
    q         = questions[q_idx]

    # ── Yuqori qator: Isim | Progresss | Timer ──
    header_col, prog_col, timer_col = st.columns([2, 3, 1])

    with header_col:
        st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")

    with prog_col:
        answered_count = len(st.session_state.answers)
        st.progress(answered_count / total_q, text=f"Javob berilgan: {answered_count}/{total_q}")

    with timer_col:
        timer_class = "timer-urgent" if remaining < 60 else "timer-box"
        st.markdown(
            f'<div class="{timer_class}">⏱ {format_time(remaining)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Savol ──
    st.markdown(f"### Savol {q_idx + 1} / {total_q}")
    question_html = f"""
    <div class="question-box">
        <p style="font-size:20px;color:#FFFFFF;">
            <b>{q.get('number', q_idx+1)}.</b> {q['question']}
        </p>
    </div>
    {MATHJAX_SCRIPT}
    """
    st.markdown(question_html, unsafe_allow_html=True)

    # ── Javob variantlari ──
    options  = q.get("options", {})
    prev_ans = st.session_state.answers.get(q_idx)

    # radio index ni oldingi javobga moslashtirish
    opt_keys   = list(options.keys())
    prev_index = opt_keys.index(prev_ans) if prev_ans in opt_keys else None

    selected = st.radio(
        "Javobingizni tanlang:",
        opt_keys,
        format_func=lambda x: f"{x})  {options[x]}",
        key=f"radio_{q_idx}",
        index=prev_index,
    )

    if selected:
        st.session_state.answers[q_idx] = selected

    # Variantlardagi formulalar
    st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    # ── Navigatsiya tugmalari ──
    st.markdown("")
    nav1, nav2, nav3 = st.columns([1, 1, 1])
    with nav1:
        if q_idx > 0:
            if st.button("⬅️ Oldingi", use_container_width=True):
                st.session_state.current_q -= 1
                st.rerun()
    with nav2:
        if q_idx < total_q - 1:
            if st.button("Keyingi ➡️", use_container_width=True):
                st.session_state.current_q += 1
                st.rerun()
    with nav3:
        if st.button("✅ Yakunlash", type="primary", use_container_width=True):
            unanswered = total_q - len(st.session_state.answers)
            if unanswered > 0:
                confirm = st.warning(
                    f"⚠️ {unanswered} ta savolga javob berilmagan. Baribir yakunlashni xohlaysizmi?"
                )
            st.session_state.finished = True
            st.rerun()

    # ── Savollar panel (mini navigatsiya) ──
    st.markdown("---")
    st.markdown("**Savollar paneli** (✓ = javob berilgan):")

    COLS_PER_ROW = 10
    for row_start in range(0, total_q, COLS_PER_ROW):
        row_qs  = list(range(row_start, min(row_start + COLS_PER_ROW, total_q)))
        cols    = st.columns(len(row_qs))
        for col, i in zip(cols, row_qs):
            with col:
                label    = f"✓{i+1}" if i in st.session_state.answers else str(i + 1)
                btn_type = "primary" if i == q_idx else "secondary"
                if st.button(label, key=f"nav_q_{i}", type=btn_type, use_container_width=True):
                    st.session_state.current_q = i
                    st.rerun()

    # ── Timer auto-refresh (har 1 soniyada) ──
    time.sleep(1)
    st.rerun()


# ─── NATIJALAR EKRANI ──────────────────────────────────────────────────────────
else:
    questions = st.session_state.questions
    total_q   = len(questions)

    correct_count = sum(
        1 for i, q in enumerate(questions)
        if st.session_state.answers.get(i) == q.get("correct")
    )
    pct = (correct_count / total_q * 100) if total_q else 0.0

    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}** — natijangiz:")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("✅ To'g'ri",     f"{correct_count} / {total_q}")
    m2.metric("❌ Noto'g'ri",   f"{total_q - correct_count} / {total_q}")
    m3.metric("📊 Foiz",        f"{pct:.1f}%")
    m4.metric("🎓 Baho",        grade(pct))

    # Progress bar — natija
    color = "#2ECC71" if pct >= 70 else "#E67E22" if pct >= 50 else "#E74C3C"
    st.markdown(
        f"""<div style="background:#333;border-radius:10px;height:20px;margin:10px 0;">
        <div style="background:{color};width:{pct:.1f}%;height:20px;border-radius:10px;"></div>
        </div>""",
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")

    for i, q in enumerate(questions):
        user_ans    = st.session_state.answers.get(i, None)
        correct_ans = q.get("correct", "?")
        is_correct  = user_ans == correct_ans
        icon        = "✅" if is_correct else ("❌" if user_ans else "⬜")

        with st.expander(f"{icon}  Savol {i+1}  |  Javobingiz: {user_ans or '—'}  |  To'g'ri: {correct_ans}"):
            st.markdown(
                f"<div class='question-box'><b>Savol:</b> {q['question']}</div>{MATHJAX_SCRIPT}",
                unsafe_allow_html=True,
            )
            for k, v in q.get("options", {}).items():
                if k == correct_ans:
                    st.markdown(f"<span class='result-correct'>✅ {k}) {v}</span>", unsafe_allow_html=True)
                elif k == user_ans:
                    st.markdown(f"<span class='result-wrong'>❌ {k}) {v}</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"&nbsp;&nbsp;&nbsp;{k}) {v}")

            explanation = q.get("explanation", "")
            if explanation:
                st.info(f"💡 **Yechim:** {explanation}")

            st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    st.markdown("---")
    if st.button("🔄 Yangi test boshlash", type="primary", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
