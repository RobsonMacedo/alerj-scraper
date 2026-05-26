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
NUMERO_RE    = re.compile(r"[Nn][º°\.]\s*(\d+(?:-[A-Z])?/\d{4})")
EMENTA_RE    = re.compile(r"EMENTA\s*[:：]\s*(.+?)(?=\s*Autor\(es\)|\s*JUSTIFICATIVA|$)", re.DOTALL)
AUTOR_RE     = re.compile(r"Autor\(es\)\s*:\s*(?:Deputad[oa]s?\s+)?([A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ,\s]+?)(?=\s*A ASSEMBLEIA|\s*RESOLVE|$)", re.DOTALL)
# ---------------------------------------------------------------------------
# Comissões permanentes da ALERJ — lista canônica e extrator
# ---------------------------------------------------------------------------

# Lista canônica oficial das 37 comissões permanentes da ALERJ (biênio 2025-2026).
# Fonte: www.alerj.rj.gov.br > Processo Legislativo > Comissões Permanentes.
# Inclui palavras-chave de nomes históricos para compatibilidade com dados anteriores.
# (nome_canônico, [palavras-chave ASCII-normalizadas — qualquer uma serve para identificar])
_COMISSOES_MAP: List[Tuple[str, List[str]]] = [
    # 1
    ("Comissão de Constituição e Justiça (CCJ)",
     ["constituicao e justica", "ccj"]),
    # 2 — nome com vírgulas; armazenado como string única, split usa lógica especial
    ("Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle",
     ["comissao de orcamento", "orcamento, financas", "fiscalizacao financeira e controle",
      "orcamento e financas"]),
    # 3 — nova comissão 2025
    ("Comissão de Tributação, Controle da Arrecadação Estadual e de Fiscalização dos Tributos Estaduais",
     ["comissao de tributacao", "tributacao, controle da arrecadacao",
      "fiscalizacao dos tributos estaduais"]),
    # 4 — nome atualizado (era "Políticas Rurais", agora "Rural, Agrária e Pesqueira")
    ("Comissão de Agricultura, Pecuária e Políticas Rural, Agrária e Pesqueira",
     ["comissao de agricultura", "pecuaria e politicas rural", "agraria e pesqueira",
      "politicas rurais"]),
    # 5
    ("Comissão de Assuntos da Criança, do Adolescente e do Idoso",
     ["assuntos da crianca", "crianca, do adolescente", "crianca e do adolescente"]),
    # 6
    ("Comissão de Assuntos Municipais e de Desenvolvimento Regional",
     ["assuntos municipais", "desenvolvimento regional"]),
    # 7
    ("Comissão de Ciência e Tecnologia",
     ["ciencia e tecnologia"]),
    # 8
    ("Comissão de Combate às Discriminações e Preconceitos de Raça, Cor, Etnia, Religião e Procedência Nacional",
     ["combate as discriminacoes", "discriminacoes e preconceitos", "preconceitos de raca"]),
    # 9
    ("Comissão de Cultura",
     ["comissao de cultura"]),
    # 10
    ("Comissão de Defesa dos Direitos Humanos e Cidadania",
     ["defesa dos direitos humanos", "direitos humanos e cidadania"]),
    # 11
    ("Comissão de Defesa Civil",
     ["comissao de defesa civil"]),
    # 12
    ("Comissão de Defesa do Consumidor",
     ["defesa do consumidor"]),
    # 13
    ("Comissão de Defesa do Meio Ambiente",
     ["defesa do meio ambiente"]),
    # 14
    ("Comissão de Defesa dos Direitos da Mulher",
     ["direitos da mulher"]),
    # 15 — renomeada (era "Comissão de Direitos dos Animais")
    ("Comissão de Defesa e Proteção dos Animais no Estado do Rio de Janeiro",
     ["defesa e protecao dos animais", "protecao dos animais", "direitos dos animais"]),
    # 16 — fundida (era "Comissão de Economia" + "Comissão de Indústria, Comércio e Serviços")
    ("Comissão de Economia, Indústria e Comércio",
     ["economia, industria e comercio", "comissao de economia",
      "industria, comercio e servicos", "industria e comercio"]),
    # 17 — renomeada (era "Comissão de Defesa da Pessoa com Deficiência")
    ("Comissão de Pessoa com Deficiência",
     ["pessoa com deficiencia", "defesa da pessoa com deficiencia"]),
    # 18
    ("Comissão de Emendas Constitucionais e Vetos",
     ["emendas constitucionais e vetos", "emendas constitucionais"]),
    # 19
    ("Comissão de Educação",
     ["comissao de educacao"]),
    # 20
    ("Comissão de Esporte e Lazer",
     ["esporte e lazer"]),
    # 21
    ("Comissão de Minas e Energia",
     ["minas e energia"]),
    # 22
    ("Comissão de Legislação Constitucional Complementar e Códigos",
     ["legislacao constitucional complementar"]),
    # 23 — renomeada (era "Comissão de Infraestrutura, Obras e Serviços Públicos")
    ("Comissão de Obras Públicas",
     ["comissao de obras publicas", "obras publicas",
      "infraestrutura, obras e servicos publicos", "comissao de infraestrutura"]),
    # 24
    ("Comissão de Normas Internas e Proposições Externas",
     ["normas internas e proposicoes externas", "normas internas"]),
    # 25 — renomeada (era "Comissão de Prevenção e Tratamento do Uso de Drogas")
    ("Comissão de Prevenção ao Uso de Drogas e Dependentes Químicos em Geral",
     ["prevencao ao uso de drogas", "dependentes quimicos",
      "prevencao e tratamento do uso de drogas", "tratamento do uso de drogas"]),
    # 26 — "Habitação" agora só existe aqui (era também comissão separada)
    ("Comissão de Política Urbana, Habitação e Assuntos Fundiários",
     ["politica urbana, habitacao", "assuntos fundiarios", "comissao de habitacao"]),
    # 27
    ("Comissão de Saúde",
     ["comissao de saude"]),
    # 28 — nova comissão 2025
    ("Comissão de Redação",
     ["comissao de redacao"]),
    # 29
    ("Comissão de Segurança Alimentar",
     ["seguranca alimentar"]),
    # 30
    ("Comissão de Saneamento Ambiental",
     ["saneamento ambiental"]),
    # 31
    ("Comissão de Servidores Públicos",
     ["servidores publicos"]),
    # 32
    ("Comissão de Segurança Pública e Assuntos de Polícia",
     ["seguranca publica e assuntos de policia", "seguranca publica"]),
    # 33
    ("Comissão de Transportes",
     ["comissao de transportes"]),
    # 34
    ("Comissão de Trabalho, Legislação Social e Seguridade Social",
     ["trabalho, legislacao social", "seguridade social"]),
    # 35 — nova comissão 2025
    ("Comissão de Turismo",
     ["comissao de turismo"]),
    # 36 — nova comissão 2025
    ("Comissão para Prevenir e Combater a Pirataria no Estado do Rio de Janeiro",
     ["prevenir e combater a pirataria", "combater a pirataria", "pirataria no estado"]),
    # 37 — renomeada (era "Comissão de Ética e Decoro Parlamentar")
    ("Comissão de Conselho de Ética e Decoro Parlamentar",
     ["conselho de etica e decoro", "etica e decoro parlamentar"]),
    # Histórico — pode aparecer em dados de 2019-2023
    ("Comissão de Administração e Serviço Público",
     ["administracao e servico publico"]),
    ("Comissão de TCU, Tribunal de Contas do Estado e Contratos",
     ["tcu, tribunal de contas", "tribunal de contas do estado e contratos"]),
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
        _last_lbl = ""
        for row in rows:
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            pairs = list(zip(cells[0::2], cells[1::2]))
            for label, value in pairs:
                lbl = label.strip().lower()
                effective = lbl if lbl else _last_lbl
                if lbl:
                    _last_lbl = lbl
                val = value.strip()
                if not val:
                    continue
                if "autor" in effective:
                    if not data["autor"]:
                        data["autor"] = val
                    elif not lbl:
                        # linha de continuação (label vazio): agrega coautores
                        data["autor"] = data["autor"].rstrip(", ") + ", " + val
                elif "regime" in effective and not data["situacao"]:
                    data["situacao"] = val

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
    """
    Captura a tabela de TRAMITAÇÃO da ALERJ.
    Cada linha tem: [descrição com "=>", data].
    A tabela é identificada pelo elemento anterior contendo "tramitac" + "projeto"
    (normalizado ASCII para tolerar encoding variável do servidor ALERJ).
    """
    results = []
    seen: set = set()

    for table in soup.find_all("table"):
        prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "strong", "font"])
        prev_norm = _norm(prev.get_text(" ", strip=True)) if prev else ""

        # Identifica pelo título: "TRAMITAÇÃO DO PROJETO ..."
        if "tramitac" not in prev_norm or "projeto" not in prev_norm:
            continue

        for row in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            non_empty = [c.strip() for c in cells if c.strip()]

            # Linhas válidas têm "=>" e o primeiro segmento é curto (nome da ação, não ementa)
            for c in non_empty:
                if "=>" not in c or len(c) < 10:
                    continue
                first_segment = c.split("=>")[0].strip()
                if len(first_segment) > 80:  # célula concatenada da tabela aninhada
                    continue

                date_val = None
                for d_cell in non_empty:
                    d = _first_date(d_cell)
                    if d:
                        date_val = d
                        break

                key = _norm(c[:100])   # só o texto normalizado evita dupl. por data None vs data real
                if key in seen:
                    continue
                seen.add(key)

                results.append({"data": date_val, "descricao": c[:500], "local": ""})

    return results


