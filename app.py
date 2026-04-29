"""
OlimpTest — Streamlit dasturi
Olimpiada va testlarga AI yordamida vaqtli mashq qilish platformasi.

Xususiyatlari:
- Foydalanuvchi ism/familya kiritadi
- Sidebar orqali test fayllarini yuklaydi (PDF, DOCX, TXT, rasm)
- Vaqt belgilaydi va testni boshlaydi
- Groq AI (LLaMA 3.3 70B + Vision) faylni o'qiydi, savollarni ajratadi
- Javoblar yo'q bo'lsa AI o'zi yechadi
- Test boshqaruvi: navigatsiya, taymer, javoblarni belgilash
- Test yakunida natija va har bir savol bo'yicha tushuntirish

Ishga tushirish:
    pip install -r requirements.txt
    streamlit run app.py

Muhit o'zgaruvchilari:
    GROQ_API_KEY — Groq API kaliti (https://console.groq.com/keys dan oling)
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from dotenv import load_dotenv
from groq import Groq

# Optional file readers (gracefully handle missing libraries)
try:
    import pypdf  # type: ignore
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    from pdf2image import convert_from_bytes  # type: ignore
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

try:
    import docx  # type: ignore
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from PIL import Image  # type: ignore
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ============================================================================
#                              KONFIGURATSIYA
# ============================================================================

load_dotenv()

APP_TITLE = "OlimpTest — Olimpiada mashq platformasi"
APP_ICON = "🏆"
APP_TAGLINE = "AI yordamida olimpiada va testlarga vaqtli mashq"

# Groq modellari
TEXT_MODEL = "llama-3.3-70b-versatile"   # Strukturali matn tahlili uchun
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"  # Rasm o'qish uchun
FALLBACK_VISION_MODEL = "llama-3.2-90b-vision-preview"

# Saqlash papkasi
DATA_DIR = Path.home() / ".olimptest"
DATA_DIR.mkdir(exist_ok=True)
TESTS_DIR = DATA_DIR / "tests"
TESTS_DIR.mkdir(exist_ok=True)
RESULTS_FILE = DATA_DIR / "results.json"

# Qo'llab-quvvatlanadigan fayl turlari
SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "webp"]


# ============================================================================
#                              MA'LUMOT TURLARI
# ============================================================================

@dataclass
class Question:
    """Bitta test savoli."""
    number: int
    question: str
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Question":
        return cls(
            number=int(data.get("number", 0)),
            question=str(data.get("question", "")),
            options=list(data.get("options", []) or []),
            correct_answer=str(data.get("correct_answer", "")),
            explanation=str(data.get("explanation", "")),
        )


@dataclass
class TestFile:
    """Saqlangan test fayli haqida ma'lumot."""
    id: str
    file_name: str
    size: int
    created_at: float
    file_type: str
    storage_path: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TestFile":
        return cls(**data)


@dataclass
class TestResult:
    """Test yakuni natijasi."""
    id: str
    student_name: str
    test_title: str
    file_name: str
    total_questions: int
    correct: int
    wrong: int
    skipped: int
    percent: float
    duration_used_sec: int
    duration_total_sec: int
    finished_at: float
    questions: list[dict]
    answers: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
#                              FAYL O'QISH
# ============================================================================

def extract_text_from_pdf(data: bytes) -> str:
    """PDF dan matn ajratib oladi."""
    if not HAS_PYPDF:
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        chunks: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                chunks.append(text)
        return "\n\n".join(chunks)
    except Exception as e:
        st.warning(f"PDF matnini o'qishda xato: {e}")
        return ""


def render_pdf_first_pages_as_images(data: bytes, max_pages: int = 3) -> list[bytes]:
    """Skanerlangan PDF uchun: birinchi sahifalarni rasmlarga aylantiradi."""
    if not HAS_PDF2IMAGE:
        return []
    try:
        images = convert_from_bytes(data, dpi=180, first_page=1, last_page=max_pages)
        out: list[bytes] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(buf.getvalue())
        return out
    except Exception as e:
        st.info(f"PDF ni rasmga aylantirib bo'lmadi: {e}. (poppler kerak bo'lishi mumkin)")
        return []


def extract_text_from_docx(data: bytes) -> str:
    """Word (.docx) dan matn ajratadi."""
    if not HAS_DOCX:
        return ""
    try:
        document = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        # Jadvallarni ham qo'shamiz
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip("| "):
                    paragraphs.append(row_text)
        return "\n".join(paragraphs)
    except Exception as e:
        st.warning(f"Word faylini o'qishda xato: {e}")
        return ""


