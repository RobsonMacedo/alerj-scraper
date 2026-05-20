"""
Scraper para o site da ALERJ — Assembleia Legislativa do RJ.

Acessa o servidor Lotus Notes diretamente (alerjln1.alerj.rj.gov.br)
via HTTP puro (requests + BeautifulSoup). Sem Selenium.

Tipos suportados:
  PL  — Projeto de Lei        (/scpro2327.nsf/Internet/LeiInt?OpenForm)
  PR  — Projeto de Resolução  (/scpro2327.nsf/Internet/ResolucaoInt?OpenForm)
"""

import re
import sys
import time
import logging
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LOG_FILE = Path(__file__).parent / "data" / "coleta.log"

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

ALERJLN = "http://alerjln1.alerj.rj.gov.br"

# Legislaturas disponíveis (mandatos) — chave = label exibido
LEGISLATURAS: Dict[str, Dict[str, str]] = {
    "2023-2027": {
        "PL": "/scpro2327.nsf/Internet/LeiInt?OpenForm",
        "PR": "/scpro2327.nsf/Internet/ResolucaoInt?OpenForm",
    },
    "2019-2023": {
        "PL": "/scpro1923.nsf/Internet/LeiInt?OpenForm",
        "PR": "/scpro1923.nsf/Internet/ResolucaoInt?OpenForm",
    },
    "2015-2019": {
        "PL": "/scpro1519.nsf/Internet/LeiInt?OpenForm",
        "PR": "/scpro1519.nsf/Internet/ResolucaoInt?OpenForm",
    },
    "2011-2015": {
        "PL": "/scpro1115.nsf/Internet/LeiInt?OpenForm",
        "PR": "/scpro1115.nsf/Internet/ResolucaoInt?OpenForm",
    },
}

# Compat: aponta para legislatura atual por padrão
LIST_FORMS: Dict[str, str] = LEGISLATURAS["2023-2027"]

DOC_VIEW_RE = re.compile(r"/scpro\d{4}\.nsf/[0-9a-f]{32}/[0-9a-f]{32}", re.I)

PAGE_SIZE = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

ENCODINGS = ["windows-1252", "latin-1", "utf-8", "iso-8859-1"]

DATE_RE      = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
ANO_RE       = re.compile(r"\b(20\d{2}|19\d{2})\b")
NUMERO_RE    = re.compile(r"[Nn][º°\.]\s*(\d+/\d{4})")
EMENTA_RE    = re.compile(r"EMENTA\s*[:：]\s*(.+?)(?=\s*Autor\(es\)|\s*JUSTIFICATIVA|$)", re.DOTALL)
AUTOR_RE     = re.compile(r"Autor\(es\)\s*:\s*(?:Deputad[oa]s?\s+)?([A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ\s]+?)(?=\s*A ASSEMBLEIA|\s*RESOLVE|$)", re.DOTALL)
# ---------------------------------------------------------------------------
# Comissões permanentes da ALERJ — lista canônica e extrator
# ---------------------------------------------------------------------------