# Captura tanto "Distribuicao" quanto "Parecer em Plenario" com relator E parecer preenchido.
_PAR_TRAM_RE = re.compile(
    r"(?P<acao>distribuicao|parecer em plenario|redistribuicao)\s*=>\s*\S+\s*=>\s*"
    r"(?P<comissao>[^=]+?)\s*=>\s*relator:\s*"
    r"(?P<relator>[^=]{1,100}?)\s*=>"
    r"(?:[^=]{1,200}=>\s*)*"
    r"parecer:\s*(?P<tipo>[^=]{1,400})",
    re.IGNORECASE,
)

# Captura apenas o relator (quando "Parecer:" está vazio ou ausente).
_REL_TRAM_RE = re.compile(
    r"(?:distribuicao|parecer em plenario|redistribuicao)\s*=>\s*\S+\s*=>\s*"
    r"(?P<comissao>[^=]+?)\s*=>\s*relator:\s*"
    r"(?P<relator>[^=]{1,100})",
    re.IGNORECASE,
)


def _normalize_tipo(tipo: str) -> str:
    """Normaliza o texto do tipo de parecer para uma etiqueta legível."""
    t = tipo.lower().strip()
    # Favorável — verificar variantes específicas antes do genérico
    if "favoravel com substitut" in t or ("substitutivo" in t and "favoravel" in t):
        return "Favorável com Substitutivo"
    if "favoravel com emenda" in t or "favoravel, com emenda" in t:
        return "Favorável com Emendas"
    if "favoravel" in t:
        return "Favorável"
    # Contrário
    if "contrario" in t:
        return "Contrário"
    # Constitucionalidade — verificar variantes com emendas antes do genérico
    if "inconstitucionalidade com emenda" in t:
        return "Pela Inconstitucionalidade com Emendas"
    if "pela inconstitucionalidade" in t or ("inconstitucionalidade" in t and "emenda" not in t):
        return "Pela Inconstitucionalidade"
    if "constitucionalidade com emenda" in t:
        return "Pela Constitucionalidade com Emendas"
    if "constitucionalidade" in t:
        return "Pela Constitucionalidade"
    # Outros
    if "departamento de apoio" in t or "comissoes permanentes" in t:
        return "Aguardando relator"
    if "prejudicado" in t:
        return "Prejudicado"
    if "aprovado" in t:
        return "Aprovado"
    cleaned = tipo.strip()[:80]
    return cleaned[0].upper() + cleaned[1:] if cleaned else tipo