def normalize_image_to_png(data: bytes) -> bytes:
    """Rasmni PNG formatga o'tkazadi (JPEG/WEBP/etc → PNG)."""
    if not HAS_PIL:
        return data
    try:
        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        # Juda katta bo'lsa kichraytiramiz (vision model limitiga mos)
        max_dim = 1600
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return data


def read_file_payload(file_bytes: bytes, file_name: str) -> dict:
    """
    Faylni AI uchun tayyorlaydi.

    Qaytaradi: {"text": str, "images": [base64_png, ...]}
    """
    name = file_name.lower()
    payload: dict = {"text": "", "images": []}

    # PDF
    if name.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)
        if text and len(text.strip()) > 50:
            payload["text"] = text
        else:
            # Skanerlangan PDF — rasmga aylantirib vision model bilan o'qiymiz
            images = render_pdf_first_pages_as_images(file_bytes, max_pages=3)
            for img in images:
                payload["images"].append(base64.b64encode(img).decode("ascii"))
        return payload

    # DOCX
    if name.endswith(".docx"):
        payload["text"] = extract_text_from_docx(file_bytes)
        return payload

    # Plain text
    if name.endswith((".txt", ".md", ".csv")):
        try:
            payload["text"] = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            payload["text"] = ""
        return payload

    # Rasmlar
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        png = normalize_image_to_png(file_bytes)
        payload["images"].append(base64.b64encode(png).decode("ascii"))
        return payload

    # Boshqa — matn sifatida sinab ko'ramiz
    try:
        payload["text"] = file_bytes.decode("utf-8", errors="ignore")
    except Exception:
        pass
    return payload


# ============================================================================
#                              GROQ AI BILAN ISHLASH
# ============================================================================

def get_groq_client() -> Optional[Groq]:
    """Groq mijozini yaratadi yoki sozlanmagan bo'lsa None qaytaradi."""
    # Birinchi: Streamlit Secrets (Streamlit Cloud uchun)
    # Keyin: muhit o'zgaruvchisi (.env, lokal ishga tushirish)
    # Oxiri: foydalanuvchi qo'lda kiritgan kalit
    api_key = ""
    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        api_key = ""
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        api_key = st.session_state.get("groq_api_key", "")
    if not api_key:
        return None
    try:
        return Groq(api_key=api_key)
    except Exception as e:
        st.error(f"Groq mijozini yaratib bo'lmadi: {e}")
        return None


SYSTEM_PROMPT = """Siz olimpiada test fayllarini tahlil qiluvchi aqlli yordamchisiz.

Vazifangiz:
1. Foydalanuvchi yuborgan matn yoki rasmdan barcha test savollarini ajratib oling.
2. Har bir savol uchun:
   - Raqamini, savol matnini, variantlarini (agar mavjud bo'lsa) yozing.
   - Agar javoblar kaliti (answer key) berilgan bo'lsa — undan foydalaning.
   - Agar javoblar berilmagan bo'lsa — siz O'ZINGIZ to'g'ri javobni TOPING.
     Siz aqlli AI siz va matematika, fizika, kimyo, biologiya, informatika,
     tarix, geografiya, til va h.k. olimpiada savollarini yecha olasiz.
3. Qisqa tushuntirish bering (nima uchun bu javob to'g'ri).

Javobni FAQAT JSON formatda qaytaring. Boshqa hech qanday matn yozmang.
Sxema:
{
  "title": "test sarlavhasi",
  "questions": [
    {
      "number": 1,
      "question": "savol matni",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "correct_answer": "A",
      "explanation": "qisqa tushuntirish"
    }
  ]
}

Muhim qoidalar:
- Variantlari yo'q ochiq savollar uchun "options" ni bo'sh massiv [] qoldiring.
- "correct_answer" har doim TO'LDIRILGAN bo'lishi kerak (variant harfi yoki javob matni).
- Test sarlavhasi aniq bo'lmasa "Test" deb yozing.
- Qaytariladigan JSON to'liq va to'g'ri sintaksisli bo'lishi kerak.
"""


