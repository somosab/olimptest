import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
import os, re, io, json, base64, time
from groq import Groq
import cohere
import mammoth
from docx import Document
import PyPDF2
from bs4 import BeautifulSoup
from PIL import Image
import numpy as np

st.set_page_config(page_title="OlimpTest - Matematika", page_icon="🏆", layout="wide")

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
#  KaTeX render
# ══════════════════════════════════════════════════════
def render_math_html(text:str, font_size:str="20px", bg:str="rgba(255,255,255,0.05)"):
    lines  = text.count('<br') + text.count('\n') + 1
    height = max(70, min(700, lines*38 + len(text)//4))
    html = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{delimiters:[
    {{left:'$$',right:'$$',display:true}},
    {{left:'$',right:'$',display:false}}
  ],throwOnError:false}});"></script>
<style>
body{{background:{bg};color:#E0E0E0;font-size:{font_size};font-family:sans-serif;
     padding:12px 16px;border-radius:10px;border:1px solid rgba(255,215,0,0.2);margin:0;}}
.katex,.katex-display{{color:#FFD700;}}
</style></head><body>{text}</body></html>"""
    components.html(html, height=height, scrolling=False)


# ══════════════════════════════════════════════════════
#  OMML → LaTeX
# ══════════════════════════════════════════════════════
MN = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
WN = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NARY_OPS  = {'\u222b':'\\int','\u222c':'\\iint','\u222d':'\\iiint',
              '\u2211':'\\sum','\u220f':'\\prod','\u222e':'\\oint'}
PROP_TAGS = {'rPr','fPr','radPr','naryPr','dPr','sSupPr','sSubPr','sSubSupPr',
              'funcPr','sPr','limLowPr','limUppPr','eqArrPr','mPr','ctrlPr',
              'groupChrPr','borderBoxPr','barPr','accPr','phantPr','boxPr'}
FN_MAP    = {'sin':'\\sin','cos':'\\cos','tan':'\\tan','cot':'\\cot',
              'sec':'\\sec','csc':'\\csc','log':'\\log','ln':'\\ln',
              'exp':'\\exp','lim':'\\lim','max':'\\max','min':'\\min',
              'det':'\\det','gcd':'\\gcd'}
ACC_MAP   = {'\u0302':'\\hat','\u0303':'\\tilde','\u0307':'\\dot',
              '\u0308':'\\ddot','\u0305':'\\bar','\u20d7':'\\vec'}

def omml_to_latex(el)->str:
    tag=el.tag.replace(MN,'').replace(WN,'')
    if tag in PROP_TAGS: return ''
    if tag in ('oMath','oMathPara','e','num','den','fName','lim','sub','sup','deg'):
        return ''.join(omml_to_latex(c) for c in el)
    if tag=='r': return ''.join(t.text or '' for t in el.findall(f'{MN}t'))
    if tag=='t': return el.text or ''
    if tag=='f':
        n=omml_to_latex(el.find(f'{MN}num')) if el.find(f'{MN}num') is not None else ''
        d=omml_to_latex(el.find(f'{MN}den')) if el.find(f'{MN}den') is not None else ''
        return f'\\frac{{{n}}}{{{d}}}'
    if tag=='rad':
        pr=el.find(f'{MN}radPr');deg_el=el.find(f'{MN}deg');e_el=el.find(f'{MN}e')
        hide=False
        if pr is not None:
            dh=pr.find(f'{MN}degHide')
            if dh is not None: hide=dh.get(f'{MN}val','1')!='0'
        deg=omml_to_latex(deg_el).strip() if deg_el is not None else ''
        e=omml_to_latex(e_el).strip() if e_el is not None else ''
        return f'\\sqrt{{{e}}}' if (hide or not deg) else f'\\sqrt[{deg}]{{{e}}}'
    if tag=='sSup':
        b=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        s=omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        return f'{{{b}}}^{{{s}}}'
    if tag=='sSub':
        b=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        s=omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        return f'{{{b}}}_{{{s}}}'
    if tag=='sSubSup':
        b=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        s=omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        p=omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        return f'{{{b}}}_{{{s}}}^{{{p}}}'
    if tag=='nary':
        pr=el.find(f'{MN}naryPr');op='\\sum'
        if pr is not None:
            ch_el=pr.find(f'{MN}chr')
            if ch_el is not None: op=NARY_OPS.get(ch_el.get(f'{MN}val',''),'\\sum')
        lo=omml_to_latex(el.find(f'{MN}sub')) if el.find(f'{MN}sub') is not None else ''
        hi=omml_to_latex(el.find(f'{MN}sup')) if el.find(f'{MN}sup') is not None else ''
        bd=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        res=op
        if lo: res+=f'_{{{lo}}}'
        if hi: res+=f'^{{{hi}}}'
        return res+f' {bd}'
    if tag=='func':
        f_raw=omml_to_latex(el.find(f'{MN}fName')).strip() if el.find(f'{MN}fName') is not None else ''
        c=omml_to_latex(el.find(f'{MN}e')).strip() if el.find(f'{MN}e') is not None else ''
        return f'{FN_MAP.get(f_raw,f_raw)}\\left({c}\\right)'
    if tag=='d':
        pr=el.find(f'{MN}dPr');left,right='(',')'
        if pr is not None:
            beg=pr.find(f'{MN}begChr');end=pr.find(f'{MN}endChr')
            if beg is not None: left=beg.get(f'{MN}val','(') or '.'
            if end is not None: right=end.get(f'{MN}val',')') or '.'
        inner=''.join(omml_to_latex(c) for c in el if c.tag!=f'{MN}dPr')
        return f'\\left{left}{inner}\\right{right}'
    if tag=='m':
        rows=el.findall(f'{MN}mr')
        lr=[' & '.join(omml_to_latex(c) for c in r.findall(f'{MN}e')) for r in rows]
        return '\\begin{pmatrix}'+'\\\\'.join(lr)+'\\end{pmatrix}'
    if tag=='limLow':
        b=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        l=omml_to_latex(el.find(f'{MN}lim')) if el.find(f'{MN}lim') is not None else ''
        return f'{b}_{{{l}}}'
    if tag=='limUpp':
        b=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        l=omml_to_latex(el.find(f'{MN}lim')) if el.find(f'{MN}lim') is not None else ''
        return f'{b}^{{{l}}}'
    if tag=='acc':
        pr=el.find(f'{MN}accPr');ch=''
        if pr is not None:
            ch_el=pr.find(f'{MN}chr')
            if ch_el is not None: ch=ch_el.get(f'{MN}val','')
        inner=omml_to_latex(el.find(f'{MN}e')) if el.find(f'{MN}e') is not None else ''
        return f'{ACC_MAP.get(ch,"\\hat")}{{{inner}}}'
    if tag=='bar':
        e=el.find(f'{MN}e')
        return f'\\overline{{{omml_to_latex(e) if e is not None else ""}}}'
    if tag=='eqArr':
        return '\\begin{cases}'+'\\\\'.join(omml_to_latex(r) for r in el.findall(f'{MN}e'))+'\\end{cases}'
    return ''.join(omml_to_latex(c) for c in el)

def get_para_text(para)->str:
    parts=[]
    for child in para._element:
        ctag=child.tag
        if ctag==f'{MN}oMathPara':
            for om in child.findall(f'{MN}oMath'):
                lat=omml_to_latex(om).strip()
                if lat: parts.append(f'$${lat}$$')
        elif ctag==f'{MN}oMath':
            lat=omml_to_latex(child).strip()
            if lat: parts.append(f'${lat}$')
        elif ctag==f'{WN}r':
            for t in child.findall(f'{WN}t'):
                if t.text: parts.append(t.text)
        elif ctag in (f'{WN}ins',f'{WN}hyperlink'):
            for r in child.findall(f'.//{WN}r'):
                for t in r.findall(f'{WN}t'):
                    if t.text: parts.append(t.text)
    return ''.join(parts)


# ══════════════════════════════════════════════════════
#  Rasm
# ══════════════════════════════════════════════════════
def is_geometric_image(arr:np.ndarray)->bool:
    gray=np.mean(arr,axis=2) if arr.ndim==3 else arr.astype(float)
    return len(np.unique(gray.astype(np.uint8)))<120 or np.sum(gray<100)/gray.size>0.25

def analyze_image_with_cohere(img_bytes:bytes)->str:
    if not COHERE_API_KEY: return "Geometrik rasm"
    try:
        co=cohere.ClientV2(api_key=COHERE_API_KEY)
        b64=base64.b64encode(img_bytes).decode()
        r=co.chat(model="command-r-plus-vision",messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
            {"type":"text","text":"Bu matematika masalasi rasmi. Geometrik shakl, o'lcham, burchak, yorliqlarni batafsil O'zbek tilida ta'rifla."}
        ]}])
        return r.message.content[0].text if r.message.content else "Tahlil qilinmadi"
    except Exception as e:
        return f"Rasm xatosi: {e}"


# ══════════════════════════════════════════════════════
#  Fayl o'qish
# ══════════════════════════════════════════════════════
def extract_docx(raw:bytes)->dict:
    try:
        doc=Document(io.BytesIO(raw))
        lines,images=[],[]
        for para in doc.paragraphs:
            t=get_para_text(para).strip()
            if t: lines.append(t)
        for table in doc.tables:
            for row in table.rows:
                parts=[]
                for cell in row.cells:
                    ct=' '.join(get_para_text(p).strip() for p in cell.paragraphs if get_para_text(p).strip())
                    if ct: parts.append(ct)
                if parts: lines.append(' | '.join(parts))
        for rel in doc.part.rels.values():
            if "image" in rel.target_ref:
                try:
                    ext=rel.target_ref.split('.')[-1].lower()
                    mime=f"image/{'jpeg' if ext in ('jpg','jpeg') else ext}"
                    images.append({'bytes':rel.target_part.blob,'mime':mime})
                except: pass
        text='\n\n'.join(lines)
        if not text.strip():
            res=mammoth.convert_to_html(io.BytesIO(raw))
            text=BeautifulSoup(res.value,'html.parser').get_text('\n',strip=True)
        return {'text':text,'images':images}
    except Exception as e:
        st.error(f"Word xatolik: {e}"); return {'text':'','images':[]}

def extract_pdf(raw:bytes)->dict:
    try:
        r=PyPDF2.PdfReader(io.BytesIO(raw))
        return {'text':'\n\n'.join(p.extract_text() or '' for p in r.pages),'images':[]}
    except Exception as e:
        st.error(f"PDF xatolik: {e}"); return {'text':'','images':[]}


# ══════════════════════════════════════════════════════
#  ✅ BUG-1 FIX: LaTeX komandalarni JSON parsedan OLDIN himoya qilish
#  Sabab: \right ichidagi \r JSON da carriage-return sifatida talqin qilinadi
#  va natijada \ight chiqadi
# ══════════════════════════════════════════════════════

# Barcha taniqli LaTeX komandalar (JSON buzadigan harflar bilan boshlanuvchilar)
LATEX_CMDS = [
    # r bilan boshlanadiganlar (ENG MUHIM — \r JSON escape!)
    'right','rho','rightarrow','Rightarrow','rightharpoonup',
    # b bilan boshlanadiganlar (\b JSON escape!)
    'beta','bar','begin','big','bigg','binom','boldsymbol',
    # f bilan boshlanadiganlar (\f JSON escape!)
    'frac','forall','footnotesize',
    # n bilan boshlanadiganlar (\n JSON escape!)
    'nu','nabla','neq','notin','norm',
    # t bilan boshlanadiganlar (\t JSON escape!)
    'theta','tau','times','text','tilde','top',
    # Boshqa keng ishlatiladiganlar
    'left','leq','geq','sqrt','sum','int','prod','oint',
    'alpha','beta','gamma','delta','epsilon','zeta','eta',
    'iota','kappa','lambda','mu','xi','pi','sigma','phi',
    'chi','psi','omega','Gamma','Delta','Theta','Lambda',
    'Xi','Pi','Sigma','Phi','Psi','Omega',
    'cdot','times','div','pm','mp','infty','partial',
    'in','subset','supset','cup','cap','emptyset',
    'overline','underline','hat','vec','dot','ddot','tilde','bar',
    'pmatrix','bmatrix','vmatrix','cases','matrix','aligned',
    'mathrm','mathbf','mathit','mathcal','text',
    'lim','max','min','sin','cos','tan','cot','sec','csc',
    'log','ln','exp','det','gcd','deg',
    'angle','triangle','parallel','perp',
    'Leftrightarrow','leftrightarrow','leftarrow','Leftarrow',
    'uparrow','downarrow','iff','implies',
    'quad','qquad','hspace','vspace',
    'frac','dfrac','tfrac','cfrac',
    'ldots','cdots','vdots','ddots',
    'not','neg','land','lor',
    'mathbb','mathfrak',
]

def protect_latex_before_json(raw:str)->str:
    """
    JSON parse qilishdan OLDIN LaTeX komandalarni himoya qilish.
    Masalan: \\right → \\\\right (JSON ichida to'g'ri saqlanadi)
    Bu FAQAT hali double-escape bo'lmagan komandalarni tuzatadi.
    """
    # Uzunroqdan qisqaga tartiblash (to'g'ri almashtirish uchun)
    cmds = sorted(LATEX_CMDS, key=len, reverse=True)
    for cmd in cmds:
        # Faqat bitta backslash bilan kelganlarni (ikkitasi allaqachon to'g'ri)
        # (?<!\\) — oldida backslash bo'lmagan holatlar
        pattern = r'(?<!\\)\\(?!\\)' + re.escape(cmd) + r'(?=[^a-zA-Z]|$)'
        replacement = r'\\\\' + cmd
        raw = re.sub(pattern, replacement, raw)
    return raw

def safe_json(raw:str):
    """Ko'p usulda JSON parse qilish."""
    # Markdown olib tashlash
    raw = re.sub(r'```(?:json)?\s*','',raw).strip().rstrip('`').strip()

    # Massivni ajratib olish
    start=raw.find('['); end=raw.rfind(']')
    if start==-1 or end<=start: return None
    chunk=raw[start:end+1]

    attempts=[
        chunk,
        protect_latex_before_json(chunk),
        re.sub(r'\\(?!["\\\/bfnrtu])',r'\\\\',chunk),
    ]
    for attempt in attempts:
        s=attempt.find('['); e=attempt.rfind(']')
        if s==-1 or e<=s: continue
        try: return json.loads(attempt[s:e+1])
        except: pass

    # Oxirgi chora: har bir {..} blokni alohida
    return manual_extract(raw)

def manual_extract(text:str)->list:
    questions=[]
    depth=0; start=-1; blocks=[]
    for i,ch in enumerate(text):
        if ch=='{':
            if depth==0: start=i
            depth+=1
        elif ch=='}':
            depth-=1
            if depth==0 and start!=-1:
                blocks.append(text[start:i+1]); start=-1
    for block in blocks:
        try:
            fixed=protect_latex_before_json(block)
            obj=json.loads(fixed)
            if 'question' in obj and 'options' in obj:
                if 'correct' not in obj: obj['correct']='A'
                if 'number' not in obj: obj['number']=len(questions)+1
                if 'explanation' not in obj: obj['explanation']=''
                if 'has_image' not in obj: obj['has_image']=False
                questions.append(obj)
        except: pass
    return questions


# ══════════════════════════════════════════════════════
#  AI: Savollarni tahlil qilish
# ══════════════════════════════════════════════════════
def parse_questions_with_ai(text:str, image_bytes_list:list, geo_imgs:list)->list:
    if not GROQ_API_KEY:
        st.error("⚠️ GROQ_API_KEY topilmadi."); return []

    # Rasm tahlili
    img_desc=""
    if image_bytes_list:
        with st.spinner("🖼️ Rasmlar tahlil qilinmoqda..."):
            for idx,ib in enumerate(geo_imgs):
                try:
                    desc=analyze_image_with_cohere(ib)
                    img_desc+=f"\nRasm {idx+1}: {desc}"
                except: pass

    # Savollar sonini aniqlash
    nums=set()
    for line in text.split('\n'):
        m=re.match(r'^(\d+)\s*[\.\)]\s',line.strip())
        if m:
            n=int(m.group(1))
            if 1<=n<=200: nums.add(n)
    num_ask=len(nums) if nums else 10
    st.info(f"📊 Faylda taxminan **{num_ask}** ta savol aniqlandi, **{len(geo_imgs)}** ta geometrik rasm bor")

    client=Groq(api_key=GROQ_API_KEY)

    # ✅ BUG-2 FIX: has_image maydoni — rasm qaysi savolga tegishli
    prompt=f"""Bu matematika olimpiada testi. Barcha {num_ask} ta savolni JSON formatda qaytar.

QOIDALAR:
1. Faqat JSON massivi qaytar. Boshqa matn YOZMA.
2. LaTeX: \\\\frac, \\\\sqrt, \\\\cdot, \\\\left, \\\\right, \\\\leq (doim IKKI backslash)
3. has_image: savol matnida "rasm", "shakl", "chizma", "rasmdan", "berilgan" so'zlari bo'lsa TRUE
4. correct: faqat "A", "B", "C" yoki "D"
5. Barcha {num_ask} ta savolni ber

Format:
[
  {{
    "number": 1,
    "question": "Savol matni (formulalar: \\\\frac{{a}}{{b}}, \\\\sqrt{{x}}, \\\\left(x-1\\\\right))",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct": "B",
    "explanation": "Qisqa yechim",
    "has_image": false
  }}
]

MATN:
{text[:14000]}

RASMLAR TAVSIFI:
{img_desc if img_desc else "Rasm yo'q"}"""

    try:
        resp=client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{'role':'user','content':prompt}],
            temperature=0.05,
            max_tokens=8192,
        )
        raw=resp.choices[0].message.content.strip()

        with st.expander("🔍 AI javobi (debug)",expanded=False):
            st.code(raw[:3000],language="text")

        result=safe_json(raw)
        if result:
            if len(result)<num_ask:
                st.warning(f"⚠️ AI {len(result)}/{num_ask} ta savol qaytardi")
            else:
                st.success(f"✅ {len(result)} ta savol muvaffaqiyatli olindi!")
        else:
            st.error("❌ JSON parse qilinmadi. Debug ma'lumotini ko'ring.")
        return result or []
    except Exception as e:
        st.error(f"AI xatosi: {e}"); return []


