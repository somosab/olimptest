import streamlit as st
import os
import re
import io
import base64
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

# Groq API key (Streamlit Secrets'dan)
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
    /* MathJax formula styling */
    .MathJax { color: #FFFFFF !important; font-size: 1.2em !important; }
    .question-box p, .question-box li { color: #E0E0E0; font-size: 18px; }
    .question-box img { max-width: 100%; border-radius: 8px; margin: 10px 0; }
</style>
""", unsafe_allow_html=True)

# ==================== MathJax YUKLASH ====================
MATHJAX_SCRIPT = """
<script>
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true
  },
  svg: { fontCache: 'global' }
};
</script>
<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
"""

# ==================== FAYL O'QISH (MAMMOTH + LaTeX) ====================
def extract_docx_with_math(file_bytes):
    """Word faylidan matn + matematik formulalarni LaTeX ko'rinishida chiqarish"""
    try:
        # Mammoth bilan HTML ga aylantirish (formulalarni saqlaydi)
        result = mammoth.convert_to_html(io.BytesIO(file_bytes))
        html = result.value

        # OMML (Word formulasi) → LaTeX o'girishga harakat
        # Mammoth ba'zi formulalarni saqlamaydi, shuning uchun python-docx bilan ham urinamiz
        soup = BeautifulSoup(html, 'html.parser')

        # Rasmlarni base64 ga o'rab qoldirish (ular allaqachon HTMLda data URI sifatida bor)
        text_content = soup.get_text(separator='\n', strip=True)

        # python-docx bilan formulalarni qo'shimcha olish
        doc = Document(io.BytesIO(file_bytes))
        full_text = []
        images = []

        for para in doc.paragraphs:
            para_text = para.text
            # OMML formulalarni qidirish
            for omml in para._element.findall(
                './/{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath'
            ):
                latex = omml_to_latex(omml)
                if latex:
                    para_text += f" ${latex}$ "
            if para_text.strip():
                full_text.append(para_text)

        # Rasmlarni ajratib olish
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    img_data = rel.target_part.blob
                    img_b64 = base64.b64encode(img_data).decode()
                    images.append(img_b64)
                except Exception:
                    pass

        # Agar mammoth dan ko'proq matn olingan bo'lsa, uni ishlatamiz
        final_text = "\n\n".join(full_text) if full_text else text_content

        return {
            "text": final_text,
            "html": html,
            "images": images
        }
    except Exception as e:
        st.error(f"Word faylni o'qishda xatolik: {e}")
        return {"text": "", "html": "", "images": []}


def omml_to_latex(omml_element):
    """OMML (Office Math Markup Language) ni LaTeX ga oddiy o'girish"""
    try:
        ns = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
        latex = ""

        for child in omml_element.iter():
            tag = child.tag.replace(ns, '')

            if tag == 't':  # oddiy matn
                if child.text:
                    latex += child.text
            elif tag == 'frac':  # kasr
                nums = child.findall(f'{ns}num//{ns}t')
                dens = child.findall(f'{ns}den//{ns}t')
                num = ''.join(n.text or '' for n in nums)
                den = ''.join(d.text or '' for d in dens)
                latex += f"\\frac{{{num}}}{{{den}}}"
            elif tag == 'rad':  # ildiz
                degs = child.findall(f'{ns}deg//{ns}t')
                es = child.findall(f'{ns}e//{ns}t')
                deg = ''.join(d.text or '' for d in degs)
                e = ''.join(x.text or '' for x in es)
                if deg:
                    latex += f"\\sqrt[{deg}]{{{e}}}"
                else:
                    latex += f"\\sqrt{{{e}}}"
            elif tag == 'sup':  # daraja
                latex += "^"
            elif tag == 'sub':  # indeks
                latex += "_"

        return latex.strip()
    except Exception:
        return ""


def extract_pdf(file_bytes):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return {"text": text, "html": "", "images": []}
    except Exception as e:
        st.error(f"PDF xatolik: {e}")
        return {"text": "", "html": "", "images": []}