def _extract_pareceres(soup: BeautifulSoup) -> List[Dict]:
    """
    Extrai pareceres das comissões da tramitação ALERJ.
    Passo 1: captura entradas com relator + parecer preenchido.
    Passo 2: para comissões sem parecer, captura apenas o relator
             designado (tipo = 'Aguardando parecer').
    Prioriza 'Parecer em Plenário' sobre 'Distribuição' para a mesma comissão.
    """
    results_map: dict = {}

    all_cells_with_date: List[tuple] = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            date_val = None
            for c in cells:
                d = _first_date(c)
                if d:
                    date_val = d
                    break
            for c in cells:
                if "=>" in c and len(c.split("=>")[0].strip()) <= 80:
                    all_cells_with_date.append((c, date_val))

    # Passo 1: relator + parecer completo
    for c, date_val in all_cells_with_date:
        c_norm = _norm(c)
        m = _PAR_TRAM_RE.search(c_norm)
        if not m:
            continue
        acao       = m.group("acao").strip()
        comissao_n = m.group("comissao").strip()
        relator_n  = m.group("relator").strip()
        tipo_n     = m.group("tipo").strip()

        comissao = _recover_original(c, comissao_n)
        relator  = _recover_original(c, relator_n)
        tipo     = _normalize_tipo(tipo_n)
        is_plen  = "plenario" in acao

        existing = results_map.get(comissao_n)
        if not existing or (is_plen and not existing["is_plen"]):
            results_map[comissao_n] = {
                "comissao":     comissao,
                "relator":      relator,
                "tipo_parecer": tipo,
                "data":         date_val,
                "is_plen":      is_plen,
            }

    # Passo 2: apenas relator designado (parecer ainda não emitido)
    for c, date_val in all_cells_with_date:
        c_norm = _norm(c)
        m = _REL_TRAM_RE.search(c_norm)
        if not m:
            continue
        comissao_n = m.group("comissao").strip()
        relator_n  = m.group("relator").strip()
        if comissao_n in results_map:
            continue  # já tem dado melhor do passo 1
        comissao = _recover_original(c, comissao_n)
        relator  = _recover_original(c, relator_n)
        results_map[comissao_n] = {
            "comissao":     comissao,
            "relator":      relator,
            "tipo_parecer": "Aguardando parecer",
            "data":         date_val,
            "is_plen":      False,
        }

    # Remove duplicatas da linha do tempo e ordena
    return [
        {k: v for k, v in r.items() if k != "is_plen"}
        for r in results_map.values()
    ]