# ══════════════════════════════════════════════════════
#  ✅ BUG-2 FIX: Rasmlarni savolga to'g'ri bog'lash
#  has_image=True bo'lgan savollar navbatma-navbat rasm oladi
# ══════════════════════════════════════════════════════
def build_image_map(questions:list, geo_imgs:list)->dict:
    image_map={}
    if not geo_imgs: return image_map

    # has_image=True bo'lgan savollar indekslari
    img_questions=[i for i,q in enumerate(questions) if q.get('has_image',False)]

    if not img_questions:
        # AI has_image ni to'ldirmagan bo'lsa — matn asosida aniqlash
        img_keywords=re.compile(r'rasm|shakl|chizma|rasmda|figura|berilgan|ko\'rsatilgan',re.I)
        img_questions=[i for i,q in enumerate(questions)
                       if img_keywords.search(q.get('question',''))]

    if not img_questions:
        # Hech narsa topilmasa — birinchi savolga ber
        image_map[0]=geo_imgs[:1]
        return image_map

    # Geometrik rasmlarni has_image savollariga navbatma-navbat taqsimlash
    for j, q_idx in enumerate(img_questions):
        if j < len(geo_imgs):
            image_map[q_idx] = [geo_imgs[j]]
        # Agar rasmlar ko'p bo'lsa (keyingi savol yo'q)
        if j == len(img_questions)-1 and j+1 < len(geo_imgs):
            image_map[q_idx] = geo_imgs[j:]  # qolgan barcha rasmlar

    return image_map