# ==================== AI BILAN SAVOL TAHLILI ====================
def parse_questions_with_ai(text, num_questions=10):
    """Groq AI orqali matndan savollarni JSON formatda ajratib olish"""
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi. Streamlit Secrets'ga qo'shing.")
        return []

    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""Quyidagi matn olimpiada test savollaridan iborat. Undan {num_questions} ta savolni ajratib ol.

MUHIM QOIDALAR:
1. Matematik formulalar LaTeX formatida ($...$ ichida) bo'lsin
2. Har bir savolda 4 ta variant (A, B, C, D) bo'lishi shart
3. To'g'ri javobni aniqla (agar belgilanmagan bo'lsa, yech va o'zing top)
4. JSON formatda qaytar

JSON struktura:
[
  {{
    "number": 1,
    "question": "Savol matni LaTeX bilan",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "A",
    "explanation": "Qisqa yechim"
  }}
]

MATN:
{text[:8000]}

Faqat JSON qaytar, boshqa hech narsa yozma."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )
        content = response.choices[0].message.content.strip()

        # JSON ni ajratib olish
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            import json
            return json.loads(json_match.group())
        return []
    except Exception as e:
        st.error(f"AI tahlil xatosi: {e}")
        return []


def render_with_math(text):
    """Matnni MathJax bilan ko'rsatish"""
    st.markdown(f"<div>{text}</div>{MATHJAX_SCRIPT}", unsafe_allow_html=True)


