"""
Interface Streamlit — Acompanhamento Legislativo da ALERJ.
Execute com:  streamlit run app.py
"""

import math
import time
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import streamlit as st
import pandas as pd

import requests as _requests
from bs4 import BeautifulSoup as _BS

import database as db
from scraper import ALERJScraper, LOG_FILE, LEGISLATURAS, _extract_pareceres, _extract_andamento, HEADERS

# ---------------------------------------------------------------------------
# Thread-safe live state — @st.cache_resource cria o objeto UMA VEZ e
# reutiliza nas reruns; o dict nu é modificado in-place pelo thread sem
# passar pelo proxy do session_state.
# ---------------------------------------------------------------------------
@st.cache_resource
def _get_coleta_state():
    return (
        {
            "scraping":     False,
            "log_lines":    [],
            "prog_current": 0,
            "prog_total":   0,
            "prog_stats":   {},
            "fase_texto":   "Aguardando início...",
            "fase_tipo":    "info",
            "sync_result":  None,
            "sync_error":   None,
        },
        threading.Lock(),
    )

_coleta_live, _coleta_log_lock = _get_coleta_state()

# ---------------------------------------------------------------------------
# Configuração geral
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_tramitacao_ao_vivo(url: str) -> dict:
    """Busca pareceres e andamento diretamente no site da ALERJ. Cache de 30 min."""
    try:
        r = _requests.get(url, timeout=20, headers=HEADERS)
        soup = _BS(r.content, "lxml")
        return {
            "pareceres": _extract_pareceres(soup),
            "andamento": _extract_andamento(soup),
            "ok": True,
        }
    except Exception as e:
        return {"pareceres": [], "andamento": [], "ok": False, "erro": str(e)}

db.init_db()

