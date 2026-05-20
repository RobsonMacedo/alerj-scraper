"""
Módulo de acesso ao banco de dados SQLite para o scraper da ALERJ.
"""

import sqlite3
import hashlib
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple

DB_PATH = Path(__file__).parent / "data" / "alerj.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()

    # 1) Tabelas (sem índices que dependem de colunas que podem não existir ainda)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projetos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            numero            TEXT,
            tipo              TEXT,
            ano               INTEGER,
            ementa            TEXT,
            autor             TEXT,
            data_apresentacao TEXT,
            situacao          TEXT,
            comissoes         TEXT,
            url               TEXT UNIQUE NOT NULL,
            hash_conteudo     TEXT,
            criado_em         TEXT DEFAULT (datetime('now','localtime')),
            atualizado_em     TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS andamento (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
            data       TEXT,
            descricao  TEXT NOT NULL,
            local      TEXT,
            criado_em  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS pareceres (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            projeto_id   INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
            comissao     TEXT,
            relator      TEXT,
            tipo_parecer TEXT,
            data         TEXT,
            criado_em    TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            data_inicio          TEXT DEFAULT (datetime('now','localtime')),
            data_fim             TEXT,
            tipos                TEXT,
            projetos_novos       INTEGER DEFAULT 0,
            projetos_atualizados INTEGER DEFAULT 0,
            pareceres_novos      INTEGER DEFAULT 0,
            andamentos_novos     INTEGER DEFAULT 0,
            erros                INTEGER DEFAULT 0,
            status               TEXT DEFAULT 'running'
        );
    """)
    conn.commit()

    # 2a) Migração: adiciona coluna legislatura se não existir
    try:
        conn.execute("ALTER TABLE projetos ADD COLUMN legislatura TEXT DEFAULT '2023-2027'")
        conn.execute("UPDATE projetos SET legislatura='2023-2027' WHERE legislatura IS NULL")
        conn.commit()
    except Exception:
        pass  # coluna já existe


    # 3) Índices (agora a coluna legislatura já existe com certeza)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_proj_tipo   ON projetos(tipo);
        CREATE INDEX IF NOT EXISTS idx_proj_leg    ON projetos(legislatura);
        CREATE INDEX IF NOT EXISTS idx_proj_ano    ON projetos(ano);
        CREATE INDEX IF NOT EXISTS idx_proj_autor  ON projetos(autor);
        CREATE INDEX IF NOT EXISTS idx_and_projeto ON andamento(projeto_id);
        CREATE INDEX IF NOT EXISTS idx_par_projeto ON pareceres(projeto_id);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_andamento
            ON andamento(projeto_id, COALESCE(data,''), descricao);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_pareceres
            ON pareceres(projeto_id, COALESCE(comissao,''), COALESCE(data,''));
    """)
    conn.commit()
    conn.close()