# ==================== SESSION STATE ====================
for key, default in {
    "questions": [], "current_q": 0, "answers": {},
    "started": False, "finished": False, "name": "", "surname": "",
    "duration": 90, "start_time": None, "uploaded_files": []
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name = st.text_input("Ism", st.session_state.name)
    st.session_state.surname = st.text_input("Familiya", st.session_state.surname)
    st.session_state.duration = st.number_input(
        "⏱ Test vaqti (daqiqa)", 10, 300, st.session_state.duration
    )

    st.markdown("---")
    st.markdown("### 📁 Test fayllari")
    uploaded = st.file_uploader(
        "Fayl yuklang",
        type=["docx", "pdf"],
        accept_multiple_files=True,
        help="Word (.docx) yoki PDF fayl yuklang. Matematik formulalar avtomatik aniqlanadi."
    )
    if uploaded:
        st.session_state.uploaded_files = uploaded
        for f in uploaded:
            st.success(f"✅ {f.name}")

    if st.session_state.started and not st.session_state.finished:
        if st.button("⛔ Testni to'xtatish"):
            st.session_state.finished = True
            st.rerun()


# ==================== ASOSIY SAHIFA ====================
st.title("🏆 OlimpTest")
st.markdown("### Olimpiada Mashq Platformasi")

# --- TEST BOSHLANMAGAN ---
if not st.session_state.started:
    st.markdown("""
    <div class="question-box">
    <h3>📋 Qo'llanma</h3>
    <ul>
        <li>Word (.docx) yoki PDF testni yuklang</li>
        <li>Ism-familiyangizni kiriting</li>
        <li>"Testni boshlash" tugmasini bosing</li>
        <li>Matematik formulalar va rasmlar avtomatik ko'rinadi</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.uploaded_files and st.session_state.name:
        if st.button("🚀 Testni boshlash", type="primary", use_container_width=True):
            with st.spinner("📖 Fayl o'qilmoqda va savollar tahlil qilinmoqda..."):
                all_text = ""
                all_images = []
                for f in st.session_state.uploaded_files:
                    file_bytes = f.read()
                    if f.name.endswith(".docx"):
                        data = extract_docx_with_math(file_bytes)
                    else:
                        data = extract_pdf(file_bytes)
                    all_text += data["text"] + "\n\n"
                    all_images.extend(data["images"])

                if not all_text.strip():
                    st.error("❌ Fayldan matn olinmadi")
                else:
                    questions = parse_questions_with_ai(all_text, 10)
                    if questions:
                        st.session_state.questions = questions
                        st.session_state.images = all_images
                        st.session_state.started = True
                        import time
                        st.session_state.start_time = time.time()
                        st.rerun()
                    else:
                        st.error("❌ Savollar tahlil qilinmadi")
    else:
        st.info("⬅️ Iltimos, fayl yuklang va ism kiriting")

# --- TEST DAVOM ETMOQDA ---
elif not st.session_state.finished:
    import time
    elapsed = time.time() - st.session_state.start_time
    remaining = max(0, st.session_state.duration * 60 - elapsed)

    if remaining <= 0:
        st.session_state.finished = True
        st.rerun()

    mins, secs = divmod(int(remaining), 60)
    col1, col2 = st.columns([3, 1])

    with col2:
        st.markdown(
            f'<div class="timer-box">⏱ {mins:02d}:{secs:02d}</div>',
            unsafe_allow_html=True
        )
        st.metric("Javob berilgan", f"{len(st.session_state.answers)} / {len(st.session_state.questions)}")

    with col1:
        st.markdown(f"## 📝 {st.session_state.name} {st.session_state.surname}")

    q_idx = st.session_state.current_q
    total = len(st.session_state.questions)
    q = st.session_state.questions[q_idx]

    st.progress((q_idx + 1) / total)
    st.markdown(f"### Savol {q_idx + 1} / {total}")

    # Savol matni (MathJax bilan)
    question_html = f"""
    <div class="question-box">
        <p style="font-size: 20px; color: #FFFFFF;">
            <b>{q['number']}.</b> {q['question']}
        </p>
    </div>
    {MATHJAX_SCRIPT}
    """
    st.markdown(question_html, unsafe_allow_html=True)

    # Variantlar
    options = q.get("options", {})
    selected = st.radio(
        "Javobingiz:",
        list(options.keys()),
        format_func=lambda x: f"{x}) {options[x]}",
        key=f"q_{q_idx}",
        index=None,
    )

    if selected:
        st.session_state.answers[q_idx] = selected

    # Variantlardagi formulalarni render qilish uchun MathJax qayta yuklaymiz
    st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    # Navigatsiya
    nav1, nav2, nav3 = st.columns([1, 1, 1])
    with nav1:
        if q_idx > 0 and st.button("⬅️ Oldingi"):
            st.session_state.current_q -= 1
            st.rerun()
    with nav2:
        if q_idx < total - 1 and st.button("Keyingi ➡️"):
            st.session_state.current_q += 1
            st.rerun()
    with nav3:
        if st.button("✅ Yakunlash"):
            st.session_state.finished = True
            st.rerun()

    # Savollar paneli
    st.markdown("---")
    st.markdown("**Savollar:**")
    cols = st.columns(min(total, 10))
    for i in range(total):
        with cols[i % 10]:
            label = f"{'✓' if i in st.session_state.answers else ''}{i+1}"
            if st.button(label, key=f"nav_{i}"):
                st.session_state.current_q = i
                st.rerun()

# --- NATIJA ---
else:
    st.markdown("## 🎉 Test yakunlandi!")
    correct = 0
    for i, q in enumerate(st.session_state.questions):
        user_ans = st.session_state.answers.get(i)
        if user_ans == q.get("correct"):
            correct += 1

    total = len(st.session_state.questions)
    pct = (correct / total * 100) if total else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("To'g'ri", f"{correct}/{total}")
    col2.metric("Foiz", f"{pct:.1f}%")
    col3.metric("Baho", "5" if pct >= 85 else "4" if pct >= 70 else "3" if pct >= 50 else "2")

    st.markdown("### 📋 Batafsil natijalar")
    for i, q in enumerate(st.session_state.questions):
        user_ans = st.session_state.answers.get(i, "—")
        correct_ans = q.get("correct", "?")
        is_correct = user_ans == correct_ans

        with st.expander(f"{'✅' if is_correct else '❌'} Savol {i+1}"):
            st.markdown(f"**Savol:** {q['question']}", unsafe_allow_html=True)
            for k, v in q.get("options", {}).items():
                marker = "✅" if k == correct_ans else ("❌" if k == user_ans else "  ")
                st.markdown(f"{marker} **{k})** {v}")
            st.info(f"💡 {q.get('explanation', '')}")
            st.markdown(MATHJAX_SCRIPT, unsafe_allow_html=True)

    if st.button("🔄 Yangi test"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
