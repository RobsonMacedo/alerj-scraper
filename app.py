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
    initial_sidebar_state="collapsed",
)

TODAS_LEGISLATURAS = list(LEGISLATURAS.keys())   # ["2023-2027", "2019-2023", ...]

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.8rem; }
.log-box {
    background: #0d1117;
    color: #e6edf3;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    padding: 12px;
    border-radius: 6px;
    max-height: 380px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    border: 1px solid #30363d;
}
.log-line-novo       { color: #3fb950; }
.log-line-atualizado { color: #58a6ff; }
.log-line-erro       { color: #f85149; }
.log-line-aviso      { color: #d29922; }
.log-line-info       { color: #8b949e; }
.phase-box      { background:#161b22; border-left:4px solid #58a6ff;
                  padding:10px 14px; border-radius:4px;
                  font-family:'Courier New',monospace; font-size:13px;
                  color:#e6edf3; margin-bottom:8px; }
.phase-box-ok   { border-left-color:#3fb950; }
.phase-box-erro { border-left-color:#f85149; }
.tram-box {
    background:#0d1117; border:1px solid #30363d; border-radius:6px;
    padding:6px; max-height:500px; overflow-y:auto;
    font-family:'Courier New',monospace; font-size:12px; }
.tram-row {
    display:flex; border-bottom:1px solid #161b22;
    padding:3px 6px; gap:8px; align-items:flex-start; }
.tram-desc  { flex:1; word-break:break-word; }
.tram-date  { min-width:72px; color:#6e7681; text-align:right; flex-shrink:0; }
.tram-dist  { color:#58a6ff; }
.tram-ok    { color:#3fb950; }
.tram-no    { color:#f85149; }
.tram-final { color:#ffa657; font-weight:bold; }
.tram-arch  { color:#6e7681; }
.tram-def   { color:#c9d1d9; }
.par-pend   { color:#d29922; }
.par-ok     { color:#3fb950; }
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
# Título
# ---------------------------------------------------------------------------

st.markdown("# 🏛️ ALERJ — Acompanhamento Legislativo")
st.caption(
    "Coleta e acompanhamento de projetos de lei, projetos de resolução "
    "e pareceres das comissões — Assembleia Legislativa do Estado do Rio de Janeiro."
)

# ---------------------------------------------------------------------------
# Exportar / Importar banco de dados
# ---------------------------------------------------------------------------
_ecol, _icol, _ = st.columns([1.4, 1.4, 5])

with _ecol:
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
        except Exception as _ex:
            st.button("⬇ Exportar Banco", disabled=True, use_container_width=True)
    else:
        st.button(
            "⬇ Exportar Banco", disabled=True, use_container_width=True,
            help="Banco ainda não criado. Execute a coleta primeiro.",
        )

with _icol:
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

# Mensagem de resultado da importação
if st.session_state.import_msg:
    if st.session_state.import_ok:
        st.success(st.session_state.import_msg)
    else:
        st.error(st.session_state.import_msg)

# Painel de importação
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
            # Valida cabeçalho SQLite
            if not _raw[:16].startswith(b"SQLite format 3"):
                st.session_state.import_msg = "❌ Arquivo inválido — não é um banco SQLite."
                st.session_state.import_ok  = False
                st.session_state.show_import = False
            else:
                try:
                    _db_path.parent.mkdir(parents=True, exist_ok=True)
                    # Backup do banco atual
                    if _db_path.exists():
                        _bk = _db_path.parent / "alerj_backup.db"
                        import shutil
                        shutil.copy2(str(_db_path), str(_bk))
                    # Substitui
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

st.divider()

tabs = st.tabs([
    "📊 Dashboard",
    "🔄 Coletar Dados",
    "📋 Projetos",
    "📜 Histórico",
    "📅 Pauta",
])

# ===========================================================================
# TAB 1 — Dashboard
# ===========================================================================
with tabs[0]:
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
with tabs[1]:
    st.subheader("Coleta Incremental de Dados")

    with st.expander("⚙️ Configurações de coleta", expanded=True):
        cfg1, cfg2, cfg3, cfg4 = st.columns(4)
        with cfg1:
            tipos_sel = st.multiselect(
                "Tipos de proposição:",
                ["PL", "PR"],
                default=["PL", "PR"],
            )
        with cfg2:
            legs_sel = st.multiselect(
                "Legislaturas:",
                TODAS_LEGISLATURAS,
                default=["2023-2027"],
                help="Selecione uma ou mais legislaturas. 2023-2027 = mandato atual.",
            )
        with cfg3:
            delay_sel = st.slider(
                "Intervalo entre requisições (s):",
                min_value=0.3, max_value=5.0, value=1.0, step=0.1,
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

            st.session_state.scraping     = True
            st.session_state.log_lines    = []
            st.session_state.prog_current = 0
            st.session_state.prog_total   = 0
            st.session_state.prog_stats   = {}
            st.session_state.fase_texto   = "⏳ Fase 1 — Iniciando coleta das listas..."
            st.session_state.fase_tipo    = "info"
            st.session_state.sync_result  = None
            st.session_state.sync_error   = None
            st.session_state.thread_done  = threading.Event()

            def _log_cb(msg: str):
                ts = datetime.now().strftime("%H:%M:%S")
                st.session_state.log_lines.append(f"[{ts}] {msg}")

            def _prog_cb(current: int, total: int, s: Dict):
                st.session_state.prog_current = current
                st.session_state.prog_total   = total
                st.session_state.prog_stats   = s

            def _phase_cb(fase: str, **kw):
                if fase == "listando":
                    tipo  = kw.get("tipo", "")
                    leg   = kw.get("legislatura", "")
                    pag   = kw.get("pagina", 0)
                    links = kw.get("links_coletados", 0)
                    st.session_state.fase_texto = (
                        f"📋 Fase 1 — Listando {tipo} [{leg}] "
                        f"— página {pag} ({links} links até agora)"
                    )
                    st.session_state.fase_tipo = "info"
                elif fase == "iniciando":
                    total = kw.get("total", 0)
                    st.session_state.fase_texto = (
                        f"📄 Fase 2 — Buscando detalhes de {total} projetos..."
                    )
                    st.session_state.fase_tipo  = "info"
                    st.session_state.prog_total = total
                elif fase == "processando":
                    atual  = kw.get("atual", 0)
                    total  = kw.get("total", 0)
                    numero = kw.get("numero", "")
                    tipo   = kw.get("tipo", "")
                    leg    = kw.get("legislatura", "")
                    st.session_state.fase_texto = (
                        f"📄 Fase 2 — {atual}/{total} — {tipo} {numero} [{leg}]"
                    )
                    st.session_state.fase_tipo  = "info"
                    st.session_state.prog_current = atual
                elif fase == "concluido":
                    s = kw.get("stats", {})
                    st.session_state.fase_texto = (
                        f"✅ Concluído — "
                        f"Novos: {s.get('novos',0)} | "
                        f"Atualizados: {s.get('atualizados',0)} | "
                        f"Erros: {s.get('erros',0)}"
                    )
                    st.session_state.fase_tipo = "ok"
                elif fase == "erro":
                    st.session_state.fase_texto = f"❌ Erro: {kw.get('mensagem','')}"
                    st.session_state.fase_tipo  = "erro"

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
                    st.session_state.sync_result = result
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    st.session_state.sync_error = f"{e}\n\n{tb}"
                    st.session_state.fase_texto = f"❌ Erro crítico: {e}"
                    st.session_state.fase_tipo  = "erro"
                finally:
                    st.session_state.scraping = False
                    st.session_state.thread_done.set()

            threading.Thread(target=_thread_fn, daemon=True).start()
            st.rerun()

    # --- Ação: Parar ---
    if stop_btn and st.session_state.scraping:
        sc = st.session_state.scraper_obj
        if sc:
            sc.stop()
        st.session_state.scraping   = False
        st.session_state.fase_texto = "⏹ Coleta interrompida pelo usuário."
        st.session_state.fase_tipo  = "info"

    # --- Painel de status ---
    if st.session_state.fase_texto and st.session_state.fase_texto != "Aguardando início...":
        fase_css = {
            "ok":   "phase-box phase-box-ok",
            "erro": "phase-box phase-box-erro",
            "info": "phase-box",
        }.get(st.session_state.fase_tipo, "phase-box")
        st.markdown(
            f'<div class="{fase_css}">{st.session_state.fase_texto}</div>',
            unsafe_allow_html=True,
        )

    # --- Barra de progresso ---
    if st.session_state.scraping or st.session_state.sync_result or st.session_state.sync_error:
        current = st.session_state.prog_current
        total   = st.session_state.prog_total
        s       = st.session_state.prog_stats

        if total > 0:
            pct = min(current / total, 1.0)
            st.progress(pct, text=f"Fase 2 — Detalhes: {current}/{total} ({int(pct*100)}%)")
        elif st.session_state.scraping:
            st.progress(0, text="Fase 1 — Coletando lista de projetos...")

        if s:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("✔ Novos",       s.get("novos", 0))
            m2.metric("↑ Atualizados", s.get("atualizados", 0))
            m3.metric("⚖️ Pareceres",   s.get("pareceres", 0))
            m4.metric("🔀 Andamentos",  s.get("andamentos", 0))
            m5.metric("❌ Erros",       s.get("erros", 0))

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
        time.sleep(1.5)
        st.rerun()

# ===========================================================================
# TAB 3 — Projetos (abas por legislatura)
# ===========================================================================
with tabs[2]:
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
with tabs[3]:
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
_PAUTAS_DIR = Path(__file__).parent / "data" / "pautas"

with tabs[4]:
    st.subheader("Pauta")
    st.caption("Envie arquivos de pauta (PDF ou Word) para armazenamento e análise posterior.")

    _PAUTAS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Upload ───────────────────────────────────────────────────────────────
    if "pauta_upload_key" not in st.session_state:
        st.session_state.pauta_upload_key = 0

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
                    st.success(f"✅ **{_uploaded.name}** substituído com sucesso.")
                    st.rerun()
            else:
                _dest.write_bytes(_uploaded.getvalue())
                st.session_state.pauta_upload_key += 1
                st.success(f"✅ **{_uploaded.name}** salvo com sucesso.")
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