st.set_page_config(
    page_title="ALERJ — Acompanhamento Legislativo",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

TODAS_LEGISLATURAS = list(LEGISLATURAS.keys())   # ["2023-2027", "2019-2023", ...]

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* ── Base ─────────────────────────────────────────────────────────────────── */
[data-testid="stApp"] { background-color: #0a0a0f; }
.main .block-container  { padding-top: 2rem; padding-left: 2rem; padding-right: 2rem; max-width: 1400px; }

/* ── Sidebar ──────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] { background-color: #0d0d17 !important; border-right: 1px solid #1a1a2e; }
[data-testid="stSidebarContent"] { padding-top: 1.5rem; }

.sidebar-brand { display:flex; align-items:center; gap:10px; padding:0 4px 2px 4px; }
.brand-icon    { font-size:1.8rem; }
.brand-text    { font-size:1.35rem; font-weight:700; color:#f4f4f5; letter-spacing:-0.5px; }
.brand-caption { font-size:0.7rem; color:#52525b; padding:0 4px; margin:0 0 4px 0; }

/* ── Sidebar nav radio ────────────────────────────────────────────────────── */
[data-testid="stSidebar"] .stRadio [data-testid="stWidgetLabel"] { display:none; }
[data-testid="stSidebar"] .stRadio > div { display:flex; flex-direction:column; gap:2px; }
[data-testid="stSidebar"] .stRadio label {
    padding: 10px 12px !important; border-radius: 8px !important;
    color: #71717a !important; font-size: 0.88rem !important;
    font-weight: 500 !important; cursor: pointer !important;
    transition: all 0.15s ease !important; margin: 0 !important;
}
[data-testid="stSidebar"] .stRadio label:hover { background:#1a1a2e !important; color:#a1a1aa !important; }
[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] > div:first-child { display:none !important; }
[data-testid="stSidebar"] .stRadio [data-checked="true"] ~ div,
[data-testid="stSidebar"] .stRadio [aria-checked="true"] { color:#10b981 !important; }
[data-testid="stSidebar"] .stRadio [data-checked="true"] + label,
[data-testid="stSidebar"] .stRadio input:checked + div + div { color:#10b981 !important; }

/* ── Metric cards ─────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background:#12121a !important; border:1px solid #1a1a2e !important;
    border-radius:12px !important; padding:18px 22px !important;
}
[data-testid="stMetricLabel"] p { color:#71717a !important; font-size:0.75rem !important; text-transform:uppercase; letter-spacing:.06em; }
[data-testid="stMetricValue"]   { color:#f4f4f5 !important; font-size:2rem !important; font-weight:700 !important; }

/* ── Containers / borders ─────────────────────────────────────────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background:#12121a !important; border-color:#1a1a2e !important; border-radius:12px !important;
}

/* ── Expanders ────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] { background:#12121a !important; border:1px solid #1a1a2e !important; border-radius:12px !important; }
[data-testid="stExpander"] summary { color:#a1a1aa !important; }

/* ── Buttons ──────────────────────────────────────────────────────────────── */
.stButton > button { border-radius:8px !important; font-weight:500 !important; transition:all .15s !important; }
.stButton > button[kind="primary"]   { background:#10b981 !important; border-color:#10b981 !important; color:#fff !important; }
.stButton > button[kind="primary"]:hover { background:#059669 !important; border-color:#059669 !important; }
.stButton > button[kind="secondary"] { background:#12121a !important; border-color:#1a1a2e !important; color:#a1a1aa !important; }
.stButton > button[kind="secondary"]:hover { background:#1a1a2e !important; color:#f4f4f5 !important; }
[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] .stDownloadButton button {
    background:#12121a !important; border:1px solid #1a1a2e !important;
    color:#a1a1aa !important; border-radius:8px !important; font-size:.82rem !important;
}
[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] .stDownloadButton button:hover { background:#1a1a2e !important; color:#f4f4f5 !important; }

/* ── Inputs ───────────────────────────────────────────────────────────────── */
.stTextInput input  { background:#12121a !important; border-color:#1a1a2e !important; color:#f4f4f5 !important; border-radius:8px !important; }
.stTextInput input:focus { border-color:#10b981 !important; box-shadow:0 0 0 1px #10b981 !important; }
.stSelectbox [data-baseweb="select"] > div { background:#12121a !important; border-color:#1a1a2e !important; border-radius:8px !important; }
.stMultiSelect [data-baseweb="select"] > div { background:#12121a !important; border-color:#1a1a2e !important; border-radius:8px !important; }

/* ── Slider / Progress ────────────────────────────────────────────────────── */
.stProgress [data-baseweb="progress-bar"] > div { background:#10b981 !important; }

/* ── Tabs (sub-tabs internas) ─────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] { background:#12121a !important; border-bottom:1px solid #1a1a2e !important; padding:6px 8px !important; border-radius:10px 10px 0 0; }
[data-testid="stTabs"] button[role="tab"] { background:transparent !important; color:#71717a !important; border-radius:6px !important; border:none !important; padding:10px 28px !important; font-size:0.88rem !important; min-width:120px !important; margin:0 4px !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { background:#1a1a2e !important; color:#10b981 !important; }

/* ── DataFrames ───────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius:12px !important; overflow:hidden !important; border:1px solid #1a1a2e !important; }

/* ── File uploader ────────────────────────────────────────────────────────── */
[data-testid="stFileUploaderDropzone"] { background:#12121a !important; border-color:#1a1a2e !important; border-radius:10px !important; }

/* ── Divider / HR ─────────────────────────────────────────────────────────── */
hr { border-color:#1a1a2e !important; }

/* ── Alerts ───────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius:10px !important; }

/* ── Log / phase / tramitação boxes ──────────────────────────────────────── */
.log-box {
    background:#0d0d15; color:#e6edf3;
    font-family:'Courier New',monospace; font-size:12px;
    padding:12px; border-radius:10px; max-height:380px;
    overflow-y:auto; white-space:pre-wrap; word-break:break-all;
    border:1px solid #1a1a2e;
}
.log-line-novo       { color:#10b981; }
.log-line-atualizado { color:#60a5fa; }
.log-line-erro       { color:#f87171; }
.log-line-aviso      { color:#fb923c; }
.log-line-info       { color:#52525b; }
.phase-box      { background:#12121a; border-left:4px solid #60a5fa;
                  padding:10px 14px; border-radius:8px; border:1px solid #1a1a2e;
                  font-family:'Courier New',monospace; font-size:13px;
                  color:#e6edf3; margin-bottom:8px; }
.phase-box-ok   { border-left-color:#10b981; }
.phase-box-erro { border-left-color:#f87171; }

/* ── Loading animado ──────────────────────────────────────────────────────── */
@keyframes pulse-ring {
  0%   { box-shadow:0 0 0 0 rgba(16,185,129,.55); }
  70%  { box-shadow:0 0 0 10px rgba(16,185,129,0); }
  100% { box-shadow:0 0 0 0 rgba(16,185,129,0); }
}
@keyframes fade-in { from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;} }
@keyframes indeterminate { 0%{transform:translateX(-100%);}100%{transform:translateX(400%);} }

.loading-card {
  background:#12121a; border:1px solid #1a1a2e; border-radius:14px;
  padding:22px 26px; margin:12px 0; animation:fade-in .3s ease;
}
.loading-header { display:flex; align-items:center; gap:12px; margin-bottom:18px; }
.pulse-dot { width:12px; height:12px; border-radius:50%; background:#10b981;
             flex-shrink:0; animation:pulse-ring 1.4s ease-out infinite; }
.loading-title { font-size:0.95rem; font-weight:600; color:#f4f4f5; line-height:1.3; }
.loading-sub   { font-size:0.75rem; color:#71717a; margin-top:2px; max-width:700px;
                 overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

.stepper { display:flex; align-items:center; margin-bottom:18px; }
.stp { text-align:center; }
.stp-circle { width:34px; height:34px; border-radius:50%; display:flex;
              align-items:center; justify-content:center;
              font-size:0.85rem; font-weight:700; margin:0 auto 5px; }
.stp-lbl { font-size:0.7rem; line-height:1.35; white-space:nowrap; }
.stp-wait   .stp-circle { background:#0d0d17; color:#3f3f46; border:2px solid #1a1a2e; }
.stp-wait   .stp-lbl    { color:#3f3f46; }
.stp-active .stp-circle { background:#10b981; color:#fff; border:2px solid #10b981;
                           animation:pulse-ring 1.4s infinite; }
.stp-active .stp-lbl    { color:#10b981; font-weight:600; }
.stp-done   .stp-circle { background:#1e3a2f; color:#10b981; border:2px solid #1e3a2f; }
.stp-done   .stp-lbl    { color:#52525b; }
.stp-erro   .stp-circle { background:#3b1111; color:#f87171; border:2px solid #3b1111; }
.stp-erro   .stp-lbl    { color:#f87171; }
.stp-line      { flex:1; height:2px; background:#1a1a2e; margin:0 8px 24px; min-width:20px; }
.stp-line-done { flex:1; height:2px; background:#1e3a2f; margin:0 8px 24px; min-width:20px; }

.prog-wrap { background:#0d0d17; border-radius:6px; height:7px; margin:10px 0 4px; overflow:hidden; }
.prog-fill  { height:100%; border-radius:6px;
              background:linear-gradient(90deg,#10b981,#34d399);
              transition:width .5s ease; }
.prog-label { font-size:0.75rem; color:#52525b; }

.stat-row  { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }
.stat-chip { display:flex; align-items:center; gap:6px;
             background:#0d0d17; border:1px solid #1a1a2e;
             border-radius:20px; padding:5px 13px; font-size:0.8rem; color:#a1a1aa; }
.stat-chip-val { font-weight:700; font-size:0.95rem; }
.c-green  { color:#10b981; }
.c-blue   { color:#60a5fa; }
.c-red    { color:#f87171; }
.c-purple { color:#a78bfa; }
.c-orange { color:#fb923c; }
.tram-box {
    background:#0d0d15; border:1px solid #1a1a2e; border-radius:10px;
    padding:6px; max-height:500px; overflow-y:auto;
    font-family:'Courier New',monospace; font-size:12px; }
.tram-row {
    display:flex; border-bottom:1px solid #1a1a2e;
    padding:3px 6px; gap:8px; align-items:flex-start; }
.tram-desc  { flex:1; word-break:break-word; }
.tram-date  { min-width:72px; color:#52525b; text-align:right; flex-shrink:0; }
.tram-dist  { color:#60a5fa; }
.tram-ok    { color:#10b981; }
.tram-no    { color:#f87171; }
.tram-final { color:#fb923c; font-weight:bold; }
.tram-arch  { color:#52525b; }
.tram-def   { color:#a1a1aa; }
.par-pend   { color:#fb923c; }
.par-ok     { color:#10b981; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------

def _init_state():
    defaults = {
        "scraping":     False,
        "scraper_obj":  None,
        "log_lines":    [],
        "prog_current": 0,
        "prog_total":   0,
        "prog_stats":   {},
        "fase_texto":   "Aguardando início...",
        "fase_tipo":    "info",
        "sync_result":  None,
        "sync_error":   None,
        "thread_done":  threading.Event(),
        "show_import":  False,
        "import_msg":   None,
        "import_ok":    False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ---------------------------------------------------------------------------
# Sidebar — navegação principal
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <span class="brand-icon">🏛️</span>
        <span class="brand-text">ALERJ</span>
    </div>
    <p class="brand-caption">Acompanhamento Legislativo</p>
    """, unsafe_allow_html=True)

    _page = st.radio(
        "Navegação",
        ["📊 Dashboard", "🔄 Coletar Dados", "📋 Projetos", "📜 Histórico", "📅 Pauta"],
        label_visibility="collapsed",
        key="nav_radio",
    )

    st.divider()
    st.caption("Banco de dados")

    _db_path = db.DB_PATH
    if _db_path.exists():
        try:
            _db_bytes = _db_path.read_bytes()
            _ts_export = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                "⬇ Exportar Banco",
                data=_db_bytes,
                file_name=f"alerj_{_ts_export}.db",
                mime="application/octet-stream",
                use_container_width=True,
                help="Baixa o arquivo SQLite completo com todos os dados coletados.",
            )
        except Exception:
            st.button("⬇ Exportar Banco", disabled=True, use_container_width=True)
    else:
        st.button(
            "⬇ Exportar Banco", disabled=True, use_container_width=True,
            help="Banco ainda não criado. Execute a coleta primeiro.",
        )

    if st.button(
        "⬆ Importar Banco",
        use_container_width=True,
        disabled=st.session_state.scraping,
        help="Substitui o banco local por um arquivo .db importado.",
    ):
        st.session_state.show_import = not st.session_state.show_import
        st.session_state.import_msg  = None
        st.session_state.import_ok   = False
        st.rerun()

# ---------------------------------------------------------------------------
# Mensagem de resultado da importação + painel (área principal)
# ---------------------------------------------------------------------------
if st.session_state.import_msg:
    if st.session_state.import_ok:
        st.success(st.session_state.import_msg)
    else:
        st.error(st.session_state.import_msg)

if st.session_state.show_import and not st.session_state.scraping:
    with st.container(border=True):
        st.markdown("#### ⬆ Importar Banco de Dados")
        st.warning(
            "⚠️ A importação **substituirá todos os dados atuais**. "
            "O banco atual será salvo automaticamente como backup antes da substituição."
        )
        _uploaded_db = st.file_uploader(
            "Selecione o arquivo `.db` exportado pelo sistema:",
            type=["db"],
            key="db_uploader",
        )
        _ic1, _ic2 = st.columns(2)
        with _ic1:
            _confirm = st.button(
                "✅ Confirmar importação",
                type="primary",
                disabled=(_uploaded_db is None),
                use_container_width=True,
            )
        with _ic2:
            _cancel = st.button("✖ Cancelar", use_container_width=True)

        if _cancel:
            st.session_state.show_import = False
            st.session_state.import_msg  = None
            st.rerun()

        if _confirm and _uploaded_db is not None:
            _raw = _uploaded_db.read()
            if not _raw[:16].startswith(b"SQLite format 3"):
                st.session_state.import_msg = "❌ Arquivo inválido — não é um banco SQLite."
                st.session_state.import_ok  = False
                st.session_state.show_import = False
            else:
                try:
                    _db_path.parent.mkdir(parents=True, exist_ok=True)
                    if _db_path.exists():
                        _bk = _db_path.parent / "alerj_backup.db"
                        import shutil
                        shutil.copy2(str(_db_path), str(_bk))
                    _db_path.write_bytes(_raw)
                    db.init_db()
                    _stats_new = db.get_stats()
                    st.session_state.import_msg = (
                        f"✅ Importação concluída! "
                        f"Banco importado contém {_stats_new['total_projetos']:,} projetos. "
                        f"Backup salvo em alerj_backup.db."
                    )
                    st.session_state.import_ok   = True
                    st.session_state.show_import = False
                except Exception as _e:
                    st.session_state.import_msg  = f"❌ Erro ao importar: {_e}"
                    st.session_state.import_ok   = False
                    st.session_state.show_import = False
            st.rerun()

# ===========================================================================
# TAB 1 — Dashboard
# ===========================================================================
if _page == "📊 Dashboard":
    st.subheader("Resumo do banco de dados")

    stats_db = db.get_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📁 Total de Projetos",    f"{stats_db['total_projetos']:,}")
    c2.metric("📄 Proj. de Lei (PL)",    f"{stats_db['total_pl']:,}")
    c3.metric("📑 Proj. Resolução (PR)", f"{stats_db['total_pr']:,}")
    c4.metric("🔀 Tramitações",          f"{stats_db['total_andamentos']:,}")

    # Totais por legislatura
    leges_db = db.get_legislaturas()
    if leges_db:
        st.divider()
        st.subheader("Projetos por Legislatura")
        leg_cols = st.columns(min(len(leges_db), 4))
        for i, leg in enumerate(leges_db):
            rows_leg = db.get_projetos(legislatura=leg, limit=1)
            # conta via query rápida
            conn_tmp = db.get_connection()
            cnt = conn_tmp.execute(
                "SELECT COUNT(*) FROM projetos WHERE legislatura=?", (leg,)
            ).fetchone()[0]
            conn_tmp.close()
            leg_cols[i % 4].metric(f"📅 {leg}", f"{cnt:,}")

    st.divider()

    ultima = stats_db.get("ultima_sync")
    if ultima:
        st.subheader("Última sincronização bem-sucedida")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Data/Hora",   (ultima.get("data_fim") or "—")[:16])
        m2.metric("Tipos",       ultima.get("tipos", "—"))
        m3.metric("Novos",       ultima.get("projetos_novos", 0))
        m4.metric("Atualizados", ultima.get("projetos_atualizados", 0))
        m5.metric("Erros",       ultima.get("erros", 0))
    else:
        st.info("Nenhuma sincronização realizada ainda. Acesse **🔄 Coletar Dados** para iniciar.")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Por tipo")
        _conn = db.get_connection()
        tc_rows = _conn.execute(
            "SELECT tipo, COUNT(*) as n FROM projetos WHERE tipo IS NOT NULL GROUP BY tipo ORDER BY n DESC"
        ).fetchall()
        _conn.close()
        if tc_rows:
            df_tc = pd.DataFrame(tc_rows, columns=["Tipo", "Quantidade"])
            st.bar_chart(df_tc.set_index("Tipo"), color="#1f77b4")

    with col2:
        st.subheader("Por ano")
        _conn = db.get_connection()
        ac_rows = _conn.execute(
            "SELECT ano, COUNT(*) as n FROM projetos WHERE ano BETWEEN 2015 AND 2026 GROUP BY ano ORDER BY ano"
        ).fetchall()
        _conn.close()
        if ac_rows:
            import altair as _alt
            df_ac = pd.DataFrame(ac_rows, columns=["Ano", "Quantidade"])
            df_ac["Ano"] = df_ac["Ano"].astype(int).astype(str)
            _chart = (
                _alt.Chart(df_ac)
                .mark_bar(color="#1f77b4")
                .encode(
                    x=_alt.X("Ano:O", sort=None, axis=_alt.Axis(labelAngle=0)),
                    y=_alt.Y("Quantidade:Q"),
                    tooltip=["Ano", "Quantidade"],
                )
            )
            st.altair_chart(_chart, use_container_width=True)

# ===========================================================================
# TAB 2 — Coletar Dados
# ===========================================================================
elif _page == "🔄 Coletar Dados":
    # Sync thread-safe dict → session_state on every rerun so UI reflects latest thread writes
    with _coleta_log_lock:
        st.session_state["log_lines"] = list(_coleta_live["log_lines"])
    for _k in ("scraping", "prog_current", "prog_total",
               "prog_stats", "fase_texto", "fase_tipo", "sync_result", "sync_error"):
        st.session_state[_k] = _coleta_live[_k]

    st.subheader("Coleta Incremental de Dados")

    with st.expander("⚙️ Configurações de coleta", expanded=not st.session_state.scraping):
        cfg1, cfg2, cfg3, cfg4 = st.columns(4)
        with cfg1:
            tipos_sel = st.multiselect(
                "Tipos de proposição:",
                ["PL", "PR"],
                default=["PL", "PR"],
                key="coleta_tipos_sel",
                disabled=st.session_state.scraping,
            )
        with cfg2:
            legs_sel = st.multiselect(
                "Legislaturas:",
                TODAS_LEGISLATURAS,
                default=["2023-2027"],
                key="coleta_legs_sel",
                help="Selecione uma ou mais legislaturas. 2023-2027 = mandato atual.",
                disabled=st.session_state.scraping,
            )
        with cfg3:
            delay_sel = st.slider(
                "Intervalo entre requisições (s):",
                min_value=0.3, max_value=5.0, value=1.0, step=0.1,
                key="coleta_delay_sel",
                disabled=st.session_state.scraping,
            )
        with cfg4:
            st.markdown("**ℹ️ Fases da coleta**")
            st.markdown(
                "1. 📋 Paginar lista de projetos  \n"
                "2. 📄 Buscar detalhe de cada um  \n\n"
                "Coleta via HTTP direto — sem Selenium."
            )

    btn1, btn2, _ = st.columns([1, 1, 3])
    with btn1:
        start_btn = st.button(
            "▶ Iniciar Coleta",
            type="primary",
            disabled=st.session_state.scraping,
            use_container_width=True,
        )
    with btn2:
        stop_btn = st.button(
            "⏹ Parar",
            type="secondary",
            disabled=not st.session_state.scraping,
            use_container_width=True,
        )

    # --- Ação: Iniciar ---
    if start_btn and not st.session_state.scraping:
        if not tipos_sel:
            st.warning("Selecione ao menos um tipo de proposição.")
        elif not legs_sel:
            st.warning("Selecione ao menos uma legislatura.")
        else:
            try:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(LOG_FILE, "w", encoding="utf-8") as _f:
                    _f.write(f"=== Coleta iniciada em {datetime.now()} ===\n")
            except Exception:
                pass

            with _coleta_log_lock:
                _coleta_live["log_lines"] = []
            _coleta_live["scraping"]     = True
            _coleta_live["prog_current"] = 0
            _coleta_live["prog_total"]   = 0
            _coleta_live["prog_stats"]   = {}
            _coleta_live["fase_texto"]   = "⏳ Fase 1 — Iniciando coleta das listas..."
            _coleta_live["fase_tipo"]    = "info"
            _coleta_live["sync_result"]  = None
            _coleta_live["sync_error"]   = None
            st.session_state.thread_done  = threading.Event()
            # Keep session_state in sync for this render cycle (sync block above runs on next rerun)
            st.session_state.scraping = True

            def _log_cb(msg: str):
                ts = datetime.now().strftime("%H:%M:%S")
                with _coleta_log_lock:
                    _coleta_live["log_lines"].append(f"[{ts}] {msg}")

            def _prog_cb(current: int, total: int, s: Dict):
                _coleta_live["prog_current"] = current
                _coleta_live["prog_total"]   = total
                _coleta_live["prog_stats"]   = s

            def _phase_cb(fase: str, **kw):
                if fase == "listando":
                    tipo  = kw.get("tipo", "")
                    leg   = kw.get("legislatura", "")
                    pag   = kw.get("pagina", 0)
                    links = kw.get("links_coletados", 0)
                    _coleta_live["fase_texto"] = (
                        f"📋 Fase 1 — Listando {tipo} [{leg}] "
                        f"— página {pag} ({links} links até agora)"
                    )
                    _coleta_live["fase_tipo"] = "info"
                elif fase == "iniciando":
                    total = kw.get("total", 0)
                    _coleta_live["fase_texto"] = (
                        f"📄 Fase 2 — Buscando detalhes de {total} projetos..."
                    )
                    _coleta_live["fase_tipo"]    = "info"
                    _coleta_live["prog_total"]   = total
                elif fase == "processando":
                    atual  = kw.get("atual", 0)
                    total  = kw.get("total", 0)
                    numero = kw.get("numero", "")
                    tipo   = kw.get("tipo", "")
                    leg    = kw.get("legislatura", "")
                    _coleta_live["fase_texto"] = (
                        f"📄 Fase 2 — {atual}/{total} — {tipo} {numero} [{leg}]"
                    )
                    _coleta_live["fase_tipo"]    = "info"
                    _coleta_live["prog_current"] = atual
                elif fase == "concluido":
                    s = kw.get("stats", {})
                    _coleta_live["fase_texto"] = (
                        f"✅ Concluído — "
                        f"Novos: {s.get('novos',0)} | "
                        f"Atualizados: {s.get('atualizados',0)} | "
                        f"Erros: {s.get('erros',0)}"
                    )
                    _coleta_live["fase_tipo"] = "ok"
                elif fase == "erro":
                    _coleta_live["fase_texto"] = f"❌ Erro: {kw.get('mensagem','')}"
                    _coleta_live["fase_tipo"]  = "erro"

            scraper = ALERJScraper(delay=delay_sel, log_cb=_log_cb)
            st.session_state.scraper_obj = scraper

            _legs_snap  = list(legs_sel)
            _tipos_snap = list(tipos_sel)

            def _thread_fn():
                try:
                    result = scraper.run_sync(
                        tipos=_tipos_snap,
                        legislaturas=_legs_snap,
                        progress_cb=_prog_cb,
                        phase_cb=_phase_cb,
                    )
                    _coleta_live["sync_result"] = result
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    _coleta_live["sync_error"] = f"{e}\n\n{tb}"
                    _coleta_live["fase_texto"]  = f"❌ Erro crítico: {e}"
                    _coleta_live["fase_tipo"]   = "erro"
                finally:
                    _coleta_live["scraping"] = False
                    st.session_state.thread_done.set()

            threading.Thread(target=_thread_fn, daemon=True).start()
            st.rerun()

    # --- Ação: Parar ---
    if stop_btn and st.session_state.scraping:
        sc = st.session_state.scraper_obj
        if sc:
            sc.stop()
        _coleta_live["scraping"]   = False
        _coleta_live["fase_texto"] = "⏹ Coleta interrompida pelo usuário."
        _coleta_live["fase_tipo"]  = "info"
        st.session_state.scraping  = False

    # --- Painel de carregamento ---
    if st.session_state.scraping or st.session_state.sync_result or st.session_state.sync_error:
        _fase  = st.session_state.fase_texto or ""
        _cur   = st.session_state.prog_current
        _tot   = st.session_state.prog_total
        _s     = st.session_state.prog_stats
        _ativo = st.session_state.scraping

        # Estado de cada fase
        if "✅" in _fase or "Concluído" in _fase:
            _s1, _s2 = "done", "done"
        elif "❌" in _fase or "Erro" in _fase or "ERRO" in _fase:
            _s1, _s2 = "done", "erro"
        elif "⏹" in _fase:
            _s1, _s2 = "done", "wait"
        elif _ativo and "listando" in _fase.lower():
            _s1, _s2 = "active", "wait"
        elif _ativo:
            _s1, _s2 = "active", "active"
        else:
            _s1, _s2 = "wait", "wait"

        _pct     = min(_cur / _tot, 1.0) if _tot > 0 else 0.0
        _pct_int = int(_pct * 100)
        _ic      = {"done": "✓", "active": "…", "erro": "✕", "wait": "·"}

        _fase_curta = _fase
        for _pfx in ["📋 Fase 1 — ", "📄 Fase 2 — ", "📋 ", "📄 ", "✅ ", "❌ ", "⏹ ", "⏳ ",
                     "Fase 1 — ", "Fase 2 — "]:
            _fase_curta = _fase_curta.replace(_pfx, "")
        _fase_curta = _fase_curta.strip()

        if _ativo:
            _dot    = '<div class="pulse-dot"></div>'
            _titulo = "Coleta em andamento"
        elif "✅" in _fase or "Concluído" in _fase:
            _dot    = '<div class="pulse-dot" style="visibility:hidden"></div>'
            _titulo = "Coleta concluída com sucesso"
        elif "❌" in _fase or "Erro" in _fase:
            _dot    = '<div class="pulse-dot" style="visibility:hidden"></div>'
            _titulo = "Erro durante a coleta"
        else:
            _dot    = '<div class="pulse-dot" style="visibility:hidden"></div>'
            _titulo = "Coleta interrompida"

        _line_cls = "stp-line-done" if _s1 == "done" else "stp-line"
        # Com total desconhecido (pipeline), mostra contagem simples
        if not _ativo:
            # Coleta encerrada — barra estática sem animação
            _prog_lbl  = f"{_cur:,} projetos processados" if _cur > 0 else "Nenhum projeto processado"
            _prog_fill = "width:100%" if _cur > 0 else "width:0%"
        elif _tot > 0:
            _prog_lbl  = f"{_cur:,} de {_tot:,} projetos processados ({_pct_int}%)"
            _prog_fill = f"width:{_pct_int}%"
        elif _cur > 0:
            _prog_lbl  = f"{_cur:,} projetos processados"
            _prog_fill = "width:100%;animation:indeterminate 1.8s ease-in-out infinite"
        else:
            _prog_lbl  = "Aguardando primeiro projeto..."
            _prog_fill = "width:30%;animation:indeterminate 1.8s ease-in-out infinite"

        st.markdown(f"""
<div class="loading-card">
  <div class="loading-header">
    {_dot}
    <div>
      <div class="loading-title">{_titulo}</div>
      <div class="loading-sub">{_fase_curta[:150]}</div>
    </div>
  </div>

  <div class="stepper">
    <div class="stp stp-{_s1}">
      <div class="stp-circle">{_ic[_s1]}</div>
      <div class="stp-lbl">Fase 1<br>Listagem</div>
    </div>
    <div class="{_line_cls}"></div>
    <div class="stp stp-{_s2}">
      <div class="stp-circle">{_ic[_s2]}</div>
      <div class="stp-lbl">Fase 2<br>Detalhes</div>
    </div>
  </div>

  <div class="prog-wrap">
    <div class="prog-fill" style="{_prog_fill}"></div>
  </div>
  <div class="prog-label">{_prog_lbl}</div>

  <div class="stat-row">
    <div class="stat-chip"><span class="stat-chip-val c-green">{_s.get('novos',0):,}</span>&nbsp;novos</div>
    <div class="stat-chip"><span class="stat-chip-val c-blue">{_s.get('atualizados',0):,}</span>&nbsp;atualizados</div>
    <div class="stat-chip"><span class="stat-chip-val c-purple">{_s.get('pareceres',0):,}</span>&nbsp;pareceres</div>
    <div class="stat-chip"><span class="stat-chip-val c-orange">{_s.get('andamentos',0):,}</span>&nbsp;andamentos</div>
    <div class="stat-chip"><span class="stat-chip-val c-red">{_s.get('erros',0):,}</span>&nbsp;erros</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # --- Log em tempo real ---
    if st.session_state.log_lines or st.session_state.scraping:
        st.markdown("#### 📋 Log de execução")
        col_log, col_dl = st.columns([4, 1])
        with col_log:
            lines = st.session_state.log_lines[-50:]
            colored = []
            for line in lines:
                if "✔ NOVO" in line or "NOVO:" in line:
                    colored.append(f'<span class="log-line-novo">{line}</span>')
                elif "Atualizado" in line or "↑" in line:
                    colored.append(f'<span class="log-line-atualizado">{line}</span>')
                elif "ERRO" in line or "❌" in line:
                    colored.append(f'<span class="log-line-erro">{line}</span>')
                elif "AVISO" in line or "Falha" in line:
                    colored.append(f'<span class="log-line-aviso">{line}</span>')
                else:
                    colored.append(f'<span class="log-line-info">{line}</span>')
            st.markdown(
                f'<div class="log-box">{"<br>".join(colored)}</div>',
                unsafe_allow_html=True,
            )
        with col_dl:
            if LOG_FILE.exists():
                try:
                    log_content = LOG_FILE.read_text(encoding="utf-8", errors="replace")
                    st.download_button(
                        "⬇ Baixar log",
                        data=log_content.encode("utf-8"),
                        file_name="coleta_alerj.log",
                        mime="text/plain",
                        use_container_width=True,
                    )
                    sz = LOG_FILE.stat().st_size
                    st.caption(f"{sz:,} bytes\n{LOG_FILE}")
                except Exception:
                    pass

    # --- Erro ---
    if st.session_state.sync_error and not st.session_state.scraping:
        with st.expander("❌ Detalhe do erro", expanded=True):
            st.code(st.session_state.sync_error, language="python")

    # --- Resultado de sucesso ---
    if st.session_state.sync_result and not st.session_state.scraping:
        r = st.session_state.sync_result
        st.success(
            f"✅ Coleta concluída! "
            f"**Novos:** {r['novos']}  |  "
            f"**Atualizados:** {r['atualizados']}  |  "
            f"**Pareceres:** {r['pareceres']}  |  "
            f"**Andamentos:** {r['andamentos']}  |  "
            f"**Erros:** {r['erros']}"
        )

    if st.session_state.scraping:
        time.sleep(1.0)
        st.rerun()

# ===========================================================================
# TAB 3 — Projetos (abas por legislatura)
# ===========================================================================
elif _page == "📋 Projetos":
    st.subheader("Projetos Legislativos")

    # Filtros globais (aplicados em todas as sub-abas)
    f1, f2, f3, f4 = st.columns([1, 1, 2, 2])
    with f1:
        f_tipo = st.selectbox("Tipo", ["Todos", "PL", "PR", "PDL", "PEC"])
    with f2:
        anos_disp = ["Todos"] + [str(a) for a in db.get_anos_disponiveis()]
        f_ano = st.selectbox("Ano", anos_disp)
    with f3:
        f_autor = st.text_input("Filtrar por autor")
    with f4:
        f_busca = st.text_input("Busca livre (número, ementa, autor)")

    filtros_base = dict(
        tipo  = f_tipo  if f_tipo  != "Todos" else None,
        ano   = int(f_ano) if f_ano != "Todos" else None,
        autor = f_autor or None,
        busca = f_busca or None,
    )

    # Sub-abas: Geral + uma por legislatura com dados no banco
    leges_com_dados = db.get_legislaturas()
    sub_labels = ["🌐 Geral"] + [f"📅 {leg}" for leg in leges_com_dados]
    sub_tabs   = st.tabs(sub_labels)

    PAGE_SIZE = 20
    _SHOW_COLS = ["numero", "tipo", "legislatura", "ano", "autor", "ementa",
                  "situacao", "comissoes", "data_apresentacao", "atualizado_em"]
    _COL_CFG = {
        "numero":            st.column_config.TextColumn("Número"),
        "tipo":              st.column_config.TextColumn("Tipo", width="small"),
        "legislatura":       st.column_config.TextColumn("Legislatura", width="small"),
        "ano":               st.column_config.NumberColumn("Ano", format="%d"),
        "autor":             st.column_config.TextColumn("Autor"),
        "ementa":            st.column_config.TextColumn("Ementa", width="large"),
        "situacao":          st.column_config.TextColumn("Situação"),
        "comissoes":         st.column_config.TextColumn("Comissões"),
        "data_apresentacao": st.column_config.TextColumn("Apresentado em"),
        "atualizado_em":     st.column_config.TextColumn("Atualizado em"),
    }

    def _render_projetos_table(
        projetos_page: List[Dict], total: int, current_page: int,
        total_pages: int, key_suffix: str,
    ):
        """Renderiza 20 registros da página atual com contador real e navegação."""
        if total == 0:
            st.info("Nenhum projeto encontrado com os filtros aplicados.")
            return

        start_num = current_page * PAGE_SIZE + 1
        end_num   = current_page * PAGE_SIZE + len(projetos_page)

        col_info, col_nav = st.columns([3, 2])
        with col_info:
            st.caption(
                f"**{total:,}** registros no total — "
                f"exibindo **{start_num}–{end_num}**"
            )
        with col_nav:
            pk = f"proj_page_{key_suffix}"
            nc1, nc2, nc3, nc4 = st.columns([1, 2, 1, 1])
            with nc1:
                if st.button("◀", key=f"prev_{key_suffix}",
                             disabled=(current_page == 0), use_container_width=True):
                    st.session_state[pk] -= 1
                    st.rerun()
            with nc2:
                st.caption(f"Página {current_page + 1} de {total_pages}")
            with nc3:
                if st.button("▶", key=f"next_{key_suffix}",
                             disabled=(current_page >= total_pages - 1),
                             use_container_width=True):
                    st.session_state[pk] += 1
                    st.rerun()
            with nc4:
                if st.button("⏮", key=f"first_{key_suffix}",
                             disabled=(current_page == 0), use_container_width=True,
                             help="Voltar à primeira página"):
                    st.session_state[pk] = 0
                    st.rerun()

        df = pd.DataFrame(projetos_page)
        df = df.where(pd.notnull(df), "")
        show_cols = [c for c in _SHOW_COLS if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True,
                     column_config=_COL_CFG)

        with st.expander("📋 Tramitação do projeto"):
            nums = [p.get("numero") or f"#{p['id']}" for p in projetos_page]
            sel_num = st.selectbox("Selecione o projeto:", nums, key=f"sel_{key_suffix}")
            sel_proj = next(
                (p for p in projetos_page
                 if (p.get("numero") or f"#{p['id']}") == sel_num), None
            )
            if sel_proj:
                # ── Cabeçalho do projeto ──────────────────────────────────
                h1, h2 = st.columns(2)
                with h1:
                    st.markdown(
                        f"**{sel_proj.get('tipo','')} {sel_proj.get('numero','')}** "
                        f"— {sel_proj.get('legislatura','')}"
                    )
                    st.markdown(f"**Autor:** {sel_proj.get('autor','—')}")
                with h2:
                    st.markdown(f"**Situação:** {sel_proj.get('situacao','—')}")
                    st.markdown(f"**Apresentado em:** {sel_proj.get('data_apresentacao','—')}")
                st.markdown(f"**Ementa:** {sel_proj.get('ementa','—')}")
                if sel_proj.get("url"):
                    st.markdown(f"[🔗 Ver no site da ALERJ]({sel_proj['url']})")

                st.divider()

                # ── Comissões e Pareceres ─────────────────────────────────
                import unicodedata as _ud

                def _nc(s: str) -> str:
                    return _ud.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode("ascii")

                def _match_par(com_name: str, pars: list) -> dict:
                    """Faz matching fuzzy entre nome canônico da comissão e pareceres extraídos."""
                    # Palavras-chave: ≥5 chars, exclui artigos/preposições comuns
                    stop = {"comissao", "para", "pelo", "pela", "sobre", "entre", "estado"}
                    kws = [w for w in _nc(com_name).split() if len(w) >= 5 and w not in stop]
                    best = None
                    best_score = 0
                    for p in pars:
                        p_com = _nc(p.get("comissao") or "")
                        score = sum(1 for k in kws if k in p_com)
                        if score > best_score:
                            best_score = score
                            best = p
                    return best if best_score >= max(1, len(kws) // 2) else None

                comissoes_str = sel_proj.get("comissoes") or ""
                com_list = db.split_comissoes(comissoes_str)

                # ── Busca ao vivo no site da ALERJ ───────────────────────
                url_proj = sel_proj.get("url") or ""
                col_refresh, _ = st.columns([1, 5])
                with col_refresh:
                    if st.button("🔄 Atualizar", key=f"refresh_{key_suffix}",
                                 help="Limpa o cache e rebusca os dados no site da ALERJ"):
                        _fetch_tramitacao_ao_vivo.clear()
                        st.rerun()
                live_data: dict = {}
                if url_proj:
                    with st.spinner("Buscando dados atualizados no site da ALERJ..."):
                        live_data = _fetch_tramitacao_ao_vivo(url_proj)

                live_pars = live_data.get("pareceres", [])
                live_ands = live_data.get("andamento", [])

                # Fallback: dados do banco (para quando não há internet)
                db_pars = db.get_pareceres_projeto(sel_proj["id"])
                db_pars += db.get_pareceres_from_andamento(sel_proj["id"])
                db_ands = db.get_andamentos(sel_proj["id"])

                # Prioriza dados ao vivo; usa banco como fallback
                all_pars = live_pars if live_pars else db_pars
                all_ands = live_ands if live_ands else [dict(a) for a in db_ands]

                if not live_data.get("ok") and url_proj:
                    st.warning(f"Não foi possível buscar dados ao vivo: {live_data.get('erro','')}")

                if com_list:
                    st.markdown("##### Comissões e Pareceres")
                    com_rows = []
                    for com in com_list:
                        par = _match_par(com, all_pars)
                        if par:
                            relator  = (par.get("relator") or "").strip() or "—"
                            tipo_par = par.get("tipo_parecer") or "—"
                            data_par = par.get("data") or "—"
                            status_ic = "✅"
                        else:
                            relator = data_par = "—"
                            tipo_par  = "⏳ Pendente de parecer"
                            status_ic = "⏳"
                        com_rows.append({
                            "":         status_ic,
                            "Comissão": com,
                            "Relator":  relator,
                            "Parecer":  tipo_par,
                            "Data":     data_par,
                        })

                    df_com = pd.DataFrame(com_rows)
                    st.dataframe(
                        df_com,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "":         st.column_config.TextColumn("", width="small"),
                            "Comissão": st.column_config.TextColumn("Comissão"),
                            "Relator":  st.column_config.TextColumn("Relator"),
                            "Parecer":  st.column_config.TextColumn("Parecer"),
                            "Data":     st.column_config.TextColumn("Data", width="small"),
                        },
                    )
                else:
                    st.info("Nenhuma comissão registrada para este projeto.")

                st.divider()

                # ── Linha do tempo ────────────────────────────────────────
                st.markdown("##### Linha do tempo")

                def _tram_css(desc: str) -> str:
                    d = desc.lower()
                    if any(k in d for k in ["aprovado", "favoráv", "favorav"]):
                        return "tram-ok"
                    if any(k in d for k in ["contrário", "contrario", "rejeitado", "sem parecer"]):
                        return "tram-no"
                    if any(k in d for k in ["resultado final", " lei ", "resolução", "lei nº"]):
                        return "tram-final"
                    if "arquivo" in d:
                        return "tram-arch"
                    if "distribuiç" in d or "parecer em plen" in d or "relator" in d:
                        return "tram-dist"
                    return "tram-def"

                if all_ands:
                    rows_html = []
                    for a in all_ands:
                        desc = (a.get("descricao") or "").strip()
                        data = (a.get("data") or "").strip()
                        css  = _tram_css(desc)
                        desc_safe = (desc.replace("&","&amp;")
                                        .replace("<","&lt;")
                                        .replace(">","&gt;"))
                        rows_html.append(
                            f'<div class="tram-row">'
                            f'<span class="tram-desc {css}">{desc_safe}</span>'
                            f'<span class="tram-date">{data}</span>'
                            f'</div>'
                        )
                    st.markdown(
                        f'<div class="tram-box">{"".join(rows_html)}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("Sem tramitação registrada para este projeto.")

    def _render_sub_tab(key_suffix: str, legislatura=None):
        filt = {**filtros_base}
        if legislatura:
            filt["legislatura"] = legislatura

        total     = db.count_projetos_filtered(**filt)
        total_pgs = max(1, math.ceil(total / PAGE_SIZE))

        pk = f"proj_page_{key_suffix}"
        if pk not in st.session_state:
            st.session_state[pk] = 0
        st.session_state[pk] = min(st.session_state[pk], max(0, total_pgs - 1))
        cur_page = st.session_state[pk]

        page_rows = db.get_projetos(**filt, limit=PAGE_SIZE, offset=cur_page * PAGE_SIZE)
        _render_projetos_table(page_rows, total, cur_page, total_pgs, key_suffix)

        if total > 0:
            csv_rows = db.get_projetos(**filt, limit=100_000)
            df_csv = pd.DataFrame(csv_rows)
            df_csv = df_csv.where(pd.notnull(df_csv), "")
            csv_cols = [c for c in _SHOW_COLS if c in df_csv.columns]
            st.download_button(
                f"⬇ Exportar CSV ({total:,} registros)",
                data=df_csv[csv_cols].to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                file_name=f"projetos_alerj_{key_suffix}.csv",
                mime="text/csv",
                key=f"dl_{key_suffix}",
            )

    # Aba Geral — todos os projetos
    with sub_tabs[0]:
        _render_sub_tab("geral")

    # Aba por legislatura
    for i, leg in enumerate(leges_com_dados):
        with sub_tabs[i + 1]:
            _render_sub_tab(leg.replace("-", "_"), legislatura=leg)

# ===========================================================================
# TAB 4 — Histórico
# ===========================================================================
elif _page == "📜 Histórico":
    st.subheader("Histórico de Sincronizações")

    if st.button("🔄 Atualizar"):
        st.rerun()

    logs = db.get_sync_logs(limit=50)

    if logs:
        df_log = pd.DataFrame(logs)
        show_log = [c for c in
                    ["id", "data_inicio", "data_fim", "tipos",
                     "projetos_novos", "projetos_atualizados",
                     "andamentos_novos", "erros", "status"]
                    if c in df_log.columns]
        st.dataframe(
            df_log[show_log],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":                   st.column_config.NumberColumn("ID", width="small"),
                "data_inicio":          st.column_config.TextColumn("Início"),
                "data_fim":             st.column_config.TextColumn("Fim"),
                "tipos":                st.column_config.TextColumn("Tipos"),
                "projetos_novos":       st.column_config.NumberColumn("Novos"),
                "projetos_atualizados": st.column_config.NumberColumn("Atualizados"),
                "andamentos_novos":     st.column_config.NumberColumn("Tramitações"),
                "erros":                st.column_config.NumberColumn("Erros"),
                "status":               st.column_config.TextColumn("Status"),
            },
        )
        st.divider()
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Total adicionados", int(df_log.get("projetos_novos", pd.Series([0])).sum()))
        tc2.metric("Total atualizações", int(df_log.get("projetos_atualizados", pd.Series([0])).sum()))
        tc3.metric("Total de erros", int(df_log.get("erros", pd.Series([0])).sum()))

        if LOG_FILE.exists():
            with st.expander("📄 Log da última coleta"):
                try:
                    log_txt = LOG_FILE.read_text(encoding="utf-8", errors="replace")
                    lines_count = log_txt.count("\n")
                    st.caption(f"{lines_count} linhas — {LOG_FILE.stat().st_size:,} bytes")
                    st.code(log_txt[-10000:], language="text")
                    st.download_button(
                        "⬇ Baixar log completo",
                        data=log_txt.encode("utf-8"),
                        file_name="coleta_alerj.log",
                        mime="text/plain",
                    )
                except Exception as e:
                    st.warning(f"Não foi possível ler o arquivo de log: {e}")
    else:
        st.info("Nenhuma sincronização registrada ainda.")

# ===========================================================================
# TAB 5 — Pauta
# ===========================================================================
import re as _re
import unicodedata as _uc

_PAUTAS_DIR = Path(__file__).parent / "data" / "pautas"

# ── Helpers de análise de pauta ──────────────────────────────────────────────

def _ler_texto_documento(caminho: Path) -> str:
    ext = caminho.suffix.lower()
    try:
        if ext in {".docx", ".doc"}:
            from docx import Document as _Doc
            _d = _Doc(str(caminho))
            partes = [p.text for p in _d.paragraphs if p.text.strip()]
            for tbl in _d.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            partes.append(cell.text.strip())
            return "\n".join(partes)
        elif ext == ".pdf":
            import pdfplumber as _ppl
            partes = []
            with _ppl.open(str(caminho)) as _pdf:
                for page in _pdf.pages:
                    t = page.extract_text()
                    if t:
                        partes.append(t)
            return "\n".join(partes)
    except Exception as exc:
        return f"__ERRO__:{exc}"
    return ""


_REL_DOC_RE = _re.compile(
    r"\bRELATOR[A]?\s*[:\-]\s*(?:(?:DEP(?:UTAD[OA])?\.?\s+)|(?:DR\.?\s+)|(?:PROF\.?\s+))?"
    r"(.+?)(?:\s*[;,]|\s*$)",
    _re.IGNORECASE,
)

_COM_NOME_RE = _re.compile(
    r"\bCOMISS[ÃA]O\b\s*(?:DE\s+|DO\s+|DA\s+|DAS?\s+|DOS?\s+|E\s+DE\s+)?(.{3,120}?)(?:\s*[-:–—]|$)",
    _re.IGNORECASE,
)

_PAR_TIPO_RE = _re.compile(
    r"\b(FAVOR[AÁ]VEL(?:\s+(?:AO\s+)?(?:PROJETO|SUBSTITUTIVO|EMENDA|REQUER\w*))?"
    r"|CONTR[AÁ]RI[OA]|APROVAD[OA]|REJEITAD[OA]|PREJUDICAD[OA]|SEM\s+PARECER|AGUARDANDO)\b",
    _re.IGNORECASE,
)


def _extrair_pareceres_bloco(linhas: list) -> list:
    """Extrai pareceres (comissão, tipo, relator, objeto) de um bloco de linhas entre projetos.

    Suporta dois formatos:
    1. Inline: 'PARECERES DAS COMISSÕES: X, TIPO; Y, TIPO ...'
               '(PENDENDO DE PARECERES DAS COMISSÕES: X; Y; ..., ÀS EMENDAS DE PLENÁRIO.)'
    2. Linha-a-linha: cada comissão em sua própria linha com 'COMISSÃO ...'
    """
    texto = "\n".join(linhas)

    # ── Formato 1: inline ────────────────────────────────────────────────────────
    _PAR_INLINE_RE = _re.compile(
        r"^PARECERES?\s+DAS?\s+COMISS[ÕO][EÕ]S?\s*:([^\n(]+?)\.?\s*$",
        _re.IGNORECASE | _re.MULTILINE,
    )
    _PEND_INLINE_RE = _re.compile(
        r"\(\s*PEND\w+\s+DE\s+PARECERES?\s+DAS?\s+COMISS[ÕO][EÕ]S?\s*:\s*(.+?)\)",
        _re.IGNORECASE | _re.DOTALL,
    )
    _PAR_EMENDA_RE = _re.compile(
        r"^PARECERES?,?\s+(?:ÀS?\s+)?EMENDAS?\s+(?:DE\s+)?PLEN[AÁ]RIO,?\s+DAS?\s+COMISS[ÕO][EÕ]S?\s*:\s*([^\n]+?)\.?\s*$",
        _re.IGNORECASE | _re.MULTILINE,
    )
    _TIPO_INLINE_RE = _re.compile(
        r",\s*((?:PELA\s+(?:CONSTITUCIONALIDADE|LEGALIDADE|INCONSTITUCIONALIDADE)|"
        r"FAVOR[AÁ]VEL|CONTR[AÁ]RI[OA]|"
        r"APROVAD[OA](?:\([AS]\))?|REJEITAD[OA](?:\([AS]\))?|PREJUDICAD[OA](?:\([AS]\))?|"
        r"SEM\s+PARECER)[^;]*)",
        _re.IGNORECASE,
    )

    m_prop = _PAR_INLINE_RE.search(texto)
    m_pend = _PEND_INLINE_RE.search(texto)
    m_emenda = _PAR_EMENDA_RE.search(texto)

    if m_prop or m_pend or m_emenda:
        resultados: list = []

        # Extrai relatores em ordem posicional (para Proposição)
        m_rel = _re.search(
            r"RELATORES?\s*:\s*(.+?)\.?\s*(?=\n|$)",
            texto, _re.IGNORECASE | _re.MULTILINE,
        )
        relatores_prop: list = []
        if m_rel:
            rel_txt = _re.sub(r"^\s*DEPUTAD\w+(?:\s+E\s+DEPUTAD\w+)?\s+", "", m_rel.group(1), flags=_re.IGNORECASE).strip()
            # Substitui o último " E " (antes do último nome) por ","
            rel_txt = _re.sub(r"\s+E\s+(?=[^,]+$)", ", ", rel_txt)
            relatores_prop = [r.strip().rstrip(". ") for r in rel_txt.split(",") if r.strip()]

        if m_prop:
            itens = _re.split(r";\s*", m_prop.group(1).strip().rstrip("."))
            for idx, item in enumerate(itens):
                item = _re.sub(r"^[Ee]\s+", "", item).strip().rstrip(". ")
                if not item:
                    continue
                m_t = _TIPO_INLINE_RE.search(item)
                if m_t:
                    tipo  = m_t.group(1).strip()
                    frag  = item[:m_t.start()].strip()
                else:
                    tipo = ""
                    frag = item
                com_nome = ("COMISSÃO " + frag
                            if not _re.match(r"COMISS[ÃA]O\b", frag, _re.IGNORECASE)
                            else frag)
                relator = relatores_prop[idx] if idx < len(relatores_prop) else ""
                if len(com_nome) > 15:
                    resultados.append({
                        "comissao":     com_nome,
                        "tipo_parecer": tipo,
                        "relator":      relator,
                        "objeto":       "Proposição",
                    })

        if m_pend:
            itens_pend = _re.split(r";\s*", m_pend.group(1).strip())
            for item in itens_pend:
                # Remove sufixo "ÀS EMENDAS DE PLENÁRIO" e similar
                item = _re.sub(r",?\s*À[S]?\s+EMENDAS?\b.*$", "", item, flags=_re.IGNORECASE).strip()
                item = _re.sub(r"^[Ee]\s+", "", item).strip().rstrip(". ")
                if not item:
                    continue
                com_nome = ("COMISSÃO " + item
                            if not _re.match(r"COMISS[ÃA]O\b", item, _re.IGNORECASE)
                            else item)
                if len(com_nome) > 15:
                    resultados.append({
                        "comissao":     com_nome,
                        "tipo_parecer": "Aguardando parecer",
                        "relator":      "",
                        "objeto":       "Emenda",
                    })

        if m_emenda:
            # Extrai relatores de emendas — procura segunda ocorrência de RELATORES ou reutiliza
            m_rel_em = _re.search(
                r"RELATORES?\s*(?:DAS?\s+EMENDAS?)?\s*:\s*(.+?)\.?\s*(?=\n|$)",
                texto, _re.IGNORECASE | _re.MULTILINE,
            )
            relatores_em: list = []
            if m_rel_em:
                rel_txt = _re.sub(r"^\s*DEPUTAD\w+(?:\s+E\s+DEPUTAD\w+)?\s+", "", m_rel_em.group(1), flags=_re.IGNORECASE).strip()
                rel_txt = _re.sub(r"\s+E\s+(?=[^,]+$)", ", ", rel_txt)
                relatores_em = [r.strip().rstrip(". ") for r in rel_txt.split(",") if r.strip()]

            itens_em = _re.split(r";\s*", m_emenda.group(1).strip().rstrip("."))
            for idx, item in enumerate(itens_em):
                item = _re.sub(r"^[Ee]\s+", "", item).strip().rstrip(". ")
                if not item:
                    continue
                m_t = _TIPO_INLINE_RE.search(item)
                if m_t:
                    tipo = m_t.group(1).strip()
                    frag = item[:m_t.start()].strip()
                else:
                    tipo = ""
                    frag = item
                com_nome = ("COMISSÃO " + frag
                            if not _re.match(r"COMISS[ÃA]O\b", frag, _re.IGNORECASE)
                            else frag)
                relator = relatores_em[idx] if idx < len(relatores_em) else ""
                if len(com_nome) > 15:
                    resultados.append({
                        "comissao":     com_nome,
                        "tipo_parecer": tipo,
                        "relator":      relator,
                        "objeto":       "Emenda",
                    })

        return resultados

    # ── Formato 2: linha-a-linha com "COMISSÃO ..." ─────────────────────────────
    resultados = []
    n = len(linhas)
    objeto_atual = "Proposição"
    i = 0
    while i < n:
        linha = linhas[i].strip()

        # Detecta marcador de seção de emendas
        if (not _re.search(r"\bCOMISS[ÃA]O\b", linha, _re.IGNORECASE)
                and _re.search(r"\bEMENDA[S]?\b", linha, _re.IGNORECASE)
                and _re.match(
                    r"^(?:PARECERES?\s+[ÀAa`]\w*\s+)?EMENDA[S]?\s*(?:\([Ss]\))?\s*[:\-]?\s*$",
                    linha, _re.IGNORECASE,
                )):
            objeto_atual = "Emenda"
            i += 1
            continue

        if not _re.search(r"\bCOMISS[ÃA]O\b", linha, _re.IGNORECASE):
            i += 1
            continue

        m = _COM_NOME_RE.search(linha)
        com_nome = ("COMISSÃO " + m.group(1).strip().rstrip("-:–— ")) if m else linha.strip()
        com_nome = com_nome.strip()

        tipo_par = None
        relator  = None

        for j in range(i, min(i + 6, n)):
            src = linhas[j].strip()
            if j > i and _re.search(r"\bCOMISS[ÃA]O\b", src, _re.IGNORECASE):
                break
            if tipo_par is None:
                m_t = _PAR_TIPO_RE.search(src)
                if m_t:
                    tipo_par = m_t.group(1).strip()
            if relator is None:
                m_r = _REL_DOC_RE.search(src)
                if m_r:
                    relator = m_r.group(1).strip().rstrip(",; ")

        if len(com_nome) > 10:
            resultados.append({
                "comissao":     com_nome,
                "tipo_parecer": tipo_par or "",
                "relator":      relator or "",
                "objeto":       objeto_atual,
            })
        i += 1

    return resultados


def _extrair_projetos_pauta(texto: str) -> list:
    """Extrai número, autor, ementa, relator e pareceres de cada projeto listado na pauta."""
    linhas = texto.split("\n")
    seen: set = set()

    # Localiza índices de todas as linhas de projeto
    proj_indices: list = []
    for i, linha in enumerate(linhas):
        if _re.search(r"PROJETO\s+DE\s+(?:LEI|RESOLU)", linha, _re.IGNORECASE):
            m_num = _re.search(r"\b(\d{1,5}(?:-[A-Z])?/20\d{2})\b", linha)
            if m_num:
                proj_indices.append((i, m_num.group(1)))

    results = []
    for idx, (li, num) in enumerate(proj_indices):
        if num in seen:
            continue
        seen.add(num)
        linha = linhas[li]

        autor = None
        m_a = _re.search(
            r"DE\s+AUTORIA\s+D[EOA]S?\s+(?:DEPUTAD[OA]S?\s+)?(.+?)(?:,\s*QUE\b|$)",
            linha, _re.IGNORECASE,
        )
        if m_a:
            autor = _re.sub(r"\s*\(.*?\)", "", m_a.group(1)).strip().rstrip(",; ")

        ementa = None
        m_e = _re.search(r",\s*QUE\s+(.+)$", linha, _re.IGNORECASE)
        if m_e:
            ementa = m_e.group(1).strip()[:400]

        # Linhas de contexto deste projeto (até o início do próximo)
        next_li = proj_indices[idx + 1][0] if idx + 1 < len(proj_indices) else len(linhas)
        context = linhas[li + 1 : next_li]

        # Relator: primeiras 7 linhas do contexto
        relator_doc = None
        for src in context[:7]:
            m_r = _REL_DOC_RE.search(src)
            if m_r:
                relator_doc = m_r.group(1).strip().rstrip(",; ")
                break

        # Pareceres: varrer todo o contexto
        pareceres_doc = _extrair_pareceres_bloco(context)

        results.append({
            "numero":        num,
            "autor_doc":     autor,
            "ementa_doc":    ementa,
            "relator_doc":   relator_doc,
            "pareceres_doc": pareceres_doc,
        })

    return results


def _buscar_projeto_db(numero: str) -> dict | None:
    """Busca projeto no banco pelo número, tentando variantes.

    Retorna o dict da linha com chave extra '_numero_encontrado' indicando
    o número real que foi encontrado (pode diferir de `numero` quando há fallback).
    """
    conn = db.get_connection()
    try:
        # 1. Correspondência exata
        row = conn.execute(
            "SELECT * FROM projetos WHERE numero = ? LIMIT 1", (numero,)
        ).fetchone()
        if row:
            result = dict(row)
            result["_numero_encontrado"] = numero
            return result

        # 2. Remove sufixo de substitutivo (ex: "5137-A/2025" → "5137/2025") e tenta exato
        base = _re.sub(r"-[A-Z](?=/)", "", numero)
        row = conn.execute(
            "SELECT * FROM projetos WHERE numero = ? LIMIT 1", (base,)
        ).fetchone()
        if row:
            result = dict(row)
            result["_numero_encontrado"] = base
            return result

        # 3. Variantes com sufixo ancorando pelo número para não casar
        #    "1899/2023" quando buscamos "899/2023"
        parts = base.split("/")
        if len(parts) == 2:
            row = conn.execute(
                "SELECT * FROM projetos WHERE numero LIKE ? LIMIT 1",
                (f"{parts[0]}%/{parts[1]}",),
            ).fetchone()
            if row:
                result = dict(row)
                result["_numero_encontrado"] = result.get("numero", base)
                return result

        return None
    finally:
        conn.close()


def _norm_cmp(s: str) -> str:
    return _uc.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode("ascii")


def _so_alfanum(s: str) -> str:
    """Remove toda pontuação e normaliza espaços, mantendo apenas letras e números."""
    return " ".join(_re.findall(r"[A-Z0-9]+", _norm_cmp(s)))


def _conferir(val_doc: str | None, val_db: str | None) -> str:
    """Retorna 'ok', 'ok_pont' (igual exceto pontuação), 'diverge' ou 'sem_dado'."""
    if not val_doc:
        return "sem_dado"
    nd, ndb = _norm_cmp(val_doc), _norm_cmp(val_db or "")
    palavras_doc = set(_re.findall(r"[A-Z]{5,}", nd))
    palavras_db  = set(_re.findall(r"[A-Z]{5,}", ndb))
    if not palavras_doc or not palavras_db:
        return "sem_dado"
    overlap = len(palavras_doc & palavras_db) / len(palavras_doc)
    if overlap >= 0.5:
        return "ok"
    # Verifica se a única diferença é pontuação
    if _so_alfanum(nd) == _so_alfanum(ndb):
        return "ok_pont"
    # Ementa do documento pode estar truncada (prefixo do texto do banco)
    nd_alf = _so_alfanum(nd)
    ndb_alf = _so_alfanum(ndb)
    if nd_alf and ndb_alf.startswith(nd_alf):
        return "ok"
    return "diverge"


def _buscar_pareceres_db(projeto_id: int) -> list:
    """Retorna pareceres do banco; usa andamento como fallback se a tabela estiver vazia.
    CCJ sempre aparece primeiro; demais mantêm a ordem original (reflete a página da ALERJ).
    """
    pareceres = db.get_pareceres_projeto(projeto_id)
    if not pareceres:
        pareceres = db.get_pareceres_from_andamento(projeto_id)

    def _is_ccj(p: dict) -> bool:
        nome = _uc.normalize("NFKD", (p.get("comissao") or "").lower()).encode("ascii", "ignore").decode("ascii")
        return "constituicao" in nome and "justica" in nome

    ccj    = [p for p in pareceres if _is_ccj(p)]
    outros = [p for p in pareceres if not _is_ccj(p)]
    return ccj + outros


def _icone_parecer(tipo: str) -> str:
    t = (tipo or "").lower()
    if "aguardando" in t:
        return "⏳"
    if "favoravel" in t or "favorável" in t or "aprovado" in t:
        return "✅"
    if "contrario" in t or "contrário" in t:
        return "❌"
    if "prejudicado" in t:
        return "⛔"
    if t:
        return "📋"
    return "⏳"


def _conferir_relator(rel_doc: str | None, pareceres_db: list) -> tuple:
    """Compara relator do documento com os relatores das comissões no banco.

    Retorna (status, relator_db_match, comissao_match):
      'ok'       — nome encontrado em alguma comissão
      'diverge'  — nome não encontrado
      'sem_dado' — documento não tem relator
    """
    if not rel_doc:
        return "sem_dado", "", ""

    def _limpa(s: str) -> str:
        s = _uc.normalize("NFKD", (s or "").upper()).encode("ascii", "ignore").decode("ascii")
        s = _re.sub(r"\b(DEP\.?|DEPUTAD[OA]\.?|DR\.?|PROF\.?)\b", "", s)
        return " ".join(s.split())

    doc_palavras = set(w for w in _limpa(rel_doc).split() if len(w) >= 4)
    if not doc_palavras:
        return "sem_dado", "", ""

    melhor_overlap = 0.0
    melhor_rel     = ""
    melhor_com     = ""

    for par in pareceres_db:
        rel_db = par.get("relator") or ""
        if not rel_db:
            continue
        db_palavras = set(w for w in _limpa(rel_db).split() if len(w) >= 4)
        if not db_palavras:
            continue
        overlap = len(doc_palavras & db_palavras) / len(doc_palavras)
        if overlap > melhor_overlap:
            melhor_overlap = overlap
            melhor_rel = rel_db
            melhor_com = par.get("comissao") or ""

    if melhor_overlap >= 0.5:
        return "ok", melhor_rel, melhor_com
    return "diverge", "", ""


_COM_STOP = {"PARA", "PELO", "PELA", "ESTE", "ESTA", "ESSE", "ESSA", "SEUS", "SUAS",
             "COMISSAO", "COMISSÃO", "COMISS"}


def _match_comissao_score(a: str, b: str) -> float:
    def words(s):
        return {w for w in _norm_cmp(s).split() if len(w) >= 4 and w not in _COM_STOP}
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _norm_tipo_parecer(s: str) -> str:
    s = _so_alfanum(s or "")
    if "FAVORAVEL" in s or "APROVADO" in s or "APROVADA" in s:
        return "FAVORAVEL"
    if "CONTRARIO" in s or "REJEITADO" in s or "REJEITADA" in s:
        return "CONTRARIO"
    if "PREJUDICADO" in s or "PREJUDICADA" in s:
        return "PREJUDICADO"
    if "SEM PARECER" in s or "AGUARDANDO" in s:
        return "AGUARDANDO"
    return s.strip()


def _comparar_pareceres_doc_db(pars_doc: list, pars_db: list) -> list:
    """Emparelha pareceres por objeto+comissão e compara tipo e relator.

    status: 'ok' | 'diverge' | 'sem_db' (só no doc) | 'sem_doc' (só no banco)
    Agrupa por objeto ('Proposição' / 'Emenda') antes de emparelhar.
    """
    def _rel_words(s):
        s = _norm_cmp(s or "")
        s = _re.sub(r"\b(DEP|DEPUTADO|DEPUTADA|DR|PROF)\b\.?", "", s)
        return {w for w in s.split() if len(w) >= 4}

    def _match_one_grupo(grupo_doc: list, grupo_db: list) -> list:
        resultados = []
        db_usados: set = set()
        for pd in grupo_doc:
            melhor_score = 0.0
            melhor_idx   = -1
            for j, pdb in enumerate(grupo_db):
                if j in db_usados:
                    continue
                sc = _match_comissao_score(pd.get("comissao", ""), pdb.get("comissao", ""))
                if sc > melhor_score:
                    melhor_score = sc
                    melhor_idx   = j
            if melhor_score < 0.35 or melhor_idx < 0:
                _t_sem = _norm_tipo_parecer(pd.get("tipo_parecer", ""))
                _st_sem = "aguardando" if _t_sem == "AGUARDANDO" else "sem_db"
                resultados.append({"doc": pd, "db": None, "status": _st_sem,
                                    "diverge_tipo": False, "diverge_rel": False})
                continue
            pdb = grupo_db[melhor_idx]
            db_usados.add(melhor_idx)
            t_doc = _norm_tipo_parecer(pd.get("tipo_parecer", ""))
            t_db  = _norm_tipo_parecer(pdb.get("tipo_parecer", ""))
            diverge_tipo = bool(t_doc and t_db and t_doc != t_db)
            wr_doc = _rel_words(pd.get("relator", ""))
            wr_db  = _rel_words(pdb.get("relator", ""))
            diverge_rel  = bool(wr_doc and wr_db and len(wr_doc & wr_db) / len(wr_doc) < 0.5)
            status = "diverge" if (diverge_tipo or diverge_rel) else "ok"
            resultados.append({"doc": pd, "db": pdb, "status": status,
                                "diverge_tipo": diverge_tipo, "diverge_rel": diverge_rel})
        for j, pdb in enumerate(grupo_db):
            if j not in db_usados:
                resultados.append({"doc": None, "db": pdb, "status": "sem_doc",
                                    "diverge_tipo": False, "diverge_rel": False})
        return resultados

    # Agrupa por objeto e emparelha dentro de cada grupo (Proposição sempre primeiro)
    objetos = sorted(
        {p.get("objeto", "Proposição") for p in pars_doc + pars_db},
        key=lambda x: (x != "Proposição", x),
    )
    all_results = []
    for obj in objetos:
        grp_doc = [p for p in pars_doc if p.get("objeto", "Proposição") == obj]
        grp_db  = [p for p in pars_db  if p.get("objeto", "Proposição") == obj]
        for r in _match_one_grupo(grp_doc, grp_db):
            r["objeto"] = obj
            all_results.append(r)
    return all_results


if _page == "📅 Pauta":
    st.subheader("Pauta")
    st.caption("Envie arquivos de pauta (PDF ou Word) para armazenamento e análise posterior.")

    _PAUTAS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Upload ───────────────────────────────────────────────────────────────
    if "pauta_upload_key" not in st.session_state:
        st.session_state.pauta_upload_key = 0
    if "pauta_msg" not in st.session_state:
        st.session_state.pauta_msg = None
    if "pauta_msg_ok" not in st.session_state:
        st.session_state.pauta_msg_ok = True

    if st.session_state.pauta_msg:
        if st.session_state.pauta_msg_ok:
            st.success(st.session_state.pauta_msg)
        else:
            st.error(st.session_state.pauta_msg)
        st.session_state.pauta_msg = None

    with st.container(border=True):
        st.markdown("#### ⬆ Enviar arquivo")
        _uploaded = st.file_uploader(
            "Selecione um arquivo PDF ou Word:",
            type=["pdf", "doc", "docx"],
            key=f"pauta_uploader_{st.session_state.pauta_upload_key}",
        )
        if _uploaded is not None:
            _dest = _PAUTAS_DIR / _uploaded.name
            if _dest.exists():
                st.warning(f"Já existe um arquivo com o nome **{_uploaded.name}**. Clique em Substituir para sobrescrever.")
                if st.button("Substituir", type="primary", key="sub_pauta"):
                    _dest.write_bytes(_uploaded.getvalue())
                    st.session_state.pauta_upload_key += 1
                    st.session_state.pauta_msg = f"✅ **{_uploaded.name}** substituído com sucesso."
                    st.session_state.pauta_msg_ok = True
                    st.rerun()
            else:
                _dest.write_bytes(_uploaded.getvalue())
                st.session_state.pauta_upload_key += 1
                st.session_state.pauta_msg = f"✅ **{_uploaded.name}** salvo com sucesso."
                st.session_state.pauta_msg_ok = True
                st.rerun()

    # ── Lista de arquivos ────────────────────────────────────────────────────
    st.markdown("#### 📂 Arquivos enviados")

    _pauta_files = sorted(_PAUTAS_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
    _pauta_files = [f for f in _pauta_files if f.suffix.lower() in {".pdf", ".doc", ".docx"}]

    if "pauta_confirmar_exclusao" not in st.session_state:
        st.session_state.pauta_confirmar_exclusao = None

    if not _pauta_files:
        st.info("Nenhum arquivo enviado ainda.")
    else:
        for _pf in _pauta_files:
            _size_kb = _pf.stat().st_size / 1024
            _mtime   = datetime.fromtimestamp(_pf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            _ext_icon = "📄" if _pf.suffix.lower() == ".pdf" else "📝"
            _key      = _pf.name

            _c1, _c2, _c3, _c4, _c5 = st.columns([4, 1.5, 1.2, 0.8, 0.8])
            _c1.markdown(f"{_ext_icon} **{_pf.name}**")
            _c2.caption(f"{_size_kb:,.1f} KB")
            _c3.caption(_mtime)
            with _c4:
                with open(_pf, "rb") as _fh:
                    st.download_button(
                        "⬇",
                        data=_fh.read(),
                        file_name=_pf.name,
                        mime="application/octet-stream",
                        key=f"dl_pauta_{_key}",
                        use_container_width=True,
                        help="Baixar arquivo",
                    )
            with _c5:
                if st.button("✕", key=f"del_pauta_{_key}", use_container_width=True, help="Excluir arquivo"):
                    st.session_state.pauta_confirmar_exclusao = str(_pf)
                    st.rerun()

        # ── Confirmação de exclusão ──────────────────────────────────────────
        if st.session_state.pauta_confirmar_exclusao:
            _alvo = Path(st.session_state.pauta_confirmar_exclusao)
            if _alvo.exists():
                st.warning(f"Confirma a exclusão de **{_alvo.name}**? Esta ação não pode ser desfeita.")
                _ex1, _ex2, _ = st.columns([1, 1, 4])
                if _ex1.button("✅ Confirmar", type="primary", key="conf_excluir_pauta", use_container_width=True):
                    _alvo.unlink()
                    st.session_state.pauta_confirmar_exclusao = None
                    st.rerun()
                if _ex2.button("✖ Cancelar", key="canc_excluir_pauta", use_container_width=True):
                    st.session_state.pauta_confirmar_exclusao = None
                    st.rerun()

    # ── Primeira Revisão ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 🔍 Primeira Revisão")
    st.caption("Extrai os projetos do documento selecionado e confere autor e ementa com o banco de dados.")

    _pauta_files_rev = sorted(_PAUTAS_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
    _pauta_files_rev = [f for f in _pauta_files_rev if f.suffix.lower() in {".pdf", ".doc", ".docx"}]

    if not _pauta_files_rev:
        st.info("Envie um arquivo de pauta para usar esta funcionalidade.")
    else:
        _sel_rev = st.selectbox(
            "Arquivo para revisar:",
            [f.name for f in _pauta_files_rev],
            key="sel_revisao",
        )

        if st.button("🔍 Primeira Revisão", type="primary", key="btn_primeira_revisao"):
            _caminho_rev = _PAUTAS_DIR / _sel_rev
            with st.spinner("Lendo e analisando documento..."):
                _texto_rev = _ler_texto_documento(_caminho_rev)

            if _texto_rev.startswith("__ERRO__"):
                st.error(f"Não foi possível ler o arquivo: {_texto_rev.replace('__ERRO__:', '')}")
            else:
                _projetos_doc = _extrair_projetos_pauta(_texto_rev)

                if not _projetos_doc:
                    st.warning("Nenhum número de projeto encontrado no documento. Verifique o formato.")
                else:
                    # Conferência com o banco
                    _relatorio = []
                    for _p in _projetos_doc:
                        _db_row = _buscar_projeto_db(_p["numero"])
                        _pareceres_db: list = []
                        _st_rel, _rel_match, _com_match = "sem_dado", "", ""
                        if _db_row and _db_row.get("id"):
                            _pareceres_db = _buscar_pareceres_db(_db_row["id"])
                            _st_rel, _rel_match, _com_match = _conferir_relator(
                                _p.get("relator_doc"), _pareceres_db
                            )
                        _pars_doc = _p.get("pareceres_doc", [])
                        _par_comp = _comparar_pareceres_doc_db(_pars_doc, _pareceres_db)
                        _relatorio.append({
                            "p":              _p,
                            "db":             _db_row,
                            "pareceres_db":   _pareceres_db,
                            "pareceres_doc":  _pars_doc,
                            "parecer_comp":   _par_comp,
                            "status_autor":   _conferir(_p.get("autor_doc"), _db_row.get("autor") if _db_row else None),
                            "status_ementa":  _conferir(_p.get("ementa_doc"), _db_row.get("ementa") if _db_row else None),
                            "status_relator": _st_rel,
                            "relator_match":  _rel_match,
                            "comissao_match": _com_match,
                        })

                    # Resumo
                    _tot     = len(_relatorio)
                    _subst   = sum(
                        1 for r in _relatorio
                        if r["db"] and r["db"].get("_numero_encontrado", r["p"]["numero"]) != r["p"]["numero"]
                    )
                    def _par_diverge(r):
                        """True somente quando o documento TEM pareceres e há divergência com o banco."""
                        return bool(r.get("pareceres_doc")) and any(
                            c.get("status") in ("diverge", "sem_db")
                            for c in r.get("parecer_comp", [])
                        )

                    _par_div = sum(1 for r in _relatorio if _par_diverge(r))
                    _div     = sum(1 for r in _relatorio if r["db"] and (
                        r["status_autor"] == "diverge" or
                        r["status_ementa"] == "diverge" or
                        _par_diverge(r)
                    ))
                    _rel_div = sum(1 for r in _relatorio if r.get("status_relator") == "diverge")
                    _nao_enc = sum(1 for r in _relatorio if not r["db"])
                    _ok      = sum(1 for r in _relatorio if r["db"] and
                        r["status_autor"] != "diverge" and r["status_ementa"] != "diverge" and
                        not _par_diverge(r) and
                        r["db"].get("_numero_encontrado", r["p"]["numero"]) == r["p"]["numero"])

                    _s1, _s2, _s3, _s4, _s5, _s6, _s7 = st.columns(7)
                    _s1.metric("Projetos na pauta",    _tot)
                    _s2.metric("✅ Conferidos",         _ok)
                    _s3.metric("⚠️ Divergências",       _div)
                    _s4.metric("📋 Parecer diverg.",    _par_div)
                    _s5.metric("👤 Relator divergente", _rel_div)
                    _s6.metric("🔄 Substitutivos",      _subst)
                    _s7.metric("❓ Não encontrados",    _nao_enc)

                    st.divider()

                    # Relatório detalhado
                    _ICONE = {"ok": "✅", "ok_pont": "✅", "diverge": "❌", "sem_dado": "—"}

                    for _r in _relatorio:
                        _p, _db = _r["p"], _r["db"]
                        _ia = _ICONE[_r["status_autor"]]
                        _ie = _ICONE[_r["status_ementa"]]

                        _tem_diverge     = "diverge" in (_r["status_autor"], _r["status_ementa"])
                        _tem_pont        = "ok_pont" in (_r["status_autor"], _r["status_ementa"])
                        _tem_rel_div     = _r.get("status_relator") == "diverge"
                        _tem_par_div     = _par_diverge(_r)
                        # Verifica se houve fallback para o projeto base (substitutivo não está no banco)
                        _num_encontrado  = (_db or {}).get("_numero_encontrado", _p["numero"])
                        _eh_substitutivo = _db is not None and _num_encontrado != _p["numero"]

                        if not _db:
                            _titulo_rel = f"❓ {_p['numero']} — Não encontrado no banco de dados"
                        elif _eh_substitutivo:
                            _titulo_rel = f"🔄 {_p['numero']} — Substitutivo sem entrada própria no banco (encontrado como {_num_encontrado})"
                        elif _tem_diverge or _tem_rel_div or _tem_par_div:
                            _sufixos = []
                            if _tem_diverge:   _sufixos.append("autor/ementa")
                            if _tem_rel_div:   _sufixos.append("relator")
                            if _tem_par_div:   _sufixos.append("pareceres")
                            _titulo_rel = f"⚠️ {_p['numero']} — Divergência: {', '.join(_sufixos)}"
                        elif _tem_pont:
                            _titulo_rel = f"✅ {_p['numero']} — Conferido (diferença de pontuação)"
                        else:
                            _titulo_rel = f"✅ {_p['numero']} — Conferido"

                        _expand = not _db or _tem_diverge or _tem_pont or _eh_substitutivo or _tem_rel_div or _tem_par_div
                        with st.expander(_titulo_rel, expanded=_expand):
                            if not _db:
                                st.error("Projeto não encontrado no banco de dados.")
                                if _p.get("autor_doc"):
                                    st.markdown(f"**Autor (pauta):** {_p['autor_doc']}")
                                if _p.get("ementa_doc"):
                                    st.markdown(f"**Ementa (pauta):** {_p['ementa_doc']}")
                            else:
                                if _eh_substitutivo:
                                    st.warning(
                                        f"O banco não possui entrada para **{_p['numero']}** (substitutivo). "
                                        f"A conferência foi feita com **{_num_encontrado}** (texto original). "
                                        "A ementa do substitutivo pode diferir — verifique manualmente."
                                    )

                                _col_a, _col_e = st.columns(2)

                                with _col_a:
                                    _label_a = f"**{_ia} Autor**"
                                    if _r["status_autor"] == "ok_pont":
                                        _label_a += " *(só pontuação)*"
                                    st.markdown(_label_a)
                                    if _p.get("autor_doc"):
                                        st.caption(f"**Pauta:** {_p['autor_doc']}")
                                    st.caption(f"**Banco:** {_db.get('autor') or '—'}")

                                with _col_e:
                                    _label_e = f"**{_ie} Ementa**"
                                    if _r["status_ementa"] == "ok_pont":
                                        _label_e += " *(só pontuação)*"
                                    elif _eh_substitutivo:
                                        _label_e += " *(texto original — pode diferir)*"
                                    st.markdown(_label_e)
                                    if _p.get("ementa_doc"):
                                        st.caption(f"**Pauta:** {_p['ementa_doc'][:200]}")
                                    st.caption(f"**Banco:** {(_db.get('ementa') or '—')[:200]}")

                                _inf1, _inf2 = st.columns(2)
                                _inf1.caption(f"Tipo: {_db.get('tipo','—')} | Legislatura: {_db.get('legislatura','—')}")
                                _inf2.caption(f"Situação: {_db.get('situacao','—')}")
                                if _db.get("url"):
                                    st.markdown(f"[🔗 Ver no site da ALERJ]({_db['url']})")

                                # ── Comissões e Pareceres ──────────────────────
                                _pars_db  = _r.get("pareceres_db", [])
                                _pars_doc = _r.get("pareceres_doc", [])
                                _comp     = _r.get("parecer_comp", [])

                                if _pars_db or _pars_doc or _comp:
                                    st.markdown("---")
                                    st.markdown("**📋 Comissões e Pareceres**")

                                    # Quando o documento não traz pareceres, tudo é informativo
                                    _doc_tem_pars = bool(_pars_doc)
                                    _STATUS_LABEL = {
                                        "ok":         "✅ Conferido",
                                        "diverge":    "❌ Divergência",
                                        "sem_db":     "❌ Não está no banco" if _doc_tem_pars else "—",
                                        "aguardando": "⏳ Aguardando parecer",
                                        "sem_doc":    "📋 Só no banco"       if _doc_tem_pars else "ℹ️ Banco",
                                    }

                                    # Exibe uma tabela por objeto (Proposição, depois Emenda)
                                    _objetos_exib = sorted(
                                        {c.get("objeto", "Proposição") for c in _comp},
                                        key=lambda x: (x != "Proposição", x),
                                    )
                                    for _obj_ex in _objetos_exib:
                                        _grp_ex = [c for c in _comp if c.get("objeto", "Proposição") == _obj_ex]
                                        st.markdown(f"**📌 {_obj_ex}**")
                                        _tbl_rows = []
                                        for _c in _grp_ex:
                                            _cpd  = _c.get("doc") or {}
                                            _cpdb = _c.get("db") or {}
                                            _cst  = _c.get("status", "")
                                            _com_nome = _cpd.get("comissao") or _cpdb.get("comissao") or "—"
                                            _tp_banco = _cpdb.get("tipo_parecer") or ""
                                            _aguard   = _tp_banco in ("Aguardando parecer", "", None)
                                            if _cst == "sem_doc" and _aguard:
                                                _st_lbl = "⏳ Pendente"
                                            else:
                                                _st_lbl = _STATUS_LABEL.get(_cst, "—")
                                            _tbl_rows.append({
                                                "Comissão":         _com_nome,
                                                "Parecer (doc)":    _cpd.get("tipo_parecer") or "—",
                                                "Relator (doc)":    _cpd.get("relator")      or "—",
                                                "Parecer (banco)":  _icone_parecer(_tp_banco) + " " + (_tp_banco or "—"),
                                                "Relator (banco)":  _cpdb.get("relator")     or "—",
                                                "Data (banco)":     _cpdb.get("data")        or "—",
                                                "Status":           _st_lbl,
                                            })
                                        if _tbl_rows:
                                            _df_par = pd.DataFrame(_tbl_rows)
                                            st.dataframe(_df_par, use_container_width=True, hide_index=True)

                                    # Relator do documento (conferência global, só se sem comp. por comissão)
                                    _rel_doc_p = _r["p"].get("relator_doc")
                                    if _rel_doc_p and not _comp:
                                        st.markdown("---")
                                        _st_rel = _r.get("status_relator")
                                        if _st_rel == "ok":
                                            st.success(
                                                f"**👤 Relator (pauta):** {_rel_doc_p}  \n"
                                                f"✅ Conferido — encontrado na **{_r.get('comissao_match') or '—'}** "
                                                f"como `{_r.get('relator_match')}`"
                                            )
                                        elif _st_rel == "diverge":
                                            _rels_bd = ", ".join(
                                                p["relator"] for p in _pars_db if p.get("relator")
                                            ) or "—"
                                            st.error(
                                                f"**👤 Relator (pauta):** {_rel_doc_p}  \n"
                                                f"❌ Não encontrado nos relatores do banco  \n"
                                                f"Relatores no banco: {_rels_bd}"
                                            )

                                elif _db.get("comissoes"):
                                    # Projeto tem comissões atribuídas mas sem pareceres registrados
                                    st.markdown("---")
                                    st.markdown("**📋 Comissões**")
                                    for _cn in db.split_comissoes(_db["comissoes"]):
                                        st.caption(f"⏳ {_cn} — sem parecer registrado no banco")
                                    if _r["p"].get("relator_doc"):
                                        st.caption(f"👤 Relator (pauta): {_r['p']['relator_doc']} — não foi possível conferir (sem pareceres no banco)")