# ══════════════════════════════════════════════════════
#  Yordamchilar
# ══════════════════════════════════════════════════════
def grade(pct):
    if pct>=85: return "5 — A'lo 🥇"
    if pct>=70: return "4 — Yaxshi 🥈"
    if pct>=50: return "3 — Qoniqarli 🥉"
    return "2 — Qoniqarsiz 📚"

def fmt_time(sec):
    h,r=divmod(sec,3600);m,s=divmod(r,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ══════════════════════════════════════════════════════
#  Session state
# ══════════════════════════════════════════════════════
DEFAULTS={
    'questions':[],'current_q':0,'answers':{},
    'started':False,'finished':False,
    'name':'','surname':'',
    'duration':90,'start_time':None,
    'file_data':[],'image_map':{},
}
for k,v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k]=v


# ══════════════════════════════════════════════════════
#  Sidebar
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 👤 Foydalanuvchi")
    st.session_state.name    = st.text_input("Ism",      st.session_state.name)
    st.session_state.surname = st.text_input("Familiya", st.session_state.surname)
    st.markdown("---")
    st.markdown("### ⚙️ Sozlamalar")
    st.session_state.duration = st.number_input("⏱ Vaqt (daqiqa)",5,300,st.session_state.duration)
    st.markdown("---")
    st.markdown("### 📁 Test fayli")

    if not st.session_state.started:
        uploaded=st.file_uploader("Fayl yuklang (.docx yoki .pdf)",
                                   type=["docx","pdf"],accept_multiple_files=True)
        if uploaded:
            st.session_state.file_data=[
                {'name':f.name,'bytes':f.read()} for f in uploaded
            ]

    for fd in st.session_state.file_data:
        st.success(f"✅ {fd['name']}")

    if st.session_state.started and not st.session_state.finished:
        st.markdown("---")
        if st.button("⛔ Testni to'xtatish",use_container_width=True):
            st.session_state.finished=True;st.rerun()


