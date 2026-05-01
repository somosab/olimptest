"""
OlimpTest - AI yordamida olimpiada mashq platformasi
Groq + Tesseract OCR (matematik formulalar va rasmlar uchun)
"""
import streamlit as st
import os
import io
import json
import time
import base64
import re
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any

# === Tashqi kutubxonalar ===
try:
    from groq import Groq
except ImportError:
    st.error("Groq kutubxonasi o'rnatilmagan. `pip install groq` ni bajaring.")
    st.stop()

from pypdf import PdfReader
from docx import Document
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np

# OCR uchun - ixtiyoriy importlar
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# ==========================================================================
# KONFIGURATSIYA
# ==========================================================================

st.set_page_config(
    page_title="OlimpTest - Olimpiada Mashq Platformasi",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Groq modellari
TEXT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# OCR til konfiguratsiyasi (Tesseract til kodlari)
# equ = matematik tenglamalar, uzb = o'zbek, uzb_cyrl = o'zbek kirill
OCR_LANGS = "uzb+uzb_cyrl+rus+eng+equ"
OCR_LANGS_FALLBACK = "rus+eng"

MAX_FILE_SIZE_MB = 25
MAX_PDF_PAGES = 30


# ==========================================================================
# CSS - Premium dark-gold theme
# ==========================================================================

CUSTOM_CSS = """
<style>
    .stApp {
        background: linear-gradient(135deg, #0a0a0f 0%, #15151f 100%);
    }
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 50%, #f59e0b 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-align: center;
        margin: 1rem 0;
        letter-spacing: -0.02em;
    }
    .subtitle {
        text-align: center;
        color: #94a3b8;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    .stat-card {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.08) 0%, rgba(251, 191, 36, 0.04) 100%);
        border: 1px solid rgba(245, 158, 11, 0.2);
        border-radius: 16px;
        padding: 1.5rem;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .stat-value {
        font-size: 2.5rem;
        font-weight: 800;
        color: #fbbf24;
        margin: 0;
    }
    .stat-label {
        color: #94a3b8;
        font-size: 0.85rem;
        margin-top: 0.25rem;
    }
    .question-card {
        background: rgba(30, 30, 45, 0.6);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 16px;
        padding: 2rem;
        margin: 1rem 0;
        backdrop-filter: blur(10px);
    }
    .timer-box {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.1), rgba(251, 191, 36, 0.05));
        border: 2px solid rgba(245, 158, 11, 0.4);
        border-radius: 12px;
        padding: 0.75rem 1.5rem;
        text-align: center;
        font-size: 1.5rem;
        font-weight: 700;
        color: #fbbf24;
        font-family: 'Courier New', monospace;
    }
    .timer-warning {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(220, 38, 38, 0.1));
        border-color: rgba(239, 68, 68, 0.6);
        color: #ef4444;
        animation: pulse 1s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
    .correct-answer {
        background: rgba(34, 197, 94, 0.1);
        border-left: 4px solid #22c55e;
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
    .wrong-answer {
        background: rgba(239, 68, 68, 0.1);
        border-left: 4px solid #ef4444;
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
    .stButton > button {
        background: linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%);
        color: #0a0a0f;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.5rem;
        font-weight: 700;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 25px rgba(245, 158, 11, 0.3);
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a0a0f 0%, #15151f 100%);
        border-right: 1px solid rgba(245, 158, 11, 0.15);
    }
    .file-item {
        background: rgba(245, 158, 11, 0.05);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 10px;
        padding: 0.75rem;
        margin: 0.5rem 0;
    }
    .ocr-info {
        background: rgba(59, 130, 246, 0.08);
        border-left: 3px solid #3b82f6;
        padding: 0.5rem 1rem;
        border-radius: 6px;
        font-size: 0.85rem;
        color: #93c5fd;
        margin: 0.5rem 0;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ==========================================================================
# SESSIYA STATE
# ==========================================================================

def init_session_state():
    defaults = {
        "first_name": "",
        "last_name": "",
        "duration_min": 30,
        "uploaded_files": [],
        "active_file_idx": None,
        "extracted_questions": None,
        "test_started": False,
        "test_finished": False,
        "test_start_time": None,
        "user_answers": {},
        "current_question_idx": 0,
        "test_history": [],
        "extraction_in_progress": False,
        "ocr_method": "auto",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ==========================================================================
# GROQ KLIENT
# ==========================================================================

def get_groq_client() -> Optional[Groq]:
    """Streamlit secrets, env, yoki manual input dan API key oladi."""
    api_key = ""
    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        pass
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        api_key = st.session_state.get("manual_api_key", "")
    if not api_key:
        return None
    try:
        return Groq(api_key=api_key)
    except Exception as e:
        st.error(f"Groq klient xatosi: {e}")
        return None


# ==========================================================================
# OCR — TESSERACT (matematik formulalar, qo'lyozma, rasmlar uchun)
# ==========================================================================

def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    """Rasmni OCR uchun sifatini oshirish: grayscale, kontrast, denoise, threshold."""
    try:
        # RGB ga o'tkazish
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Hajmni oshirish (kichik rasmlarda OCR yomon ishlaydi)
        w, h = image.size
        if max(w, h) < 1500:
            scale = 1500 / max(w, h)
            new_size = (int(w * scale), int(h * scale))
            image = image.resize(new_size, Image.LANCZOS)

        # OpenCV bilan murakkab preprocessing
        if CV2_AVAILABLE:
            img_array = np.array(image)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

            # Denoise
            denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

            # Adaptive threshold (matematik formulalar uchun yaxshi)
            thresh = cv2.adaptiveThreshold(
                denoised, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31, 15
            )

            return Image.fromarray(thresh)
        else:
            # Faqat PIL bilan
            gray = image.convert("L")
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(2.0)
            sharpened = enhanced.filter(ImageFilter.SHARPEN)
            return sharpened
    except Exception as e:
        st.warning(f"Preprocessing xatosi (asl rasm ishlatiladi): {e}")
        return image


def ocr_image_tesseract(image: Image.Image, lang: str = OCR_LANGS) -> str:
    """Rasmdan Tesseract OCR yordamida matn ajratib olish."""
    if not TESSERACT_AVAILABLE:
        return ""

    try:
        processed = preprocess_image_for_ocr(image)

        # Birinchi urinish — to'liq tillar bilan
        try:
            text = pytesseract.image_to_string(
                processed,
                lang=lang,
                config="--oem 3 --psm 6"  # PSM 6 = uniform block of text
            )
            if text.strip():
                return text.strip()
        except pytesseract.TesseractError:
            pass

        # Fallback — kamroq tillar
        try:
            text = pytesseract.image_to_string(
                processed,
                lang=OCR_LANGS_FALLBACK,
                config="--oem 3 --psm 6"
            )
            return text.strip()
        except pytesseract.TesseractError:
            pass

        # Oxirgi fallback — faqat ingliz
        text = pytesseract.image_to_string(processed, lang="eng", config="--oem 3 --psm 6")
        return text.strip()
    except Exception as e:
        return f"[OCR xatosi: {e}]"


def ocr_image_with_layout(image: Image.Image, lang: str = OCR_LANGS) -> str:
    """Maxsus PSM rejimlarini sinash — eng yaxshi natijani tanlash."""
    if not TESSERACT_AVAILABLE:
        return ""

    processed = preprocess_image_for_ocr(image)
    results = []

    # Turli PSM rejimlari (matematik test uchun yaxshilari)
    psm_modes = [6, 3, 4, 11]  # 6=block, 3=auto, 4=column, 11=sparse

    for psm in psm_modes:
        try:
            text = pytesseract.image_to_string(
                processed,
                lang=lang,
                config=f"--oem 3 --psm {psm}"
            )
            if text and text.strip():
                results.append((len(text.strip()), text.strip()))
        except Exception:
            continue

    if not results:
        return ocr_image_tesseract(image, lang)

    # Eng uzun natijani qaytarish (odatda eng to'liq)
    results.sort(reverse=True)
    return results[0][1]


# ==========================================================================
# FAYL O'QUVCHILARI
# ==========================================================================

def read_pdf_text(file_bytes: bytes) -> str:
    """PDF dan matnni oddiy yo'l bilan ajratish."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                text += page.extract_text() + "\n\n"
            except Exception:
                continue
        return text.strip()
    except Exception as e:
        return f"[PDF o'qish xatosi: {e}]"


def read_pdf_with_ocr(file_bytes: bytes, status_placeholder=None) -> str:
    """PDF ni rasm sifatida o'qib, har bir sahifaga OCR qilish."""
    if not PDF2IMAGE_AVAILABLE or not TESSERACT_AVAILABLE:
        return read_pdf_text(file_bytes)

    try:
        if status_placeholder:
            status_placeholder.info("📄 PDF sahifalarini rasmga aylantirish...")

        images = convert_from_bytes(file_bytes, dpi=250, fmt="png")
        images = images[:MAX_PDF_PAGES]

        all_text = []
        for i, img in enumerate(images, 1):
            if status_placeholder:
                status_placeholder.info(f"🔍 OCR: sahifa {i}/{len(images)} (matematik formulalar bilan)...")
            page_text = ocr_image_with_layout(img)
            if page_text:
                all_text.append(f"--- Sahifa {i} ---\n{page_text}")

        return "\n\n".join(all_text)
    except Exception as e:
        if status_placeholder:
            status_placeholder.warning(f"OCR xatosi, oddiy o'qishga o'tildi: {e}")
        return read_pdf_text(file_bytes)


def read_docx(file_bytes: bytes) -> str:
    """DOCX dan matn va jadvallarni ajratib olish."""
    try:
        doc = Document(io.BytesIO(file_bytes))
        parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip():
                    parts.append(row_text)
        return "\n".join(parts)
    except Exception as e:
        return f"[DOCX xatosi: {e}]"


def read_image(file_bytes: bytes, status_placeholder=None) -> str:
    """Rasmdan OCR yordamida matn ajratish."""
    try:
        image = Image.open(io.BytesIO(file_bytes))

        if status_placeholder:
            status_placeholder.info("🔍 Rasmdan OCR qilinmoqda (matematik formulalar bilan)...")

        if TESSERACT_AVAILABLE:
            return ocr_image_with_layout(image)
        else:
            return "[Tesseract OCR o'rnatilmagan. Rasmni o'qish uchun tesseract kerak.]"
    except Exception as e:
        return f"[Rasm xatosi: {e}]"


def read_text_file(file_bytes: bytes) -> str:
    """TXT/MD/CSV fayllarini o'qish."""
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def extract_file_content(file_data: dict, status_placeholder=None) -> Tuple[str, str]:
    """
    Fayl turi bo'yicha matnni ajratib olish.
    Return: (extracted_text, method_used)
    """
    name = file_data["name"].lower()
    file_bytes = file_data["bytes"]

    if name.endswith(".pdf"):
        # 1. Avval oddiy matn (tezroq)
        text = read_pdf_text(file_bytes)
        # Agar matn yetarli bo'lmasa (skanerlangan PDF) — OCR
        if len(text.strip()) < 100 or text.startswith("[PDF"):
            ocr_text = read_pdf_with_ocr(file_bytes, status_placeholder)
            return ocr_text, "PDF + OCR (skanerlangan/matematik)"
        # Aralash: agar matn bor bo'lsa-yu, lekin formulalar bo'lishi mumkin — OCR ham qo'shamiz
        if any(kw in text.lower() for kw in ["формул", "rasm", "image", "figure"]) and PDF2IMAGE_AVAILABLE:
            ocr_text = read_pdf_with_ocr(file_bytes, status_placeholder)
            combined = f"=== Matn qatlami ===\n{text}\n\n=== OCR qatlami (formulalar) ===\n{ocr_text}"
            return combined, "PDF (matn + OCR aralash)"
        return text, "PDF (matn qatlami)"

    elif name.endswith((".docx", ".doc")):
        return read_docx(file_bytes), "Word hujjat"

    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff")):
        return read_image(file_bytes, status_placeholder), "Rasm + OCR"

    elif name.endswith((".txt", ".md", ".csv")):
        return read_text_file(file_bytes), "Matn fayl"

    else:
        try:
            return read_text_file(file_bytes), "Noma'lum (matn sifatida)"
        except Exception as e:
            return f"[Qo'llab-quvvatlanmaydigan fayl: {e}]", "Xato"


# ==========================================================================
# AI - SAVOLLARNI AJRATIB OLISH VA YECHISH
# ==========================================================================

EXTRACTION_SYSTEM_PROMPT = """Sen test fayllarini tahlil qiluvchi mutaxassis AI siz. Sening vazifang:

1. Matndan har bir savolni aniq ajratib olish (raqami, matni, variantlari)
2. Matematik formulalar, ifodalar, tenglamalarni to'g'ri talqin qilish
3. Agar javoblar kalit (answer key) berilgan bo'lsa — uni ishlatish
4. Agar javoblar berilmagan bo'lsa — O'ZING TO'G'RI JAVOBNI HISOBLAB CHIQARISH
   (sen kuchli AI siz, har qanday matematika, fizika, kimyo, biologiya, tarix savolini yecha olasin)

MUHIM QOIDALAR:
- OCR natijasida matn buzilgan bo'lishi mumkin — kontekstdan tushunib, to'g'ri talqin qil
- Matematik belgilar (², ³, √, ∫, π) noto'g'ri o'qilgan bo'lsa — formulani tikla
- Faqat va faqat JSON formatda javob qaytar, boshqa hech narsa yozma
- Variantlar formati: "A) javob matni", "B) ...", va h.k.
- correct_answer da faqat harf bo'lishi kerak: "A", "B", "C", "D" yoki "E"
- Agar variantlar yo'q bo'lsa, correct_answer da to'liq javob bo'ladi

JSON struktura:
{
  "title": "Test sarlavhasi",
  "subject": "Fan nomi (matematika, fizika...)",
  "questions": [
    {
      "number": 1,
      "question": "Savol matni (formulalar bilan)",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "correct_answer": "B",
      "explanation": "Qisqa yechim/tushuntirish"
    }
  ]
}"""


def extract_questions_from_text(client: Groq, text: str, status_placeholder=None) -> Optional[Dict]:
    """Matndan savollarni AI yordamida ajratib olish."""
    if not text or len(text.strip()) < 20:
        return None

    # Juda uzun matn bo'lsa qisqartirish (Groq token limiti)
    MAX_CHARS = 25000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n[matn qisqartirildi]"

    if status_placeholder:
        status_placeholder.info("🧠 AI test savollarini tahlil qilmoqda...")

    user_prompt = f"""Quyidagi test matnini tahlil qil va JSON formatida qaytar:

{text}

DIQQAT: Faqat JSON qaytar, hech qanday qo'shimcha matn yozma. Agar javoblar yo'q bo'lsa — har bir savolni o'zing yech va correct_answer ga to'g'ri harfni qo'y."""

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = json.loads(content)

        # Validatsiya
        if "questions" not in data or not isinstance(data["questions"], list):
            return None
        if len(data["questions"]) == 0:
            return None

        # Har bir savolda zarur maydonlar borligini tekshirish
        clean_questions = []
        for i, q in enumerate(data["questions"], 1):
            if not isinstance(q, dict):
                continue
            clean_q = {
                "number": q.get("number", i),
                "question": str(q.get("question", "")).strip(),
                "options": q.get("options", []) if isinstance(q.get("options"), list) else [],
                "correct_answer": str(q.get("correct_answer", "")).strip().upper()[:1] or "A",
                "explanation": str(q.get("explanation", "")).strip(),
            }
            if clean_q["question"]:
                clean_questions.append(clean_q)

        if not clean_questions:
            return None

        data["questions"] = clean_questions
        if "title" not in data:
            data["title"] = "Test"
        return data

    except json.JSONDecodeError as e:
        st.error(f"AI javobini JSON ga o'tkazib bo'lmadi: {e}")
        return None
    except Exception as e:
        st.error(f"AI tahlil xatosi: {e}")
        return None


def solve_single_question(client: Groq, question: Dict) -> str:
    """Bitta savolni AI yordamida yechib, to'g'ri javobni qaytarish."""
    options_text = "\n".join(question.get("options", []))
    prompt = f"""Quyidagi savolni yech va faqat to'g'ri javob harfini qaytar (A, B, C, D yoki E):

Savol: {question['question']}

Variantlar:
{options_text}

Faqat bitta harf yoz, boshqa hech narsa yozma."""

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=10,
        )
        answer = response.choices[0].message.content.strip().upper()
        # Faqat harfni ajratib olish
        match = re.search(r"[A-E]", answer)
        return match.group(0) if match else "A"
    except Exception:
        return "A"