# (nome_canônico, [palavras-chave normalizadas — qualquer uma serve para identificar])
_COMISSOES_MAP: List[Tuple[str, List[str]]] = [
    ("Comissão de Administração e Serviço Público",
     ["comissao de administracao e servico", "administracao e servico publico"]),
    ("Comissão de Agricultura, Pecuária e Políticas Rurais",
     ["comissao de agricultura", "pecuaria e politicas rurais", "politicas rurais"]),
    ("Comissão de Assuntos da Criança, do Adolescente e do Idoso",
     ["comissao de assuntos da crianca", "crianca, do adolescente e do idoso",
      "crianca e do adolescente"]),
    ("Comissão de Assuntos Municipais e de Desenvolvimento Regional",
     ["comissao de assuntos municipais", "desenvolvimento regional"]),
    ("Comissão de Ciência e Tecnologia",
     ["comissao de ciencia e tecnologia", "ciencia e tecnologia"]),
    ("Comissão de Combate às Discriminações e Preconceitos de Raça, Cor, Etnia, Religião e Procedência Nacional",
     ["comissao de combate as discriminacoes", "discriminacoes e preconceitos",
      "preconceitos de raca"]),
    ("Comissão de Constituição e Justiça (CCJ)",
     ["comissao de constituicao e justica", "constituicao e justica", "ccj"]),
    ("Comissão de Cultura",
     ["comissao de cultura"]),
    ("Comissão de Defesa Civil",
     ["comissao de defesa civil"]),
    ("Comissão de Defesa da Pessoa com Deficiência",
     ["comissao de defesa da pessoa com deficiencia", "pessoa com deficiencia"]),
    ("Comissão de Defesa do Consumidor",
     ["comissao de defesa do consumidor", "defesa do consumidor"]),
    ("Comissão de Defesa do Meio Ambiente",
     ["comissao de defesa do meio ambiente", "defesa do meio ambiente"]),
    ("Comissão de Defesa dos Direitos da Mulher",
     ["comissao de defesa dos direitos da mulher", "direitos da mulher"]),
    ("Comissão de Defesa dos Direitos Humanos e Cidadania",
     ["comissao de defesa dos direitos humanos", "direitos humanos e cidadania"]),
    ("Comissão de Direitos dos Animais",
     ["comissao de direitos dos animais", "direitos dos animais"]),
    ("Comissão de Economia",
     ["comissao de economia"]),
    ("Comissão de Educação",
     ["comissao de educacao"]),
    ("Comissão de Emendas Constitucionais e Vetos",
     ["comissao de emendas constitucionais", "emendas constitucionais e vetos"]),
    ("Comissão de Esporte e Lazer",
     ["comissao de esporte e lazer", "esporte e lazer"]),
    ("Comissão de Ética e Decoro Parlamentar",
     ["comissao de etica e decoro", "etica e decoro parlamentar"]),
    ("Comissão de Habitação",
     ["comissao de habitacao"]),
    ("Comissão de Indústria, Comércio e Serviços",
     ["comissao de industria, comercio", "comissao de industria e comercio",
      "industria, comercio e servicos"]),
    ("Comissão de Infraestrutura, Obras e Serviços Públicos",
     ["comissao de infraestrutura", "infraestrutura, obras e servicos publicos"]),
    ("Comissão de Legislação Constitucional Complementar e Códigos",
     ["comissao de legislacao constitucional", "legislacao constitucional complementar"]),
    ("Comissão de Minas e Energia",
     ["comissao de minas e energia", "minas e energia"]),
    ("Comissão de Normas Internas e Proposições Externas",
     ["comissao de normas internas", "normas internas e proposicoes externas"]),
    ("Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle",
     ["comissao de orcamento", "orcamento, financas", "fiscalizacao financeira e controle"]),
    ("Comissão de Política Urbana, Habitação e Assuntos Fundiários",
     ["comissao de politica urbana", "politica urbana, habitacao", "assuntos fundiarios"]),
    ("Comissão de Prevenção e Tratamento do Uso de Drogas",
     ["comissao de prevencao e tratamento do uso de drogas", "tratamento do uso de drogas"]),
    ("Comissão de Saneamento Ambiental",
     ["comissao de saneamento ambiental", "saneamento ambiental"]),
    ("Comissão de Saúde",
     ["comissao de saude"]),
    ("Comissão de Segurança Alimentar",
     ["comissao de seguranca alimentar", "seguranca alimentar"]),
    ("Comissão de Segurança Pública e Assuntos de Polícia",
     ["comissao de seguranca publica", "seguranca publica e assuntos de policia"]),
    ("Comissão de Servidores Públicos",
     ["comissao de servidores publicos", "servidores publicos"]),
    ("Comissão de TCU, Tribunal de Contas do Estado e Contratos",
     ["comissao de tcu", "tribunal de contas do estado e contratos",
      "tcu, tribunal de contas"]),
    ("Comissão de Trabalho, Legislação Social e Seguridade Social",
     ["comissao de trabalho, legislacao", "trabalho, legislacao social",
      "seguridade social"]),
    ("Comissão de Transportes",
     ["comissao de transportes"]),
]