# ══════════════════════════════════════════════════════
#  Asosiy sahifa
# ══════════════════════════════════════════════════════
st.title("🏆 OlimpTest — Matematika")
st.markdown("#### Matematika Olimpiada Mashq Platformasi")


# ─── BOSHLASH ───────────────────────────────────────
if not st.session_state.started:
    st.markdown("""
<div style="background:rgba(255,255,255,0.05);padding:20px;border-radius:12px;
            border:1px solid rgba(255,215,0,0.3);">
<h3>📋 Qo'llanma</h3>
<ol>
<li>Ism-familiyangizni kiriting</li>
<li>Word (.docx) yoki PDF matematika test faylini yuklang</li>
<li>Vaqt belgilang va testni boshlang</li>
<li>Formulalar (KaTeX) va rasmlar to'g'ri ko'rsatiladi</li>
</ol>
</div>""",unsafe_allow_html=True)

    ready=bool(st.session_state.file_data and st.session_state.name.strip())
    if not st.session_state.name.strip(): st.info("⬅️ Ismingizni kiriting")
    if not st.session_state.file_data:   st.info("⬅️ Fayl yuklang")

    if ready and st.button("🚀 Testni boshlash",type="primary",use_container_width=True):
        with st.spinner("📖 Fayl o'qilmoqda..."):
            all_text,all_images="",[]
            for fd in st.session_state.file_data:
                raw=fd['bytes']
                data=(extract_docx(raw) if fd['name'].lower().endswith('.docx')
                      else extract_pdf(raw))
                all_text+=data['text']+'\n\n'
                all_images+=data.get('images',[])

        if not all_text.strip():
            st.error("❌ Fayldan matn olinmadi.");st.stop()

        # Faqat geometrik rasmlarni ajratib olish
        geo_imgs=[]
        for img in all_images:
            try:
                arr=np.array(Image.open(io.BytesIO(img['bytes'])))
                if is_geometric_image(arr):
                    geo_imgs.append(img['bytes'])
            except: pass

        with st.spinner("🤖 AI matematika savollarni tahlil qilmoqda..."):
            questions=parse_questions_with_ai(all_text,[img['bytes'] for img in all_images],geo_imgs)

        if not questions:
            st.error("❌ Savollar tahlil qilinmadi.");st.stop()

        # ✅ BUG-2 FIX: To'g'ri rasm-savol bog'lash
        image_map=build_image_map(questions,geo_imgs)

        st.session_state.questions=questions
        st.session_state.image_map=image_map
        st.session_state.started=True
        st.session_state.start_time=time.time()
        st.session_state.current_q=0
        st.session_state.answers={}
        st.rerun()