def explain_question(client: Groq, question: Dict, user_answer: str) -> str:
    """Savol yechimini batafsil tushuntirish."""
    options_text = "\n".join(question.get("options", []))
    prompt = f"""Savol: {question['question']}

Variantlar:
{options_text}

To'g'ri javob: {question['correct_answer']}
Foydalanuvchi javobi: {user_answer or '(javob bermagan)'}

Bu savolni qisqa va tushunarli qilib o'zbek tilida tushuntir. Yechim bosqichlarini ko'rsat."""

    try:
        response = client.chat.completions.create(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Tushuntirish olinmadi: {e}"


# ==========================================================================
# SIDEBAR
# ==========================================================================

def render_sidebar():
    with st.sidebar:
        st.markdown("### 🏆 OlimpTest")
        st.caption("Olimpiada mashq platformasi")
        st.divider()

        # API Key holati
        client = get_groq_client()
        if client:
            st.success("✅ AI ulangan")
        else:
            st.warning("⚠️ Groq API kalit kerak")
            with st.expander("🔑 API kalit kiritish"):
                manual_key = st.text_input(
                    "Groq API Key",
                    type="password",
                    key="manual_api_key_input",
                    help="https://console.groq.com/keys dan oling"
                )
                if manual_key:
                    st.session_state["manual_api_key"] = manual_key
                    st.rerun()

        # OCR holati
        if TESSERACT_AVAILABLE:
            st.success("✅ OCR (Tesseract) faol")
        else:
            st.error("❌ Tesseract OCR yo'q")

        st.divider()

        # Foydalanuvchi
        st.markdown("#### 👤 Foydalanuvchi")
        st.session_state.first_name = st.text_input(
            "Ism", value=st.session_state.first_name, placeholder="Ali"
        )
        st.session_state.last_name = st.text_input(
            "Familiya", value=st.session_state.last_name, placeholder="Valiyev"
        )

        st.session_state.duration_min = st.number_input(
            "⏱️ Test vaqti (daqiqa)",
            min_value=1, max_value=300,
            value=st.session_state.duration_min,
        )

        st.divider()

        # Fayl yuklash
        st.markdown("#### 📁 Test fayllari")

        uploaded = st.file_uploader(
            "Fayl yuklang",
            type=["pdf", "docx", "doc", "txt", "md", "csv", "png", "jpg", "jpeg", "webp", "bmp", "tiff"],
            accept_multiple_files=False,
            help=f"Maks: {MAX_FILE_SIZE_MB}MB. Matematik formulalar va rasmlar OCR bilan o'qiladi.",
        )

        if uploaded is not None:
            file_bytes = uploaded.read()
            file_size_mb = len(file_bytes) / (1024 * 1024)

            if file_size_mb > MAX_FILE_SIZE_MB:
                st.error(f"Fayl juda katta: {file_size_mb:.1f}MB")
            else:
                file_hash = hashlib.md5(file_bytes).hexdigest()
                existing_hashes = [f.get("hash") for f in st.session_state.uploaded_files]
                if file_hash not in existing_hashes:
                    st.session_state.uploaded_files.append({
                        "name": uploaded.name,
                        "bytes": file_bytes,
                        "size": len(file_bytes),
                        "hash": file_hash,
                        "uploaded_at": datetime.now().isoformat(),
                    })
                    st.success(f"✅ {uploaded.name} yuklandi")
                    st.rerun()

        # Yuklangan fayllar ro'yxati
        if st.session_state.uploaded_files:
            st.markdown("**Yuklangan fayllar:**")
            for idx, f in enumerate(st.session_state.uploaded_files):
                col1, col2 = st.columns([4, 1])
                with col1:
                    is_active = st.session_state.active_file_idx == idx
                    label = f"{'🟢' if is_active else '📄'} {f['name'][:25]}"
                    if st.button(label, key=f"file_{idx}", use_container_width=True):
                        st.session_state.active_file_idx = idx
                        st.session_state.extracted_questions = None
                        st.rerun()
                with col2:
                    if st.button("🗑", key=f"del_{idx}"):
                        st.session_state.uploaded_files.pop(idx)
                        if st.session_state.active_file_idx == idx:
                            st.session_state.active_file_idx = None
                        st.rerun()

        st.divider()

        # Test boshlash tugmasi
        can_start = (
            st.session_state.first_name and
            st.session_state.last_name and
            st.session_state.active_file_idx is not None and
            client is not None and
            not st.session_state.test_started
        )

        if st.session_state.test_started and not st.session_state.test_finished:
            if st.button("⛔ Testni to'xtatish", use_container_width=True, type="secondary"):
                st.session_state.test_finished = True
                st.rerun()
        else:
            if st.button(
                "🚀 Testni boshlash",
                use_container_width=True,
                disabled=not can_start,
                type="primary",
            ):
                start_test()


# ==========================================================================
# TEST BOSHLASH
# ==========================================================================

def start_test():
    """Test boshlash: faylni o'qish, AI tahlil, savollar tayyorlash."""
    client = get_groq_client()
    if not client:
        st.error("Groq API kalit yo'q")
        return

    file_data = st.session_state.uploaded_files[st.session_state.active_file_idx]

    with st.spinner("Fayl tahlil qilinmoqda..."):
        status = st.empty()

        # 1-bosqich: Fayldan matn ajratib olish
        status.info("📖 Fayl o'qilmoqda...")
        text, method = extract_file_content(file_data, status)

        if not text or len(text.strip()) < 20:
            status.error("Fayldan matn ajratib bo'lmadi. Boshqa fayl yuklang.")
            return

        st.markdown(f'<div class="ocr-info">📋 O\'qish usuli: <b>{method}</b> · {len(text)} ta belgi</div>',
                    unsafe_allow_html=True)

        # 2-bosqich: AI bilan savollarni ajratib olish
        result = extract_questions_from_text(client, text, status)

        if not result or not result.get("questions"):
            status.error("AI savollarni ajratib ololmadi. Fayl formati noto'g'ri bo'lishi mumkin.")
            return

        # 3-bosqich: Javoblari yo'q savollarni AI bilan yechish
        questions = result["questions"]
        unanswered = [q for q in questions if not q.get("correct_answer") or q["correct_answer"] not in "ABCDE"]

        if unanswered:
            status.info(f"🧠 AI {len(unanswered)} ta savolni yechmoqda...")
            for q in unanswered:
                if q.get("options"):
                    q["correct_answer"] = solve_single_question(client, q)

        st.session_state.extracted_questions = result
        st.session_state.test_started = True
        st.session_state.test_finished = False
        st.session_state.test_start_time = time.time()
        st.session_state.user_answers = {}
        st.session_state.current_question_idx = 0
        status.empty()
        st.rerun()


# ==========================================================================
# TEST INTERFEYSI
# ==========================================================================

def render_test():
    questions = st.session_state.extracted_questions["questions"]
    title = st.session_state.extracted_questions.get("title", "Test")
    total = len(questions)

    elapsed = time.time() - st.session_state.test_start_time
    remaining = max(0, st.session_state.duration_min * 60 - elapsed)

    if remaining <= 0:
        st.session_state.test_finished = True
        st.rerun()

    mins = int(remaining // 60)
    secs = int(remaining % 60)
    timer_class = "timer-box timer-warning" if remaining < 60 else "timer-box"

    # Header
    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        st.markdown(f"### 📝 {title}")
        st.caption(f"{st.session_state.first_name} {st.session_state.last_name}")
    with col2:
        st.markdown(f'<div class="{timer_class}">⏱️ {mins:02d}:{secs:02d}</div>',
                    unsafe_allow_html=True)
    with col3:
        answered = len(st.session_state.user_answers)
        st.metric("Javob berilgan", f"{answered} / {total}")

    progress = (st.session_state.current_question_idx + 1) / total
    st.progress(progress)

    # Joriy savol
    idx = st.session_state.current_question_idx
    q = questions[idx]

    st.markdown(f"#### Savol {idx + 1} / {total}")
    st.markdown(f'<div class="question-card">{q["number"]}. {q["question"]}</div>',
                unsafe_allow_html=True)

    # Variantlar
    if q.get("options"):
        current_ans = st.session_state.user_answers.get(q["number"], "")
        option_letters = [opt[:1] for opt in q["options"] if opt]

        # Default index
        default_idx = 0
        if current_ans:
            for i, opt in enumerate(q["options"]):
                if opt.startswith(current_ans):
                    default_idx = i
                    break

        chosen = st.radio(
            "Javobingiz:",
            options=q["options"],
            index=default_idx if current_ans else None,
            key=f"q_{q['number']}",
        )
        if chosen:
            letter = chosen[:1].upper()
            st.session_state.user_answers[q["number"]] = letter
    else:
        text_ans = st.text_input(
            "Javobingiz:",
            value=st.session_state.user_answers.get(q["number"], ""),
            key=f"qt_{q['number']}",
        )
        if text_ans:
            st.session_state.user_answers[q["number"]] = text_ans

    # Navigatsiya
    st.divider()
    nav_cols = st.columns([1, 1, 4, 1, 1])
    with nav_cols[0]:
        if st.button("⬅️", disabled=(idx == 0)):
            st.session_state.current_question_idx -= 1
            st.rerun()
    with nav_cols[1]:
        if st.button("➡️", disabled=(idx == total - 1)):
            st.session_state.current_question_idx += 1
            st.rerun()
    with nav_cols[3]:
        if st.button("✅ Yakunlash", type="primary"):
            st.session_state.test_finished = True
            st.rerun()

    # Savol raqamlariga o'tish
    st.markdown("**Savollar:**")
    cols = st.columns(min(10, total))
    for i, qq in enumerate(questions):
        col = cols[i % len(cols)]
        with col:
            answered = qq["number"] in st.session_state.user_answers
            label = f"{'✓' if answered else ''}{qq['number']}"
            btn_type = "primary" if i == idx else "secondary"
            if st.button(label, key=f"nav_{i}", type=btn_type, use_container_width=True):
                st.session_state.current_question_idx = i
                st.rerun()

    # Auto-refresh timer
    time.sleep(1)
    st.rerun()


# ==========================================================================
# NATIJA
# ==========================================================================

def render_results():
    questions = st.session_state.extracted_questions["questions"]
    title = st.session_state.extracted_questions.get("title", "Test")
    answers = st.session_state.user_answers

    correct = 0
    wrong = 0
    unanswered = 0
    details = []

    for q in questions:
        user_ans = answers.get(q["number"], "").strip().upper()
        correct_ans = q["correct_answer"].strip().upper()
        if not user_ans:
            unanswered += 1
            status = "unanswered"
        elif user_ans[:1] == correct_ans[:1]:
            correct += 1
            status = "correct"
        else:
            wrong += 1
            status = "wrong"
        details.append({"q": q, "user": user_ans, "status": status})

    total = len(questions)
    percent = round((correct / total) * 100) if total else 0

    elapsed = int(time.time() - st.session_state.test_start_time)
    elapsed_min = elapsed // 60
    elapsed_sec = elapsed % 60

    # Sarlavha
    st.markdown('<h1 class="main-title">🏆 Test Yakunlandi</h1>', unsafe_allow_html=True)
    st.markdown(f'<p class="subtitle">{st.session_state.first_name} {st.session_state.last_name} · {title}</p>',
                unsafe_allow_html=True)

    # Statistika
    cols = st.columns(4)
    stats = [
        ("To'g'ri", correct, "#22c55e"),
        ("Noto'g'ri", wrong, "#ef4444"),
        ("Javobsiz", unanswered, "#94a3b8"),
        ("Natija", f"{percent}%", "#fbbf24"),
    ]
    for col, (label, value, color) in zip(cols, stats):
        with col:
            st.markdown(f'''
                <div class="stat-card">
                    <p class="stat-value" style="color: {color}">{value}</p>
                    <p class="stat-label">{label}</p>
                </div>
            ''', unsafe_allow_html=True)

    st.markdown(f"⏱️ Sarflangan vaqt: **{elapsed_min}:{elapsed_sec:02d}**")
    st.divider()

    # Tafsilotlar
    st.markdown("### 📋 Savol-javoblar")

    for d in details:
        q = d["q"]
        status = d["status"]
        user_ans = d["user"] or "—"

        if status == "correct":
            css_class = "correct-answer"
            icon = "✅"
        elif status == "wrong":
            css_class = "wrong-answer"
            icon = "❌"
        else:
            css_class = "wrong-answer"
            icon = "⚪"

        with st.expander(f"{icon} Savol {q['number']}"):
            st.markdown(f"**{q['question']}**")
            if q.get("options"):
                for opt in q["options"]:
                    st.markdown(f"- {opt}")
            st.markdown(f'<div class="{css_class}">'
                        f'Sizning javob: <b>{user_ans}</b> · '
                        f'To\'g\'ri javob: <b>{q["correct_answer"]}</b>'
                        f'</div>', unsafe_allow_html=True)
            if q.get("explanation"):
                st.info(f"💡 {q['explanation']}")

    st.divider()

    # Eksport va qayta boshlash
    col1, col2, col3 = st.columns(3)
    with col1:
        export_data = {
            "user": f"{st.session_state.first_name} {st.session_state.last_name}",
            "test": title,
            "date": datetime.now().isoformat(),
            "duration_seconds": elapsed,
            "score": {"correct": correct, "wrong": wrong, "unanswered": unanswered, "percent": percent},
            "answers": [
                {"number": d["q"]["number"], "user": d["user"], "correct": d["q"]["correct_answer"], "status": d["status"]}
                for d in details
            ],
        }
        st.download_button(
            "📥 JSON natija",
            data=json.dumps(export_data, ensure_ascii=False, indent=2),
            file_name=f"olimptest_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        txt_report = f"""OlimpTest Natijasi
=====================
O'quvchi: {st.session_state.first_name} {st.session_state.last_name}
Test: {title}
Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Vaqt: {elapsed_min}:{elapsed_sec:02d}

NATIJA: {correct}/{total} ({percent}%)
To'g'ri: {correct}
Noto'g'ri: {wrong}
Javobsiz: {unanswered}
"""
        st.download_button(
            "📄 TXT hisobot",
            data=txt_report,
            file_name=f"olimptest_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with col3:
        if st.button("🔄 Yangi test", use_container_width=True, type="primary"):
            st.session_state.test_started = False
            st.session_state.test_finished = False
            st.session_state.extracted_questions = None
            st.session_state.user_answers = {}
            st.session_state.current_question_idx = 0
            st.rerun()


# ==========================================================================
# WELCOME
# ==========================================================================

def render_welcome():
    st.markdown('<h1 class="main-title">🏆 OlimpTest</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">AI yordamida olimpiada mashq platformasi · Matematik formulalar va rasmlarni o\'qiy oladi</p>',
                unsafe_allow_html=True)

    st.markdown("### 🚀 Qanday ishlatish")
    cols = st.columns(4)
    steps = [
        ("1️⃣", "Ism kiritish", "Sidebar'dan ism va familiyangizni yozing"),
        ("2️⃣", "Fayl yuklang", "Test faylini (PDF, Word, rasm) yuklang"),
        ("3️⃣", "Vaqt belgilang", "Test uchun vaqt limitini sozlang"),
        ("4️⃣", "Boshlang", "🚀 Testni boshlash tugmasini bosing"),
    ]
    for col, (icon, title, desc) in zip(cols, steps):
        with col:
            st.markdown(f'''
                <div class="stat-card">
                    <div style="font-size: 2rem">{icon}</div>
                    <div style="font-weight: 700; color: #fbbf24; margin: 0.5rem 0">{title}</div>
                    <div style="font-size: 0.85rem; color: #94a3b8">{desc}</div>
                </div>
            ''', unsafe_allow_html=True)

    st.divider()

    st.markdown("### ✨ Imkoniyatlar")
    feat_cols = st.columns(3)
    features = [
        ("🔍 OCR Texnologiya",
         "Tesseract OCR yordamida rasmlardan, skanerlangan PDF lardan va matematik formulalardan matn ajratib oladi. "
         "O'zbek (lotin/kirill), rus, ingliz tillarini qo'llab-quvvatlaydi."),
        ("🧠 Aqlli AI",
         "Groq Llama 3.3 70B modeli javob kalitsiz testlarni ham o'zi yecha oladi. "
         "Matematika, fizika, kimyo, biologiya — har qanday fanni tushunadi."),
        ("⚡ Tezlik",
         "Sizning olimpiadalarda tezligingizni oshirish uchun maxsus mashq muhiti. "
         "Vaqt sanagich, savol navigatsiyasi va batafsil natijalar."),
    ]
    for col, (title, desc) in zip(feat_cols, features):
        with col:
            st.markdown(f'''
                <div class="question-card">
                    <h4 style="color: #fbbf24">{title}</h4>
                    <p style="color: #cbd5e1; font-size: 0.9rem">{desc}</p>
                </div>
            ''', unsafe_allow_html=True)

    if not get_groq_client():
        st.warning("⚠️ Boshlash uchun sidebar'dan Groq API kalitini kiriting yoki Streamlit Secrets'ga qo'shing.")
        with st.expander("📖 API kalit qanday olinadi?"):
            st.markdown("""
1. https://console.groq.com/keys saytiga kiring (bepul ro'yxatdan o'ting)
2. **Create API Key** tugmasini bosing
3. Hosil bo'lgan kalitni nusxalang
4. **Streamlit Cloud** da: app sozlamalarida **Secrets** bo'limiga `GROQ_API_KEY = "sizning_kalitingiz"` qo'shing
5. Yoki sidebar'dagi inputga vaqtinchalik kiriting
            """)


# ==========================================================================
# MAIN
# ==========================================================================

def main():
    render_sidebar()

    if st.session_state.test_finished and st.session_state.extracted_questions:
        render_results()
    elif st.session_state.test_started and st.session_state.extracted_questions:
        render_test()
    else:
        render_welcome()


if __name__ == "__main__":
    main()