def _content_hash(data: Dict) -> str:
    keys = ["numero", "tipo", "legislatura", "ano", "ementa", "autor", "situacao", "comissoes"]
    subset = {k: str(data.get(k, "") or "") for k in keys}
    return hashlib.md5(
        json.dumps(subset, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def upsert_projeto(data: Dict) -> Tuple[bool, bool]:
    """Insere ou atualiza um projeto. Retorna (is_new, is_updated)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        h = _content_hash(data)
        row = cur.execute(
            "SELECT id, hash_conteudo FROM projetos WHERE url = ?", (data["url"],)
        ).fetchone()

        if row is None:
            cur.execute(
                """INSERT OR IGNORE INTO projetos
                   (numero, tipo, legislatura, ano, ementa, autor, data_apresentacao,
                    situacao, comissoes, url, hash_conteudo)
                   VALUES (:numero,:tipo,:legislatura,:ano,:ementa,:autor,:data_apresentacao,
                           :situacao,:comissoes,:url,:hash)""",
                {**data, "hash": h, "legislatura": data.get("legislatura", "2023-2027")},
            )
            conn.commit()
            changed = conn.execute("SELECT changes()").fetchone()[0]
            return changed > 0, False

        if row["hash_conteudo"] != h:
            cur.execute(
                """UPDATE projetos
                   SET numero=:numero, tipo=:tipo, legislatura=:legislatura,
                       ano=:ano, ementa=:ementa, autor=:autor,
                       data_apresentacao=:data_apresentacao,
                       situacao=:situacao, comissoes=:comissoes,
                       hash_conteudo=:hash,
                       atualizado_em=datetime('now','localtime')
                   WHERE url=:url""",
                {**data, "hash": h, "legislatura": data.get("legislatura", "2023-2027")},
            )
            conn.commit()
            return False, True

        return False, False
    finally:
        conn.close()


def get_legislaturas() -> List[str]:
    """Retorna lista de legislaturas que têm projetos no banco."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT DISTINCT legislatura FROM projetos
               WHERE legislatura IS NOT NULL
               ORDER BY legislatura DESC"""
        ).fetchall()
        return [r["legislatura"] for r in rows]
    finally:
        conn.close()


def get_projeto_id(url: str) -> Optional[int]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM projetos WHERE url = ?", (url,)
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def insert_andamento(projeto_id: int, data: Dict) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO andamento (projeto_id, data, descricao, local)
               VALUES (?, ?, ?, ?)""",
            (projeto_id, data.get("data"), data.get("descricao", ""), data.get("local")),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    finally:
        conn.close()


def insert_parecer(projeto_id: int, data: Dict) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO pareceres
               (projeto_id, comissao, relator, tipo_parecer, data)
               VALUES (?, ?, ?, ?, ?)""",
            (
                projeto_id,
                data.get("comissao"),
                data.get("relator"),
                data.get("tipo_parecer"),
                data.get("data"),
            ),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    finally:
        conn.close()


def get_stats() -> Dict:
    conn = get_connection()
    try:
        def scalar(q, p=()):
            return conn.execute(q, p).fetchone()[0]

        last = conn.execute(
            "SELECT * FROM sync_log WHERE status='completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        return {
            "total_projetos":  scalar("SELECT COUNT(*) FROM projetos"),
            "total_pl":        scalar("SELECT COUNT(*) FROM projetos WHERE tipo='PL'"),
            "total_pr":        scalar("SELECT COUNT(*) FROM projetos WHERE tipo='PR'"),
            "total_pareceres": scalar("SELECT COUNT(*) FROM pareceres"),
            "total_andamentos":scalar("SELECT COUNT(*) FROM andamento"),
            "ultima_sync":     dict(last) if last else None,
        }
    finally:
        conn.close()


def start_sync(tipos: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO sync_log (tipos) VALUES (?)", (tipos,)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def finish_sync(sync_id: int, stats: Dict, status: str = "completed"):
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE sync_log
               SET data_fim=datetime('now','localtime'), status=?,
                   projetos_novos=?, projetos_atualizados=?,
                   pareceres_novos=?, andamentos_novos=?, erros=?
               WHERE id=?""",
            (
                status,
                stats.get("novos", 0),
                stats.get("atualizados", 0),
                stats.get("pareceres", 0),
                stats.get("andamentos", 0),
                stats.get("erros", 0),
                sync_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_projetos(
    tipo=None, legislatura=None, ano=None, autor=None, busca=None, limit=200, offset=0
) -> List[Dict]:
    conn = get_connection()
    try:
        clauses, params = ["1=1"], []
        if tipo:
            clauses.append("tipo = ?"); params.append(tipo)
        if legislatura:
            clauses.append("legislatura = ?"); params.append(legislatura)
        if ano:
            clauses.append("ano = ?"); params.append(int(ano))
        if autor:
            clauses.append("autor LIKE ?"); params.append(f"%{autor}%")
        if busca:
            clauses.append("(ementa LIKE ? OR numero LIKE ? OR autor LIKE ?)")
            params += [f"%{busca}%", f"%{busca}%", f"%{busca}%"]
        params += [limit, offset]
        rows = conn.execute(
            f"""SELECT * FROM projetos WHERE {' AND '.join(clauses)}
                ORDER BY atualizado_em DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pareceres(comissao=None, relator=None, limit=200) -> List[Dict]:
    conn = get_connection()
    try:
        clauses, params = ["1=1"], []
        if comissao:
            clauses.append("p.comissao LIKE ?"); params.append(f"%{comissao}%")
        if relator:
            clauses.append("p.relator LIKE ?"); params.append(f"%{relator}%")
        params.append(limit)
        rows = conn.execute(
            f"""SELECT p.*, pr.numero, pr.tipo, pr.ementa, pr.url AS projeto_url
                FROM pareceres p
                JOIN projetos pr ON pr.id = p.projeto_id
                WHERE {' AND '.join(clauses)}
                ORDER BY p.criado_em DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_andamentos(projeto_id: int) -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM andamento WHERE projeto_id=? ORDER BY data DESC",
            (projeto_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sync_logs(limit: int = 30) -> List[Dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_anos_disponiveis() -> List[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT ano FROM projetos WHERE ano IS NOT NULL ORDER BY ano DESC"
        ).fetchall()
        return [r["ano"] for r in rows]
    finally:
        conn.close()


def count_projetos() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM projetos").fetchone()[0]
    finally:
        conn.close()


def count_projetos_filtered(
    tipo=None, legislatura=None, ano=None, autor=None, busca=None
) -> int:
    conn = get_connection()
    try:
        clauses, params = ["1=1"], []
        if tipo:
            clauses.append("tipo = ?"); params.append(tipo)
        if legislatura:
            clauses.append("legislatura = ?"); params.append(legislatura)
        if ano:
            clauses.append("ano = ?"); params.append(int(ano))
        if autor:
            clauses.append("autor LIKE ?"); params.append(f"%{autor}%")
        if busca:
            clauses.append("(ementa LIKE ? OR numero LIKE ? OR autor LIKE ?)")
            params += [f"%{busca}%", f"%{busca}%", f"%{busca}%"]
        return conn.execute(
            f"SELECT COUNT(*) FROM projetos WHERE {' AND '.join(clauses)}", params
        ).fetchone()[0]
    finally:
        conn.close()