def build_user_message(payload: dict) -> list[dict]:
    """Groq API uchun user message qismini quradi (matn va/yoki rasm)."""
    content: list[dict] = []
    text = payload.get("text", "").strip()
    images: list[str] = payload.get("images", [])

    if text:
        # Juda uzun bo'lsa kesamiz (model context limitiga sig'sin)
        if len(text) > 25_000:
            text = text[:25_000] + "\n\n[... matn qisqartirildi ...]"
        content.append({
            "type": "text",
            "text": (
                "Quyidagi test matnini tahlil qiling va savollar/javoblarni "
                "JSON ko'rinishda qaytaring:\n\n" + text
            ),
        })

    for b64 in images[:4]:  # eng ko'pi 4 ta rasm
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    if not content:
        content.append({
            "type": "text",
            "text": "Faylda hech qanday tahlil qilinadigan ma'lumot topilmadi.",
        })

    return content


def extract_json_block(text: str) -> Optional[dict]:
    """Modeldan kelgan matndan JSON blokni topib parse qiladi."""
    if not text:
        return None
    # ```json ... ``` ko'rinishidagi blok
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Birinchi { dan oxirgi } gacha
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def analyze_test_with_ai(payload: dict) -> dict:
    """
    Faylni Groq AI orqali tahlil qiladi.
    Qaytaradi: {"title": str, "questions": [Question dict, ...]}
    """
    client = get_groq_client()
    if client is None:
        raise RuntimeError("Groq API kaliti sozlanmagan")

    images = payload.get("images", [])
    has_images = len(images) > 0

    user_content = build_user_message(payload)

    # Model tanlash: rasm bo'lsa vision, aks holda text
    model = VISION_MODEL if has_images else TEXT_MODEL

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content if has_images else user_content[0]["text"]},
    ]

    last_error: Optional[Exception] = None
    for attempt_model in ([model] if not has_images else [model, FALLBACK_VISION_MODEL]):
        try:
            kwargs: dict = {
                "model": attempt_model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 6000,
            }
            # JSON rejimi (faqat text modellarda barqaror ishlaydi)
            if not has_images:
                kwargs["response_format"] = {"type": "json_object"}

            completion = client.chat.completions.create(**kwargs)
            raw = completion.choices[0].message.content or ""
            data = extract_json_block(raw) or json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Model JSON obyekt qaytarmadi")
            return data
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"AI tahlilida xatolik: {last_error}")


# ============================================================================
#                              TEST SAQLASH
# ============================================================================

def save_uploaded_test(file_bytes: bytes, file_name: str) -> TestFile:
    """Yuklangan faylni diskka saqlaydi va metadata qaytaradi."""
    test_id = uuid.uuid4().hex
    suffix = Path(file_name).suffix.lower()
    storage_path = TESTS_DIR / f"{test_id}{suffix}"
    storage_path.write_bytes(file_bytes)
    return TestFile(
        id=test_id,
        file_name=file_name,
        size=len(file_bytes),
        created_at=time.time(),
        file_type=suffix.lstrip("."),
        storage_path=str(storage_path),
    )


def delete_test_file(test: TestFile) -> None:
    """Faylni diskdan o'chiradi."""
    try:
        Path(test.storage_path).unlink(missing_ok=True)
    except Exception:
        pass


def load_test_bytes(test: TestFile) -> bytes:
    """Saqlangan fayldan baytlarni o'qiydi."""
    return Path(test.storage_path).read_bytes()


# ============================================================================
#                              NATIJALARNI SAQLASH
# ============================================================================

def load_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_result(result: TestResult) -> None:
    results = load_results()
    results.insert(0, result.to_dict())
    results = results[:50]  # so'nggi 50 ta natija
    RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================================
#                              JAVOB TEKSHIRISH
# ============================================================================

def normalize_answer(answer: str) -> str:
    """Javobni solishtirish uchun normalizatsiya qiladi."""
    if not answer:
        return ""
    s = answer.strip().lower()
    # "A)", "A.", "A " → "a"
    s = re.sub(r"^([a-eа-е])[\)\.\s]", r"\1", s)
    return s


def is_answer_correct(user: str, correct: str) -> bool:
    """Foydalanuvchi javobi to'g'rimi tekshiradi."""
    u = normalize_answer(user)
    c = normalize_answer(correct)
    if not u or not c:
        return False
    if u == c:
        return True
    # Variant harfi bo'yicha solishtirish
    if u[0] == c[0] and u[0] in "abcdeабсде":
        return True
    # Birining ichida ikkinchisi
    if u in c or c in u:
        return True
    return False


# ============================================================================
#                              SESSIYA HOLATI
# ============================================================================