def _recover_original(original: str, norm_fragment: str) -> str:
    """
    Tenta recuperar o trecho original a partir de um fragmento normalizado.
    Percorre o original por janelas deslizantes do mesmo comprimento e
    retorna o trecho cujo _norm() coincide com norm_fragment.
    """
    target_len = len(norm_fragment)
    # Varredura: fatias de comprimento target_len ± 4 (acento pode variar o tamanho)
    for extra in range(0, 6):
        for start in range(len(original)):
            for length in (target_len + extra, target_len - extra):
                if length <= 0:
                    continue
                candidate = original[start:start + length]
                if _norm(candidate) == norm_fragment:
                    return candidate.strip()
    return norm_fragment  # fallback: retorna normalizado


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
                    # Protege sufixo: se a lista trouxe "5137-A/2025" mas o detalhe
                    # parseou apenas "5137/2025" (regex sem sufixo), mantém o da lista.
                    _suffix_re = re.compile(r"-[A-Z]/")
                    if quick.get("numero") and _suffix_re.search(quick["numero"]):
                        detail_num = detail.get("numero") or ""
                        if not _suffix_re.search(detail_num):
                            project_data["numero"] = quick["numero"]
                            self.log(f"  [INFO] Número preservado da lista: {quick['numero']}")
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