# ─── TEST ───────────────────────────────────────────
elif not st.session_state.finished:
    st_autorefresh(interval=1000,key="math_timer")

    elapsed=time.time()-st.session_state.start_time
    remaining=max(0,int(st.session_state.duration*60-elapsed))
    if remaining==0:
        st.session_state.finished=True;st.rerun()

    questions=st.session_state.questions
    total_q=len(questions)
    q_idx=st.session_state.current_q
    q=questions[q_idx]

    # Header
    h1,h2,h3=st.columns([2,3,1])
    with h1: st.markdown(f"### 👤 {st.session_state.name} {st.session_state.surname}")
    with h2:
        ans_count=len(st.session_state.answers)
        st.progress(ans_count/total_q,text=f"Javob berilgan: {ans_count}/{total_q}")
    with h3:
        tcls="timer-urgent" if remaining<60 else "timer-box"
        st.markdown(f'<div class="{tcls}">⏱ {fmt_time(remaining)}</div>',unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"### Savol {q_idx+1} / {total_q}")

    # ✅ Savol matni — KaTeX render
    render_math_html(f"<b>{q.get('number',q_idx+1)}.</b> {q.get('question','Savol topilmadi')}",
                     font_size="20px")

    # ✅ BUG-2 FIX: Faqat shu savolning rasmi ko'rsatiladi
    if q_idx in st.session_state.image_map:
        st.markdown("### 🖼️ Rasm:")
        imgs=st.session_state.image_map[q_idx]
        cols=st.columns(min(2,len(imgs)))
        for ci,ib in enumerate(imgs):
            with cols[ci%2]:
                try:
                    st.image(Image.open(io.BytesIO(ib)),use_container_width=True)
                except: st.error("Rasm ko'rsatilmadi")

    st.markdown("---")

    # Variantlar
    options=q.get('options',{})
    opt_keys=list(options.keys())
    opt_labels=[f"{k}) {options[k]}" for k in opt_keys]
    prev_ans=st.session_state.answers.get(q_idx)
    prev_idx=opt_keys.index(prev_ans) if prev_ans in opt_keys else None

    st.markdown("**Javobingizni tanlang:**")
    chosen=st.radio("",options=opt_labels,index=prev_idx,
                    label_visibility="collapsed",key=f"r_{q_idx}")
    if chosen:
        st.session_state.answers[q_idx]=chosen.split(")")[0].strip()

    # KaTeX ko'rinishi
    with st.expander("🔍 Formulalar bilan ko'rish"):
        for k in opt_keys:
            bg="rgba(255,215,0,0.1)" if st.session_state.answers.get(q_idx)==k else "transparent"
            render_math_html(f"<b>{k})</b> {options[k]}",font_size="17px",bg=bg)

    # Navigatsiya
    n1,n2,n3=st.columns(3)
    with n1:
        if q_idx>0 and st.button("⬅️ Oldingi",use_container_width=True):
            st.session_state.current_q-=1;st.rerun()
    with n2:
        if q_idx<total_q-1 and st.button("Keyingi ➡️",use_container_width=True):
            st.session_state.current_q+=1;st.rerun()
    with n3:
        if st.button("✅ Yakunlash",type="primary",use_container_width=True):
            st.session_state.finished=True;st.rerun()

    st.markdown("---")
    st.markdown("**Savollar paneli:**")
    for rs in range(0,total_q,10):
        row=list(range(rs,min(rs+10,total_q)))
        cols=st.columns(len(row))
        for col,i in zip(cols,row):
            with col:
                lbl=f"✓{i+1}" if i in st.session_state.answers else str(i+1)
                bt="primary" if i==q_idx else "secondary"
                if st.button(lbl,key=f"nav_{i}",type=bt,use_container_width=True):
                    st.session_state.current_q=i;st.rerun()