def init_session_state() -> None:
    """Streamlit sessiya o'zgaruvchilarini ishga tushiradi."""
    defaults: dict[str, Any] = {
        "first_name": "",
        "last_name": "",
        "duration_min": 30,
        "tests": [],                # list[TestFile]
        "active_test_id": None,
        "view": "home",             # "home" | "test" | "result"
        "current_test": None,       # dict: {"title", "questions": [Question]}
        "answers": {},              # {q_number: str}
        "current_index": 0,
        "test_started_at": None,    # epoch seconds
        "test_duration_sec": 0,
        "last_result": None,        # TestResult dict
        "groq_api_key": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ============================================================================
#                              UI: STIL
# ============================================================================

CUSTOM_CSS = """
<style>
    /* Asosiy fon va shrift */
    .stApp {
        background: radial-gradient(ellipse at top, #1a1a2e 0%, #0f0f1a 60%);
    }
    /* Sarlavhalar */
    h1, h2, h3 {
        font-family: 'Helvetica Neue', sans-serif;
        letter-spacing: -0.02em;
    }
    /* Gradient matn */
    .gradient-text {
        background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    /* Karta */
    .olimp-card {
        background: rgba(30, 30, 50, 0.6);
        border: 1px solid rgba(251, 191, 36, 0.2);
        border-radius: 14px;
        padding: 20px;
        backdrop-filter: blur(10px);
    }
    /* Taymer */
    .timer-box {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 18px;
        border-radius: 12px;
        font-family: 'Courier New', monospace;
        font-weight: 700;
        font-size: 1.2rem;
        background: rgba(251, 191, 36, 0.1);
        border: 1px solid rgba(251, 191, 36, 0.4);
        color: #fbbf24;
    }
    .timer-warn {
        background: rgba(239, 68, 68, 0.15);
        border-color: rgba(239, 68, 68, 0.6);
        color: #f87171;
        animation: pulse 1s infinite;
    }
    @keyframes pulse {
        0%, 100% { box-shadow: 0 0 10px rgba(239,68,68,0.3); }
        50% { box-shadow: 0 0 30px rgba(239,68,68,0.7); }
    }
    /* Natija raqamlari */
    .result-number {
        font-size: 2.5rem;
        font-weight: 800;
        text-align: center;
    }
    .result-correct { color: #4ade80; }
    .result-wrong { color: #f87171; }
    .result-percent {
        background: linear-gradient(135deg, #fbbf24, #f59e0b);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    /* Tugmalar */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
    }
</style>
"""


# ============================================================================
#                              UI: SIDEBAR
# ============================================================================

def render_sidebar() -> None:
    """Chap paneldagi sozlamalar va fayllar ro'yxati."""
    with st.sidebar:
        st.markdown(f"## {APP_ICON} OlimpTest")
        st.caption(APP_TAGLINE)
        st.divider()

        # API kalit (agar .env da yo'q bo'lsa)
        secrets_has_key = False
        try:
            secrets_has_key = bool(st.secrets.get("GROQ_API_KEY", ""))
        except Exception:
            pass
        if not (os.getenv("GROQ_API_KEY") or secrets_has_key):
            with st.expander("🔑 Groq API kalit", expanded=not bool(st.session_state.groq_api_key)):
                key = st.text_input(
                    "API kalit",
                    type="password",
                    value=st.session_state.groq_api_key,
                    help="https://console.groq.com/keys dan oling",
                )
                if key != st.session_state.groq_api_key:
                    st.session_state.groq_api_key = key
                st.caption("⚠️ Kalitni hech kimga yubormang")
        st.divider()

        # Foydalanuvchi
        st.markdown("### 👤 Foydalanuvchi")
        st.session_state.first_name = st.text_input(
            "Ism", value=st.session_state.first_name, placeholder="Ali"
        )
        st.session_state.last_name = st.text_input(
            "Familya", value=st.session_state.last_name, placeholder="Valiyev"
        )
        st.session_state.duration_min = st.number_input(
            "⏱ Vaqt (daqiqa)",
            min_value=1, max_value=300,
            value=int(st.session_state.duration_min),
            step=1,
        )
        st.divider()

        # Test fayllari
        st.markdown("### 📁 Test fayllari")
        uploaded = st.file_uploader(
            "Fayl yuklash",
            type=SUPPORTED_EXTENSIONS,
            accept_multiple_files=False,
            key="file_uploader",
        )
        if uploaded is not None:
            existing_names = {t.file_name for t in st.session_state.tests}
            if uploaded.name not in existing_names:
                file_bytes = uploaded.getvalue()
                test = save_uploaded_test(file_bytes, uploaded.name)
                st.session_state.tests.append(test)
                st.session_state.active_test_id = test.id
                st.success(f"✅ {uploaded.name} yuklandi")

        # Yuklangan fayllar ro'yxati
        if not st.session_state.tests:
            st.caption("Hali test yuklanmagan")
        else:
            for test in st.session_state.tests:
                is_active = (test.id == st.session_state.active_test_id)
                col1, col2 = st.columns([5, 1])
                with col1:
                    label = ("✅ " if is_active else "📄 ") + test.file_name
                    if st.button(
                        label,
                        key=f"select_{test.id}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary",
                    ):
                        st.session_state.active_test_id = test.id
                        st.rerun()
                with col2:
                    if st.button("🗑", key=f"del_{test.id}", help="O'chirish"):
                        delete_test_file(test)
                        st.session_state.tests = [
                            t for t in st.session_state.tests if t.id != test.id
                        ]
                        if st.session_state.active_test_id == test.id:
                            st.session_state.active_test_id = None
                        st.rerun()
                st.caption(f"  {test.size / 1024:.1f} KB · {test.file_type.upper()}")


# ============================================================================
#                              UI: BOSH SAHIFA
# ============================================================================

def render_home() -> None:
    """Bosh sahifa — testni boshlash ekranı."""
    st.markdown(
        f"""
        <div style="text-align:center; padding:30px 0 20px;">
            <div style="display:inline-block; padding:6px 14px; border-radius:999px;
                        background:rgba(251,191,36,0.1); border:1px solid rgba(251,191,36,0.3);
                        color:#fbbf24; font-size:0.85rem; margin-bottom:16px;">
                ✨ Groq AI quvvatida
            </div>
            <h1 style="font-size:3rem; margin:0;">
                <span class="gradient-text">OlimpTest</span>
            </h1>
            <p style="color:#9ca3af; max-width:600px; margin:12px auto;">
                {APP_TAGLINE}. Har qanday test faylini yuklang —
                javobi yo'q bo'lsa AI o'zi yechib beradi.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Xususiyatlar
    cols = st.columns(3)
    features = [
        ("📄", "Har qanday format", "PDF, Word, rasm, matn — barchasi"),
        ("🧠", "AI tahlili", "Groq LLaMA savollarni ajratadi va javob topadi"),
        ("⏱", "Vaqtli mashq", "Belgilangan vaqt ichida tezligingizni oshiring"),
    ]
    for col, (icon, title, desc) in zip(cols, features):
        with col:
            st.markdown(
                f"""
                <div class="olimp-card" style="text-align:center; height:160px;">
                    <div style="font-size:2rem;">{icon}</div>
                    <div style="font-weight:700; margin:8px 0;">{title}</div>
                    <div style="color:#9ca3af; font-size:0.85rem;">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.write("")

    # Tayyorlik holati
    has_user = bool(st.session_state.first_name.strip() and st.session_state.last_name.strip())
    has_test = st.session_state.active_test_id is not None
    secrets_key = ""
    try:
        secrets_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        pass
    has_key = bool(secrets_key or os.getenv("GROQ_API_KEY") or st.session_state.groq_api_key)

    if not has_key:
        st.warning("🔑 Avval chap paneldan Groq API kalitini kiriting")
    elif not has_user:
        st.info("1️⃣ Chap paneldan ism va familyangizni kiriting")
    elif not has_test:
        st.info("2️⃣ Chap paneldan test faylini yuklang va tanlang")
    else:
        st.success("3️⃣ Hammasi tayyor — testni boshlashingiz mumkin")

    st.write("")

    # Boshlash tugmasi
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        start_disabled = not (has_user and has_test and has_key)
        if st.button(
            "🚀 Testni boshlash",
            disabled=start_disabled,
            use_container_width=True,
            type="primary",
        ):
            start_test()

    # Oldingi natijalar
    results = load_results()
    if results:
        st.divider()
        st.markdown("### 📊 So'nggi natijalar")
        for r in results[:5]:
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                with c1:
                    st.write(f"**{r['student_name']}** · {r['test_title']}")
                    finished = datetime.fromtimestamp(r["finished_at"])
                    st.caption(finished.strftime("%Y-%m-%d %H:%M"))
                with c2:
                    st.write(f"{r['correct']}/{r['total_questions']} to'g'ri")
                with c3:
                    st.metric("", f"{r['percent']:.0f}%")
                with c4:
                    mins = r["duration_used_sec"] // 60
                    secs = r["duration_used_sec"] % 60
                    st.caption(f"⏱ {mins}:{secs:02d}")


# ============================================================================
#                              TESTNI BOSHLASH
# ============================================================================

def start_test() -> None:
    """Tanlangan faylni AI bilan tahlil qilib, test rejimiga o'tadi."""
    test = next(
        (t for t in st.session_state.tests if t.id == st.session_state.active_test_id),
        None,
    )
    if test is None:
        st.error("Test fayli topilmadi")
        return

    with st.spinner("🤖 AI fayldan savollarni o'qimoqda..."):
        try:
            file_bytes = load_test_bytes(test)
            payload = read_file_payload(file_bytes, test.file_name)

            if not payload.get("text") and not payload.get("images"):
                st.error("Fayldan ma'lumot olib bo'lmadi")
                return

            data = analyze_test_with_ai(payload)
            raw_questions = data.get("questions", [])
            if not raw_questions:
                st.error("Faylda savollar topilmadi")
                return

            questions = [Question.from_dict(q) for q in raw_questions]
            st.session_state.current_test = {
                "title": data.get("title", test.file_name),
                "file_name": test.file_name,
                "questions": [q.to_dict() for q in questions],
            }
            st.session_state.answers = {}
            st.session_state.current_index = 0
            st.session_state.test_started_at = time.time()
            st.session_state.test_duration_sec = int(st.session_state.duration_min) * 60
            st.session_state.view = "test"
            st.success(f"✅ {len(questions)} ta savol topildi. Test boshlanmoqda...")
            time.sleep(0.6)
            st.rerun()
        except Exception as e:
            st.error(f"Xato: {e}")


# ============================================================================
#                              UI: TEST EKRANI
# ============================================================================

def render_test() -> None:
    """Test boshqaruv ekrani."""
    test = st.session_state.current_test
    if not test:
        st.session_state.view = "home"
        st.rerun()
        return

    questions = [Question.from_dict(q) for q in test["questions"]]
    total = len(questions)
    idx = st.session_state.current_index
    current = questions[idx]

    # Vaqt hisoblash
    elapsed = int(time.time() - st.session_state.test_started_at)
    remaining = max(0, st.session_state.test_duration_sec - elapsed)

    # Vaqt tugagan bo'lsa avtomatik yakunlash
    if remaining == 0:
        finish_test(forced=True)
        return

    # Sarlavha + taymer
    col_t, col_timer = st.columns([3, 1])
    with col_t:
        st.markdown(f"### {test['title']}")
        st.caption(f"👤 {st.session_state.first_name} {st.session_state.last_name}")
    with col_timer:
        mm, ss = divmod(remaining, 60)
        warn_class = "timer-warn" if remaining < 60 else ""
        st.markdown(
            f"<div class='timer-box {warn_class}'>⏱ {mm:02d}:{ss:02d}</div>",
            unsafe_allow_html=True,
        )

    # Progress bar
    progress = (idx + 1) / total
    st.progress(progress, text=f"Savol {idx + 1} / {total}")

    # Savol kartasi
    st.markdown("<div class='olimp-card'>", unsafe_allow_html=True)
    st.markdown(f"#### {current.number}. {current.question}")

    answer_key = f"q_{current.number}"
    current_answer = st.session_state.answers.get(current.number, "")

    if current.options:
        # Variantli savol
        labels: list[str] = []
        for i, opt in enumerate(current.options):
            letter_match = re.match(r"^\s*([A-EA-Eа-е])[\)\.]", opt)
            letter = letter_match.group(1).upper() if letter_match else chr(65 + i)
            labels.append(f"{letter}) {re.sub(r'^[A-Ea-eА-Еа-е][).]\\s*', '', opt)}")

        # Joriy javobning indeksi
        try:
            current_letter = (current_answer[0].upper() if current_answer else "")
            default_idx = next(
                (i for i, l in enumerate(labels) if l.startswith(current_letter + ")")),
                None,
            )
        except Exception:
            default_idx = None

        choice = st.radio(
            "Javobingizni tanlang:",
            options=labels,
            index=default_idx if default_idx is not None else None,
            key=answer_key,
            label_visibility="collapsed",
        )
        if choice:
            letter = choice.split(")", 1)[0].strip()
            st.session_state.answers[current.number] = letter
    else:
        # Ochiq savol
        text_answer = st.text_input(
            "Javobingizni kiriting:",
            value=current_answer,
            key=answer_key,
        )
        if text_answer != current_answer:
            st.session_state.answers[current.number] = text_answer

    st.markdown("</div>", unsafe_allow_html=True)
    st.write("")

    # Navigatsiya
    nav_cols = st.columns([1, 1, 1])
    with nav_cols[0]:
        if st.button("⬅ Oldingi", disabled=(idx == 0), use_container_width=True):
            st.session_state.current_index = max(0, idx - 1)
            st.rerun()
    with nav_cols[1]:
        if st.button("🏁 Yakunlash", use_container_width=True, type="primary"):
            finish_test(forced=False)
            return
    with nav_cols[2]:
        if st.button("Keyingi ➡", disabled=(idx >= total - 1), use_container_width=True):
            st.session_state.current_index = min(total - 1, idx + 1)
            st.rerun()

    # Savollar paneli
    st.write("")
    st.caption("Savollarga o'tish:")
    cols_per_row = 10
    rows = (total + cols_per_row - 1) // cols_per_row
    for r in range(rows):
        row_cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            qi = r * cols_per_row + c
            if qi >= total:
                break
            q = questions[qi]
            answered = q.number in st.session_state.answers and st.session_state.answers[q.number]
            is_current = (qi == idx)
            label = f"{q.number}"
            btn_type = "primary" if is_current else ("secondary" if answered else "secondary")
            with row_cols[c]:
                if st.button(label, key=f"jump_{qi}", use_container_width=True, type=btn_type):
                    st.session_state.current_index = qi
                    st.rerun()

    # Avtomatik yangilanish (taymer uchun) — har 1 sekundda
    if remaining > 0:
        # Streamlit'da aniq timer yo'q; sahifani qayta yuklash uchun rerun ishlatamiz
        time.sleep(1)
        st.rerun()


def finish_test(forced: bool = False) -> None:
    """Testni yakunlaydi va natijalarni saqlaydi."""
    test = st.session_state.current_test
    if not test:
        return

    questions = [Question.from_dict(q) for q in test["questions"]]
    answers = st.session_state.answers
    total = len(questions)
    correct = 0
    wrong = 0
    skipped = 0
    for q in questions:
        ua = answers.get(q.number, "")
        if not ua:
            skipped += 1
        elif is_answer_correct(ua, q.correct_answer):
            correct += 1
        else:
            wrong += 1
    answered = total - skipped
    percent = (correct / total * 100) if total else 0.0

    elapsed = int(time.time() - st.session_state.test_started_at)
    duration_used = min(elapsed, st.session_state.test_duration_sec)

    result = TestResult(
        id=uuid.uuid4().hex,
        student_name=f"{st.session_state.first_name} {st.session_state.last_name}".strip(),
        test_title=test.get("title", "Test"),
        file_name=test.get("file_name", ""),
        total_questions=total,
        correct=correct,
        wrong=wrong,
        skipped=skipped,
        percent=percent,
        duration_used_sec=duration_used,
        duration_total_sec=st.session_state.test_duration_sec,
        finished_at=time.time(),
        questions=test["questions"],
        answers={str(k): v for k, v in answers.items()},
    )
    save_result(result)
    st.session_state.last_result = result.to_dict()
    st.session_state.view = "result"
    if forced:
        st.warning("⏰ Vaqt tugadi — test avtomatik yakunlandi")
    st.rerun()


# ============================================================================
#                              UI: NATIJA EKRANI
# ============================================================================

def render_result() -> None:
    """Test yakunidan keyingi natija ekrani."""
    result = st.session_state.last_result
    if not result:
        st.session_state.view = "home"
        st.rerun()
        return

    st.markdown(
        f"""
        <div style="text-align:center; padding:20px 0;">
            <div style="font-size:3rem;">🏆</div>
            <h2 style="margin:10px 0;">Test yakunlandi</h2>
            <p style="color:#9ca3af;">
                {result['student_name']} · {result['test_title']}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Statistika kartalari
    cols = st.columns(4)
    stats = [
        ("✅ To'g'ri", result["correct"], "result-correct"),
        ("❌ Noto'g'ri", result["wrong"], "result-wrong"),
        ("⏭ O'tkazilgan", result["skipped"], ""),
        (f"{result['percent']:.0f}%", "Natija", "result-percent"),
    ]
    for col, (label, value, cls) in zip(cols, stats):
        with col:
            if isinstance(value, int):
                st.markdown(
                    f"""
                    <div class="olimp-card" style="text-align:center;">
                        <div class="result-number {cls}">{value}</div>
                        <div style="color:#9ca3af; font-size:0.85rem;">{label}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div class="olimp-card" style="text-align:center;">
                        <div class="result-number {cls}">{label}</div>
                        <div style="color:#9ca3af; font-size:0.85rem;">{value}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Vaqt ma'lumoti
    used = result["duration_used_sec"]
    total = result["duration_total_sec"]
    st.write("")
    st.caption(
        f"⏱ Sarflangan vaqt: {used // 60} daqiqa {used % 60} soniya "
        f"(berilgan: {total // 60} daqiqa)"
    )

    st.divider()

    # Har bir savol bo'yicha tahlil
    st.markdown("### 📝 Savollar bo'yicha tahlil")
    for q_dict in result["questions"]:
        q = Question.from_dict(q_dict)
        ua = result["answers"].get(str(q.number), "")
        ok = ua and is_answer_correct(ua, q.correct_answer)

        if not ua:
            border_color = "#6b7280"
            icon = "⏭"
            status = "Javob berilmagan"
        elif ok:
            border_color = "#4ade80"
            icon = "✅"
            status = "To'g'ri"
        else:
            border_color = "#f87171"
            icon = "❌"
            status = "Noto'g'ri"

        with st.expander(f"{icon} {q.number}. {q.question[:80]}{'...' if len(q.question) > 80 else ''}"):
            st.markdown(
                f"<div style='border-left:3px solid {border_color}; padding-left:12px;'>",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Savol:** {q.question}")
            if q.options:
                st.markdown("**Variantlar:**")
                for opt in q.options:
                    st.markdown(f"- {opt}")
            st.markdown(f"**Sizning javobingiz:** `{ua or '—'}`")
            st.markdown(f"**To'g'ri javob:** `{q.correct_answer}`")
            if q.explanation:
                st.markdown(f"**Tushuntirish:** _{q.explanation}_")
            st.markdown(f"**Holat:** {status}")
            st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # Harakat tugmalari
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔁 Yangi test", use_container_width=True, type="primary"):
            st.session_state.view = "home"
            st.session_state.current_test = None
            st.session_state.last_result = None
            st.rerun()
    with col2:
        # Natijani JSON sifatida yuklab olish
        st.download_button(
            "💾 Natijani saqlash (JSON)",
            data=json.dumps(result, ensure_ascii=False, indent=2),
            file_name=f"natija_{result['student_name'].replace(' ', '_')}_{int(result['finished_at'])}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col3:
        # Matn ko'rinishida hisobot
        report_lines = [
            f"OlimpTest Natijasi",
            f"=" * 40,
            f"Talaba: {result['student_name']}",
            f"Test: {result['test_title']}",
            f"Sana: {datetime.fromtimestamp(result['finished_at']).strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"Jami savollar: {result['total_questions']}",
            f"To'g'ri: {result['correct']}",
            f"Noto'g'ri: {result['wrong']}",
            f"O'tkazilgan: {result['skipped']}",
            f"Natija: {result['percent']:.1f}%",
            f"Sarflangan vaqt: {used // 60}:{used % 60:02d}",
            f"",
            f"Savollar:",
            f"-" * 40,
        ]
        for q_dict in result["questions"]:
            q = Question.from_dict(q_dict)
            ua = result["answers"].get(str(q.number), "—")
            report_lines.append(f"{q.number}. {q.question}")
            report_lines.append(f"   Sizning javob: {ua}")
            report_lines.append(f"   To'g'ri: {q.correct_answer}")
            if q.explanation:
                report_lines.append(f"   Izoh: {q.explanation}")
            report_lines.append("")
        st.download_button(
            "📄 Hisobot (TXT)",
            data="\n".join(report_lines),
            file_name=f"hisobot_{int(result['finished_at'])}.txt",
            mime="text/plain",
            use_container_width=True,
        )


# ============================================================================
#                              ASOSIY ENTRY POINT
# ============================================================================

def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_session_state()
    render_sidebar()

    view = st.session_state.view
    if view == "test":
        render_test()
    elif view == "result":
        render_result()
    else:
        render_home()


if __name__ == "__main__":
    main()