def _norm(text: str) -> str:
    """Minúsculas + remove acentos para comparação fuzzy."""
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")


def _extract_comissoes(full_text: str, pareceres: List[Dict]) -> Optional[str]:
    """Identifica comissões usando a lista canônica da ALERJ.

    Busca no texto completo da página e nos nomes extraídos dos pareceres.
    Retorna os nomes canônicos das comissões encontradas, separados por vírgula.
    """
    # Inclui nomes de comissão dos pareceres para aumentar o recall
    extra = " ".join(p.get("comissao", "") or "" for p in pareceres)
    corpus = _norm(full_text + " " + extra)

    found: List[str] = []
    seen:  set = set()

    for nome, keywords in _COMISSOES_MAP:
        if nome in seen:
            continue
        for kw in keywords:
            if kw in corpus:
                found.append(nome)
                seen.add(nome)
                break

    return ", ".join(found) if found else None

TIPO_KEYWORDS = {
    "PL":  ["projeto de lei", "proj. lei"],
    "PR":  ["projeto de resolução", "proj. resolução", "proj. resol", "projeto de resolu"],
    "PDL": ["projeto de decreto legislativo", "proj. decreto"],
    "PEC": ["emenda constitucional", "proj. emenda"],
}


def _write_log_file(msg: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _decode_response(resp: requests.Response) -> str:
    if resp.encoding and resp.encoding.lower() not in ("utf-8", "utf8"):
        try:
            return resp.content.decode(resp.encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ENCODINGS:
        try:
            return resp.content.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return resp.text


def _infer_tipo(text: str) -> Optional[str]:
    t = text.lower()
    for tipo, keywords in TIPO_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return tipo
    return None


def _first_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or "")
    return m.group(1) if m else None


def _first_ano(text: str) -> Optional[int]:
    m = ANO_RE.search(text or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Parsing da página de detalhe
# ---------------------------------------------------------------------------

def _parse_detail(html: str, url: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(" ", strip=True)

    data: Dict = {
        "url":               url,
        "numero":            None,
        "tipo":              None,
        "ano":               None,
        "ementa":            None,
        "autor":             None,
        "data_apresentacao": None,
        "situacao":          None,
        "comissoes":         None,
        "andamento":         [],
        "pareceres":         [],
    }

    data["tipo"] = _infer_tipo(full_text)

    m = NUMERO_RE.search(full_text)
    if m:
        data["numero"] = m.group(1)
        data["ano"]    = _first_ano(m.group(1))

    m_ementa = EMENTA_RE.search(full_text)
    if m_ementa:
        data["ementa"] = " ".join(m_ementa.group(1).split())[:600]
    else:
        tables = soup.find_all("table")
        if tables:
            first_cell = tables[0].find("td")
            if first_cell:
                txt = first_cell.get_text(" ", strip=True)
                if len(txt) > 20:
                    data["ementa"] = txt[:600]

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            pairs = list(zip(cells[0::2], cells[1::2]))
            for label, value in pairs:
                lbl = label.lower()
                if "autor" in lbl and not data["autor"]:
                    data["autor"] = value.strip()
                elif "regime" in lbl and not data["situacao"]:
                    data["situacao"] = value.strip()

    if not data["autor"]:
        m_autor = AUTOR_RE.search(full_text)
        if m_autor:
            data["autor"] = " ".join(m_autor.group(1).split())

    for table in tables:
        ttext = table.get_text(" ", strip=True).lower()
        if "entrada" in ttext or "publicaç" in ttext:
            rows = table.find_all("tr")
            for row in rows:
                cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
                for j, cell in enumerate(cells):
                    if "entrada" in cell.lower() and j + 1 < len(cells):
                        d = _first_date(cells[j + 1])
                        if d:
                            data["data_apresentacao"] = d
                            break
                if data["data_apresentacao"]:
                    break

    data["andamento"] = _extract_andamento(soup)
    data["pareceres"] = _extract_pareceres(soup)
    data["comissoes"] = _extract_comissoes(full_text, data["pareceres"])

    if not data["ano"] and data.get("data_apresentacao"):
        data["ano"] = _first_ano(data["data_apresentacao"])
    if not data["tipo"]:
        data["tipo"] = "PL"

    return data


def _extract_andamento(soup: BeautifulSoup) -> List[Dict]:
    results = []
    INCLUDE_KWS = ["tramitaç", "andamento", "histórico", "moviment"]
    EXCLUDE_KWS = ["cadastro de proposi", "data public", "autor(es)"]

    for table in soup.find_all("table"):
        header_text = " ".join(
            el.get_text(" ", strip=True).lower()
            for el in table.find_all(["th", "caption"])
        )
        prev = table.find_previous(["h2", "h3", "h4", "caption", "b", "strong"])
        prev_text = prev.get_text(" ", strip=True).lower() if prev else ""
        combined = header_text + " " + prev_text

        if any(kw in combined for kw in EXCLUDE_KWS):
            continue
        if not any(kw in combined for kw in INCLUDE_KWS):
            continue

        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not any(c.strip() for c in cells):
                continue
            if all(c == c.upper() and len(c) < 30 for c in cells if c):
                continue
            date_val = None
            for c in cells:
                d = _first_date(c)
                if d:
                    date_val = d
                    break
            desc = " | ".join(c for c in cells if c.strip()).strip()
            if desc and len(desc) > 15 and "link:" not in desc.lower():
                results.append({"data": date_val, "descricao": desc[:400], "local": ""})

    return results


def _extract_pareceres(soup: BeautifulSoup) -> List[Dict]:
    results = []
    KEYWORDS = ["parecer", "relator", "comissão", "comiss"]

    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not any(kw in " ".join(headers) for kw in KEYWORDS):
            prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "strong"])
            prev_text = (prev.get_text(" ", strip=True).lower() if prev else "")
            if not any(kw in prev_text for kw in KEYWORDS):
                continue

        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not any(c.strip() for c in cells):
                continue
            date_val = None
            for c in cells:
                d = _first_date(c)
                if d:
                    date_val = d
                    break
            results.append({
                "comissao":     cells[0] if len(cells) > 0 else "",
                "relator":      cells[1] if len(cells) > 1 else "",
                "tipo_parecer": cells[2] if len(cells) > 2 else "",
                "data":         date_val,
            })
    return results


# ---------------------------------------------------------------------------
# Parsing da lista
# ---------------------------------------------------------------------------

def _extract_list_rows(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not DOC_VIEW_RE.search(href):
            continue

        full_url = ALERJLN + href if not href.startswith("http") else href
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        row = a.find_parent("tr")
        if row:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            results.append({
                "url":    full_url,
                "numero": a.get_text(strip=True) or (cells[0] if cells else ""),
                "ementa": cells[2] if len(cells) > 2 else "",
                "data":   cells[3] if len(cells) > 3 else "",
                "autor":  cells[4] if len(cells) > 4 else "",
            })
        else:
            results.append({
                "url":    full_url,
                "numero": a.get_text(strip=True),
                "ementa": "", "data": "", "autor": "",
            })

    return results


# ---------------------------------------------------------------------------
# Classe principal
# ---------------------------------------------------------------------------

class ALERJScraper:
    """
    Scraper incremental para projetos legislativos da ALERJ.
    Usa apenas requests + BeautifulSoup. Sem Selenium.
    """

    def __init__(
        self,
        delay: float = 1.5,
        log_cb: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        self.delay  = max(delay, 0.3)
        self.log_cb = log_cb
        self._stop  = False
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def stop(self):
        self._stop = True

    def log(self, msg: str):
        logger.info(msg)
        _write_log_file(msg)
        if self.log_cb:
            try:
                self.log_cb(msg)
            except Exception:
                pass

    def _get(self, url: str, retries: int = 3) -> Optional[str]:
        if self._stop:
            return None
        for attempt in range(retries):
            try:
                time.sleep(self.delay)
                resp = self._session.get(url, timeout=30)
                resp.raise_for_status()
                return _decode_response(resp)
            except requests.RequestException as exc:
                self.log(f"[AVISO] Tentativa {attempt+1}/{retries} falhou — {exc}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        self.log(f"[ERRO] Falha definitiva ao acessar: {url}")
        return None

    def _list_url(self, form_path: str, start: int) -> str:
        sep = "&" if "?" in form_path else "?"
        return ALERJLN + form_path + f"{sep}Start={start}"

    def iter_project_links(
        self,
        tipo: str,
        phase_cb: Optional[Callable] = None,
        seen: Optional[set] = None,
        form_path: Optional[str] = None,
        legislatura: str = "2023-2027",
    ) -> Generator[Dict, None, None]:
        """Itera sobre todos os links de projeto de um tipo, com paginação."""
        if form_path is None:
            form_path = LIST_FORMS.get(tipo)
        if not form_path:
            self.log(f"[ERRO] Tipo '{tipo}' não encontrado na legislatura '{legislatura}'.")
            return

        start = 1
        page  = 1
        if seen is None:
            seen = set()
        local_count = 0

        while not self._stop:
            url  = self._list_url(form_path, start)
            self.log(f"[LISTA {tipo}/{legislatura}] Página {page} — {url}")

            if phase_cb:
                phase_cb("listando", tipo=tipo, legislatura=legislatura,
                         pagina=page, links_coletados=local_count)

            html = self._get(url)
            if not html:
                self.log(f"[ERRO] Falha ao carregar página {page} — {tipo}/{legislatura}")
                break

            rows = _extract_list_rows(html)
            self.log(f"[LISTA {tipo}/{legislatura}] Página {page} — {len(rows)} encontrados")

            new_count = 0
            for row in rows:
                if row["url"] not in seen:
                    seen.add(row["url"])
                    new_count += 1
                    local_count += 1
                    row["legislatura"] = legislatura
                    yield row

            if new_count == 0:
                self.log(f"[LISTA {tipo}/{legislatura}] Fim da lista na página {page}.")
                break

            start += PAGE_SIZE
            page  += 1

    def scrape_detail(self, url: str) -> Optional[Dict]:
        html = self._get(url)
        if not html:
            return None
        return _parse_detail(html, url)

    def run_sync(
        self,
        tipos: List[str],
        legislaturas: Optional[List[str]] = None,
        mandatos=None,
        progress_cb: Optional[Callable[[int, int, Dict], None]] = None,
        phase_cb: Optional[Callable] = None,
    ) -> Dict:
        """
        Executa a coleta incremental completa.

        progress_cb(current, total, stats_dict) — chamado após cada projeto no detalhe
        phase_cb(fase, **kwargs) — chamado em cada mudança de fase/página

        Fases emitidas via phase_cb:
          listando   — tipo, legislatura, pagina, links_coletados
          iniciando  — total
          processando— atual, total, numero, tipo, legislatura
          concluido  — stats
          erro       — mensagem
        """
        import database as db

        if legislaturas is None:
            legislaturas = ["2023-2027"]

        desc = f"{', '.join(tipos)} | {', '.join(legislaturas)}"
        _write_log_file(f"=== Iniciando coleta: {desc} ===")

        stats: Dict[str, int] = {
            "novos": 0, "atualizados": 0,
            "pareceres": 0, "andamentos": 0, "erros": 0,
        }
        sync_id = db.start_sync(desc)

        try:
            # FASE 1 — Coleta de listas
            all_links: List[Tuple[str, Dict]] = []
            seen_urls: set = set()

            for leg in legislaturas:
                if self._stop:
                    break
                leg_forms = LEGISLATURAS.get(leg)
                if not leg_forms:
                    self.log(f"[AVISO] Legislatura '{leg}' não reconhecida. Ignorando.")
                    continue

                for tipo in tipos:
                    if self._stop:
                        break
                    form_path = leg_forms.get(tipo)
                    if not form_path:
                        self.log(f"[AVISO] Tipo '{tipo}' não disponível em '{leg}'.")
                        continue

                    self.log(f"=== FASE 1 — {tipo} / {leg} ===")
                    for link in self.iter_project_links(
                        tipo, phase_cb=phase_cb, seen=seen_urls,
                        form_path=form_path, legislatura=leg,
                    ):
                        all_links.append((tipo, link))

                    count_leg_tipo = sum(
                        1 for t, l in all_links
                        if t == tipo and l.get("legislatura") == leg
                    )
                    self.log(f"[{tipo}/{leg}] Links coletados: {count_leg_tipo}")

            total = len(all_links)
            self.log(f"=== FASE 2 — Total de projetos para processar: {total} ===")

            if phase_cb:
                phase_cb("iniciando", total=total)

            if total == 0:
                self.log("[AVISO] Nenhum projeto encontrado nas listas. Verifique a conectividade com alerjln1.alerj.rj.gov.br")
                db.finish_sync(sync_id, stats, status="completed")
                if phase_cb:
                    phase_cb("concluido", stats=stats)
                return stats

            # FASE 2 — Coleta de detalhes
            for i, (tipo, link_data) in enumerate(all_links):
                if self._stop:
                    self.log("Coleta interrompida pelo usuário.")
                    break

                url    = link_data["url"]
                numero = link_data.get("numero", "?")
                self.log(f"[{i+1}/{total}] {tipo} {numero} — {url}")

                leg = link_data.get("legislatura", "2023-2027")

                if phase_cb:
                    phase_cb("processando", atual=i + 1, total=total,
                             numero=numero, tipo=tipo, legislatura=leg)

                quick: Dict = {
                    "url":               url,
                    "tipo":              tipo,
                    "legislatura":       leg,
                    "numero":            numero,
                    "ementa":            link_data.get("ementa", ""),
                    "autor":             link_data.get("autor", ""),
                    "data_apresentacao": link_data.get("data", ""),
                    "ano":               _first_ano(link_data.get("data", "") or ""),
                    "situacao":          None,
                    "comissoes":         None,
                }

                detail = self.scrape_detail(url)
                if detail:
                    project_data = {**quick}
                    for k, v in detail.items():
                        if k not in ("andamento", "pareceres") and v is not None:
                            project_data[k] = v
                else:
                    project_data = quick
                    stats["erros"] += 1
                    self.log(f"  [AVISO] Sem detalhe para {url}")

                project_data["tipo"] = tipo

                is_new, is_upd = db.upsert_projeto(project_data)
                if is_new:
                    stats["novos"] += 1
                    self.log(f"  ✔ NOVO: {project_data.get('numero','?')}")
                elif is_upd:
                    stats["atualizados"] += 1
                    self.log(f"  ↑ Atualizado: {project_data.get('numero','?')}")
                else:
                    self.log(f"  = Sem alteração: {project_data.get('numero','?')}")

                if detail:
                    pid = db.get_projeto_id(url)
                    if pid:
                        for a in detail.get("andamento", []):
                            if db.insert_andamento(pid, a):
                                stats["andamentos"] += 1
                        for p in detail.get("pareceres", []):
                            if db.insert_parecer(pid, p):
                                stats["pareceres"] += 1

                if progress_cb:
                    progress_cb(i + 1, total, dict(stats))

        except Exception as exc:
            tb = traceback.format_exc()
            self.log(f"[ERRO CRÍTICO] {exc}")
            self.log(tb)
            stats["erros"] += 1
            db.finish_sync(sync_id, stats, status="error")
            if phase_cb:
                phase_cb("erro", mensagem=str(exc))
            raise

        db.finish_sync(sync_id, stats)
        resumo = (
            f"Coleta finalizada — "
            f"Novos: {stats['novos']} | "
            f"Atualizados: {stats['atualizados']} | "
            f"Pareceres: {stats['pareceres']} | "
            f"Andamentos: {stats['andamentos']} | "
            f"Erros: {stats['erros']}"
        )
        self.log(resumo)

        if phase_cb:
            phase_cb("concluido", stats=dict(stats))

        return stats