# ─── NATIJA ─────────────────────────────────────────
else:
    questions=st.session_state.questions
    total_q=len(questions)
    correct=sum(1 for i,q in enumerate(questions)
                if st.session_state.answers.get(i)==q.get('correct'))
    pct=(correct/total_q*100) if total_q else 0.0

    st.markdown("## 🎉 Test yakunlandi!")
    st.markdown(f"**{st.session_state.name} {st.session_state.surname}**")

    c1,c2,c3,c4=st.columns(4)
    c1.metric("✅ To'g'ri",   f"{correct}/{total_q}")
    c2.metric("❌ Noto'g'ri", f"{total_q-correct}/{total_q}")
    c3.metric("📊 Foiz",      f"{pct:.1f}%")
    c4.metric("🎓 Baho",      grade(pct))

    color="#2ECC71" if pct>=70 else "#E67E22" if pct>=50 else "#E74C3C"
    st.markdown(
        f'<div style="background:{color};padding:18px;border-radius:12px;'
        f'text-align:center;color:white;font-size:22px;font-weight:bold;margin:16px 0;">'
        f'Natija: {pct:.1f}% — {grade(pct)}</div>',
        unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Batafsil natijalar")
    for i,q in enumerate(questions):
        user_ans=st.session_state.answers.get(i)
        correct_ans=q.get('correct','?')
        ok=user_ans==correct_ans
        icon="✅" if ok else ("❌" if user_ans else "⬜")
        with st.expander(f"{icon} Savol {i+1}  |  Siz: {user_ans or '—'}  |  To'g'ri: {correct_ans}"):
            render_math_html(f"<b>Savol:</b> {q['question']}")
            for k,v in q.get('options',{}).items():
                if k==correct_ans:   render_math_html(f"✅ <b>{k})</b> {v}",bg="rgba(46,204,113,0.15)")
                elif k==user_ans:    render_math_html(f"❌ <b>{k})</b> {v}",bg="rgba(231,76,60,0.15)")
                else:                render_math_html(f"&nbsp;&nbsp;{k}) {v}",bg="transparent")
            if q.get('explanation'):
                st.info(f"💡 **Yechim:** {q['explanation']}")

    if st.button("🔄 Yangi test",type="primary",use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

st.markdown("---")
st.markdown("<p style='text-align:center;color:#888;font-size:12px;'>Yaratuvchi: Usmonov Sodiq</p>",
            unsafe_allow_html=True)
