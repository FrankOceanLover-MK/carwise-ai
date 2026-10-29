import base64
import html
import re
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image
from components.utils import (
    health,
    ask_chat,
    ApiError,
    DEFAULT_BASE,
)

ASSETS = Path(__file__).resolve().parent / "assets"
BOT_AVATAR = str(ASSETS / "carwise.png")
USER_AVATAR_B64 = base64.b64encode((ASSETS / "user.png").read_bytes()).decode()
BOT_AVATAR_B64 = base64.b64encode((ASSETS / "carwise.png").read_bytes()).decode()

st.set_page_config(
    page_title="Carwise AI - Your Smart Car Shopping Assistant",
    page_icon=Image.open(BOT_AVATAR),
    layout="centered",
    initial_sidebar_state="collapsed",
)

QUICK_PROMPTS = [
    ("Family SUV under $30k", "I need a reliable family SUV with good safety ratings under $30,000"),
    ("Fuel-efficient sedan", "Show me fuel-efficient sedans with at least 35 MPG"),
    ("Pickup trucks under $35k", "Show me pickup trucks under $35,000 with low mileage"),
    ("Best value under $20k", "What are the best value used cars under $20,000 with low mileage?"),
]

# Original line-art car mark, used as the logo and as the "no photo" placeholder
LOGO_SVG = (
    '<svg viewBox="0 0 128 128" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<rect width="128" height="128" rx="30" fill="#4f46e5"/>'
    '<rect x="20" y="62" width="88" height="26" rx="9" fill="#fff"/>'
    '<polygon points="36,62 49,40 82,40 97,62" fill="#fff"/>'
    '<polygon points="46,60 54,45 65,45 65,60" fill="#4f46e5"/>'
    '<polygon points="70,60 70,45 80,45 90,60" fill="#4f46e5"/>'
    '<circle cx="40" cy="88" r="11" fill="#4f46e5"/><circle cx="40" cy="88" r="8" fill="#fff"/><circle cx="40" cy="88" r="3" fill="#4f46e5"/>'
    '<circle cx="88" cy="88" r="11" fill="#4f46e5"/><circle cx="88" cy="88" r="8" fill="#fff"/><circle cx="88" cy="88" r="3" fill="#4f46e5"/>'
    "</svg>"
)
PLACEHOLDER_SVG = (
    '<svg viewBox="0 0 128 128" width="64" height="64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<rect x="14" y="62" width="100" height="26" rx="10" fill="#a5b4fc"/>'
    '<polygon points="34,62 48,38 84,38 100,62" fill="#a5b4fc"/>'
    '<circle cx="38" cy="88" r="12" fill="#818cf8"/><circle cx="90" cy="88" r="12" fill="#818cf8"/>'
    "</svg>"
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* ---------- Base ---------- */
    .stApp { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; }
    [data-testid="stHeader"] { background: transparent; pointer-events: none; }
    [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
    #MainMenu, footer { visibility: hidden; }
    .block-container, [data-testid="stBottomBlockContainer"] {
        max-width: 920px !important; padding-left: 1.5rem !important; padding-right: 1.5rem !important;
    }
    .block-container { padding-top: 1.5rem !important; padding-bottom: 7rem !important; }
    [data-testid="stBottom"], [data-testid="stBottom"] > div { background: transparent !important; }

    /* The scroll helper is an invisible 0px iframe; take it out of the layout flow */
    .element-container:has(iframe[height="0"]) { position: absolute; height: 0; width: 0; margin: 0; overflow: hidden; }
    /* Chat view: the empty placeholder above the header adds a gap, so tighten the top padding */
    .stApp:has(.brand) .block-container { padding-top: .5rem !important; }

    /* ---------- Header ---------- */
    .brand { display: flex; align-items: center; gap: .7rem; font-size: 1.35rem; font-weight: 800; color: #fff; padding-top: .35rem; }
    .brand svg { flex: none; border-radius: 9px; }

    /* ---------- Landing ---------- */
    .hero { text-align: center; padding: 7vh 0 1.6rem 0; }
    .hero svg { border-radius: 18px; box-shadow: 0 8px 24px rgba(31,38,135,.35); }
    .hero h1 { font-size: 2.6rem; font-weight: 800; margin: 1rem 0 .4rem 0; padding: 0; color: #fff; }
    .hero p { font-size: 1.1rem; opacity: .9; margin: 0 auto; max-width: 34rem; line-height: 1.5; }
    .section-label { text-align: center; font-size: .8rem; letter-spacing: .08em; text-transform: uppercase; opacity: .75; margin: 2rem 0 .7rem 0; font-weight: 700; }
    .features { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-top: 2.2rem; }
    .feature { background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.18); border-radius: 14px; padding: 1rem 1.1rem; }
    .feature b { display: block; font-size: .98rem; margin-bottom: .25rem; }
    .feature span { font-size: .88rem; opacity: .85; line-height: 1.45; }
    @media (max-width: 700px) { .features { grid-template-columns: 1fr; } }

    /* ---------- Inputs: glass, matching the theme ---------- */
    /* Streamlit wraps the <input> in two styled boxes; restyle the outer ones, not just the input */
    [data-testid="stTextInput"] [data-baseweb="input"] {
        background: rgba(255,255,255,.18) !important; border: 1px solid rgba(255,255,255,.4) !important;
        border-radius: 14px !important; box-shadow: none !important; backdrop-filter: blur(8px);
    }
    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
        border-color: #fff !important; box-shadow: 0 0 0 3px rgba(255,255,255,.22) !important;
    }
    [data-testid="stTextInput"] [data-baseweb="base-input"] { background: transparent !important; border-radius: 14px !important; }
    [data-testid="stTextInput"] input {
        background: transparent !important; color: #fff !important; border: none !important;
        padding: .8rem 1rem !important; caret-color: #fff;
    }
    [data-testid="stTextInput"] input::placeholder { color: rgba(255,255,255,.75) !important; }
    [data-testid="stTextInput"] [data-testid="InputInstructions"] { display: none; }
    /* Attach the ZIP helper to the input itself, with no separate Streamlit block gap. */
    .stApp:has(.hero) [data-testid="stTextInput"]::after {
        content: "Enter your ZIP code to find cars near you.";
        display: block;
        width: 100%;
        box-sizing: border-box;
        text-align: center;
        font-size: .9rem;
        line-height: 1.4;
        color: rgba(255,255,255,.85);
        margin-top: .35rem;
        padding: 0 .35rem;
        white-space: normal;
    }

    [data-testid="stChatInput"] {
        background: rgba(255,255,255,.18) !important; border: 1px solid rgba(255,255,255,.4) !important;
        border-radius: 16px !important; backdrop-filter: blur(10px); box-shadow: 0 8px 28px rgba(31,38,135,.25);
    }
    [data-testid="stChatInput"] > div, [data-testid="stChatInput"] div[data-baseweb] { background: transparent !important; border: none !important; }
    [data-testid="stChatInput"]:focus-within { border-color: #fff !important; box-shadow: 0 0 0 3px rgba(255,255,255,.22), 0 8px 28px rgba(31,38,135,.25); }
    [data-testid="stChatInput"] textarea { color: #fff !important; background: transparent !important; caret-color: #fff; }
    [data-testid="stChatInput"] textarea::placeholder { color: rgba(255,255,255,.72) !important; }
    [data-testid="stChatInput"] button { background: transparent !important; color: #fff !important; }
    [data-testid="stChatInput"] button:disabled { opacity: .5; }

    /* ---------- Buttons ---------- */
    .stButton > button {
        background: rgba(255,255,255,.14) !important; color: #fff !important;
        border: 1px solid rgba(255,255,255,.35) !important; border-radius: 14px !important;
        font-weight: 600 !important; width: 100%; min-height: 3.1rem; padding: .6rem .9rem !important;
        transition: background .15s ease, transform .15s ease;
    }
    .stButton > button:hover { background: rgba(255,255,255,.28) !important; border-color: #fff !important; transform: translateY(-1px); }
    .stButton > button:focus-visible { outline: 3px solid rgba(255,255,255,.6) !important; }

    /* ---------- Conversation ---------- */
    /* One padding value (1.25rem) is used inside the box and between the cards, so spacing is even */
    .bot-msg {
        background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.2); border-radius: 18px;
        padding: 1.25rem; margin: 0 0 1.25rem 0;
    }
    .bot-head { display: flex; align-items: flex-start; gap: .9rem; }
    .bot-head > img { width: 36px; height: 36px; border-radius: 10px; flex: none; }
    .bot-text { flex: 1; min-width: 0; padding-top: .15rem; }
    .bot-text p { font-size: 1.02rem; line-height: 1.6; margin: 0 0 .65rem 0 !important; }
    .bot-text p:last-child { margin-bottom: 0 !important; }
    .typing { display: flex; align-items: center; gap: .4rem; padding: .5rem 0; }
    .typing span { width: 8px; height: 8px; border-radius: 50%; background: #fff; opacity: .3; animation: blink 1.2s infinite ease-in-out; }
    .typing span:nth-child(2) { animation-delay: .2s; }
    .typing span:nth-child(3) { animation-delay: .4s; }
    .typing em { margin-left: .5rem; opacity: .85; font-size: .95rem; }
    @keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
    .user-row { scroll-margin-top: 4.5rem; display: flex; justify-content: flex-end; align-items: center; gap: .75rem; margin: 1.3rem 0 1.1rem 0; }
    .user-bubble {
        background: rgba(255,255,255,.26); border: 1px solid rgba(255,255,255,.34);
        border-radius: 18px 18px 4px 18px; padding: .75rem 1.15rem; max-width: 78%;
        font-size: 1.02rem; line-height: 1.5; word-wrap: break-word;
    }
    .user-row img { width: 36px; height: 36px; border-radius: 10px; flex: none; }

    /* ---------- Listing cards: uniform grid, whole card is a link ---------- */
    .car-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1.25rem; margin-top: 1.25rem; }
    @media (max-width: 760px) { .car-grid { grid-template-columns: 1fr; } }
    .car-card {
        position: relative; display: flex; flex-direction: column; background: #fff; color: #1f2937;
        border-radius: 16px; overflow: hidden; box-shadow: 0 6px 20px rgba(31,38,135,.28);
        transition: transform .15s ease, box-shadow .15s ease;
    }
    .car-card:hover { transform: translateY(-3px); box-shadow: 0 12px 28px rgba(31,38,135,.42); }
    .card-link { position: absolute; inset: 0; z-index: 3; }
    .car-photo { position: relative; aspect-ratio: 4 / 3; background: linear-gradient(135deg, #eef2ff, #e0e7ff); display: flex; align-items: center; justify-content: center; }
    .car-photo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
    .pill { position: absolute; top: .6rem; z-index: 2; border-radius: 999px; padding: .2rem .65rem; font-size: .75rem; font-weight: 700; }
    .pill-rank { left: .6rem; background: #111827; color: #fff; }
    .pill-match { right: .6rem; background: #dcfce7; color: #166534; }
    .car-body { padding: 1rem 1.1rem 1.1rem; display: flex; flex-direction: column; flex: 1; }
    .car-title { font-size: 1.05rem; font-weight: 700; color: #111827; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 2.6em; }
    .car-sub { font-size: .82rem; color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 1.3em; margin-top: .1rem; }
    .car-price { font-size: 1.55rem; font-weight: 800; color: #4f46e5; margin: .55rem 0 .5rem 0; }
    .spec { display: flex; justify-content: space-between; gap: .5rem; font-size: .88rem; padding: .35rem 0; border-top: 1px solid #eef0f5; }
    .spec span { color: #6b7280; }
    .spec b { color: #111827; font-weight: 600; text-align: right; }
    .cta-wrap { margin-top: auto; padding-top: .9rem; }
    .car-cta { text-align: center; background: #4f46e5; color: #fff; border-radius: 10px; padding: .55rem; font-weight: 700; font-size: .9rem; }
    .car-cta-off { background: #e5e7eb; color: #6b7280; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_md(text: str) -> str:
    """Escape dollar signs so Streamlit doesn't render "$24,600 ... $27,000" as LaTeX math."""
    return text.replace("$", r"\$")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True) if value not in (None, "") else ""


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def listing_card_html(car: Dict[str, Any], rank: int) -> str:
    """One listing card. Single-line HTML (so the Markdown parser leaves it alone); values escaped."""
    title = " ".join(str(x) for x in (car.get("year"), car.get("make"), car.get("model")) if x) or "Vehicle"
    sub = " · ".join(esc(x) for x in (car.get("trim"), car.get("dealer")) if x) or " "

    price = _num(car.get("price"))
    price_html = f"&#36;{price:,.0f}" if price is not None else "Price unavailable"

    mileage, distance = _num(car.get("mileage")), _num(car.get("distance_miles"))
    city_mpg, hwy_mpg = _num(car.get("city_mpg")), _num(car.get("highway_mpg"))
    safety = _num(car.get("safety_rating"))
    place = ", ".join(str(x) for x in (car.get("city"), car.get("state")) if x)

    # Only rows we actually have data for, most useful first (no columns of dashes)
    rows = []
    if mileage is not None:
        rows.append(("Mileage", f"{mileage:,.0f} mi"))
    if distance is not None:
        rows.append(("Distance", f"{distance:,.0f} mi away"))
    elif place:
        rows.append(("Location", esc(place)))
    if car.get("fuel_type"):
        rows.append(("Fuel", esc(car["fuel_type"])))
    if car.get("body_style"):
        rows.append(("Body", esc(car["body_style"])))
    if city_mpg is not None and hwy_mpg is not None:
        rows.append(("MPG", f"{city_mpg:.0f} city / {hwy_mpg:.0f} hwy"))
    if safety is not None:
        rows.append(("Safety", f"{safety:.0f} of 5 stars"))
    specs_html = "".join(f'<div class="spec"><span>{k}</span><b>{v}</b></div>' for k, v in rows[:5])

    match = car.get("match_score")
    match_pill = f'<span class="pill pill-match">{esc(match)}% match</span>' if match is not None else ""
    image_url = car.get("image_url")
    img = f'<img src="{esc(image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if _is_url(image_url) else ""

    url = car.get("listing_url")
    if _is_url(url):
        link = (
            f'<a class="card-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
            f'aria-label="Open listing for {esc(title)}"></a>'
        )
        cta = '<div class="cta-wrap"><div class="car-cta">View listing</div></div>'
    else:
        link = ""
        cta = '<div class="cta-wrap"><div class="car-cta car-cta-off">Listing link unavailable</div></div>'

    return (
        f'<div class="car-card">{link}'
        f'<div class="car-photo">{PLACEHOLDER_SVG}{img}<span class="pill pill-rank">#{rank}</span>{match_pill}</div>'
        f'<div class="car-body"><div class="car-title">{esc(title)}</div><div class="car-sub">{sub}</div>'
        f'<div class="car-price">{price_html}</div>{specs_html}{cta}</div></div>'
    )


def paragraphs_html(text: str) -> str:
    """Plain LLM text -> escaped <p> tags. '$' becomes an entity so Streamlit never treats it as math."""
    t = esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = t.replace("$", "&#36;")
    parts = [p.strip() for p in re.split(r"\n+", t) if p.strip()]
    return "".join(f"<p>{p}</p>" for p in parts)


def user_html(content: str, anchor: bool = False) -> str:
    anchor_attr = ' id="last-user-msg"' if anchor else ""
    return (
        f'<div class="user-row"{anchor_attr}><div class="user-bubble">{esc(content)}</div>'
        f'<img src="data:image/png;base64,{USER_AVATAR_B64}" alt="You"></div>'
    )


def bot_html(msg: Optional[Dict[str, Any]] = None, thinking: bool = False) -> str:
    """The assistant bubble as one HTML block: avatar + text on top, listing cards full-width below."""
    grid = ""
    if thinking:
        body = '<div class="typing"><span></span><span></span><span></span><em>Searching live listings...</em></div>'
    else:
        body = paragraphs_html((msg or {}).get("content", ""))
        listings = (msg or {}).get("listings") or []
        if listings:
            cards = "".join(listing_card_html(car, i) for i, car in enumerate(listings[:3], 1))
            grid = f'<div class="car-grid">{cards}</div>'
    return (
        f'<div class="bot-msg"><div class="bot-head">'
        f'<img src="data:image/png;base64,{BOT_AVATAR_B64}" alt="Carwise AI">'
        f'<div class="bot-text">{body}</div></div>{grid}</div>'
    )


def scroll_to_last_user() -> None:
    """Bring the newest question to the top of the view (invisible 0px helper)."""
    n = len(st.session_state.chat_messages)  # changes every time, so the script re-runs
    components.html(
        f"""<script>/* {n} */
        let tries = 0;
        const go = () => {{
            const el = window.parent.document.getElementById('last-user-msg');
            if (el) {{ el.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
            else if (tries++ < 15) {{ setTimeout(go, 80); }}
        }};
        go();
        </script>""",
        height=0,
    )


def get_reply(zip_code: Optional[str]) -> Dict[str, Any]:
    msgs = st.session_state.chat_messages
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in msgs[:-1]
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ][-10:]
    try:
        reply = ask_chat(msgs[-1]["content"], vin=None, history=history, zip_code=zip_code)
        return {
            "role": "assistant",
            "content": reply.get("answer", "I couldn't find a suitable response."),
            "listings": reply.get("listings") or [],
        }
    except ApiError as e:
        return {"role": "assistant", "content": f"Sorry, I ran into an error: {e.message}"}
    except Exception:
        return {
            "role": "assistant",
            "content": "I'm having trouble reaching the search service. Please make sure the backend is running.",
        }


def zip_box(container) -> Optional[str]:
    """ZIP input; returns a valid 5-digit ZIP or None."""
    value = container.text_input(
        "ZIP code",
        key="zip_code",
        max_chars=5,
        placeholder="ZIP for local listings",
        label_visibility="collapsed",
        help="Used for 'near me' searches.",
    ).strip()
    if re.fullmatch(r"\d{5}", value):
        return value
    if value:
        container.caption("Enter a 5-digit ZIP.")
    return None


def start_query(text: str) -> None:
    st.session_state.chat_messages.append({"role": "user", "content": text})
    st.session_state.needs_reply = True


def submit_from_box(key: str) -> None:
    """Callback for the chat boxes: runs before the page reruns, so no extra st.rerun() is needed."""
    text = (st.session_state.get(key) or "").strip()
    if text:
        start_query(text)


def new_chat() -> None:
    st.session_state.chat_messages = []
    st.session_state.needs_reply = False


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
st.session_state.setdefault("chat_messages", [])
st.session_state.setdefault("needs_reply", False)
if "backend_healthy" not in st.session_state:
    try:
        st.session_state.backend_info = health()
        st.session_state.backend_healthy = True
    except Exception:
        st.session_state.backend_info = {}
        st.session_state.backend_healthy = False

if not st.session_state.backend_healthy:
    st.error("Backend is not reachable. Start it with `uvicorn app.main:app --reload`, then refresh.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Settings")
    st.markdown("### AI model")
    st.info(f"Using {st.session_state.backend_info.get('model', 'an open-source LLM')}")
    st.markdown("### Backend")
    st.success("Connected")
    st.caption(f"URL: {DEFAULT_BASE}")

# Everything on the landing page lives in this one slot. In the chat view the slot is simply empty,
# so the landing content disappears immediately instead of lingering (faded) while a search runs.
landing_slot = st.empty()

# ---------------------------------------------------------------------------
# Landing page (no messages yet)
# ---------------------------------------------------------------------------
if not st.session_state.chat_messages:
    with landing_slot.container():
        st.markdown(
            f'<div class="hero">{LOGO_SVG.format(size=64)}<h1>Carwise AI</h1>'
            "<p>Describe the car you want. I'll search live listings and rank the best matches for you.</p></div>",
            unsafe_allow_html=True,
        )

        col_input, col_zip = st.columns([3.6, 1.6])
        with col_input:
            st.chat_input(
                "Describe the car you're looking for...",
                key="landing_box",
                on_submit=submit_from_box,
                args=("landing_box",),
            )
        with col_zip:
            zip_box(st)

        st.markdown('<div class="section-label">Try one of these</div>', unsafe_allow_html=True)
        for row in (QUICK_PROMPTS[:2], QUICK_PROMPTS[2:]):
            for col, (label, prompt) in zip(st.columns(2), row):
                col.button(label, key=f"chip_{label}", on_click=start_query, args=(prompt,))

        st.markdown(
            '<div class="features">'
            '<div class="feature"><b>Live listings</b><span>Pulled from dealers across the U.S. as you search.</span></div>'
            '<div class="feature"><b>Ranked for you</b><span>Scored on price, mileage, fuel economy, distance and safety.</span></div>'
            '<div class="feature"><b>One click to the dealer</b><span>Every match links straight to the original listing.</span></div>'
            "</div>",
            unsafe_allow_html=True,
        )
    st.stop()

# ---------------------------------------------------------------------------
# Conversation view
# ---------------------------------------------------------------------------
head_brand, head_zip, head_new = st.columns([2.6, 2, 1.3])
head_brand.markdown(f'<div class="brand">{LOGO_SVG.format(size=34)}Carwise AI</div>', unsafe_allow_html=True)
zip_code = zip_box(head_zip)
head_new.button("New chat", key="new_chat", on_click=new_chat)

messages = st.session_state.chat_messages
last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
for i, msg in enumerate(messages):
    html_block = user_html(msg["content"], anchor=(i == last_user)) if msg["role"] == "user" else bot_html(msg)
    st.markdown(html_block, unsafe_allow_html=True)

if st.session_state.needs_reply:
    # Show a "thinking" bubble, then replace it in place with the answer (no layout jump).
    reply_slot = st.empty()
    reply_slot.markdown(bot_html(thinking=True), unsafe_allow_html=True)
    scroll_to_last_user()
    reply_msg = get_reply(zip_code)
    reply_slot.markdown(bot_html(reply_msg), unsafe_allow_html=True)
    st.session_state.chat_messages.append(reply_msg)
    st.session_state.needs_reply = False

st.chat_input(
    "Ask a follow-up or describe another car...",
    key="chat_box",
    on_submit=submit_from_box,
    args=("chat_box",),
)