"""
Gerenciamento do banco de dados SQLite.
Tabelas: usuarios, produtos
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "botprecos.db")


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar():
    """Cria as tabelas se não existirem."""
    conn = conectar()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            chat_id     INTEGER PRIMARY KEY,
            username    TEXT,
            nome        TEXT,
            ativo       INTEGER DEFAULT 1,
            criado_em   TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id         INTEGER NOT NULL,
            nome            TEXT NOT NULL,
            busca           TEXT NOT NULL,
            modelo          TEXT,
            preco_alvo      REAL,
            preco_mercado   REAL,
            horario         TEXT DEFAULT '08:00',
            ativo           INTEGER DEFAULT 1,
            criado_em       TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (chat_id) REFERENCES usuarios(chat_id)
        )
    """)

    conn.commit()
    conn.close()


# ── Usuários ──────────────────────────────────────────────────────────────────

def salvar_usuario(chat_id: int, username: str, nome: str):
    conn = conectar()
    conn.execute("""
        INSERT INTO usuarios (chat_id, username, nome)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, nome=excluded.nome
    """, (chat_id, username, nome))
    conn.commit()
    conn.close()


def total_usuarios() -> int:
    conn = conectar()
    total = conn.execute("SELECT COUNT(*) FROM usuarios WHERE ativo=1").fetchone()[0]
    conn.close()
    return total


def listar_usuarios():
    conn = conectar()
    rows = conn.execute("""
        SELECT u.chat_id, u.username, u.nome, u.criado_em,
               COUNT(p.id) as total_produtos
        FROM usuarios u
        LEFT JOIN produtos p ON p.chat_id = u.chat_id AND p.ativo = 1
        GROUP BY u.chat_id
        ORDER BY u.criado_em DESC
    """).fetchall()
    conn.close()
    return rows


# ── Produtos ──────────────────────────────────────────────────────────────────

def contar_produtos_usuario(chat_id: int) -> int:
    conn = conectar()
    total = conn.execute(
        "SELECT COUNT(*) FROM produtos WHERE chat_id=? AND ativo=1", (chat_id,)
    ).fetchone()[0]
    conn.close()
    return total


def salvar_produto(chat_id: int, nome: str, busca: str, modelo: str,
                   preco_alvo: float, preco_mercado: float, horario: str):
    conn = conectar()
    # Remove produto anterior (limite de 1 por usuário)
    conn.execute("UPDATE produtos SET ativo=0 WHERE chat_id=?", (chat_id,))
    conn.execute("""
        INSERT INTO produtos (chat_id, nome, busca, modelo, preco_alvo, preco_mercado, horario)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, nome, busca, modelo, preco_alvo, preco_mercado, horario))
    conn.commit()
    conn.close()


def remover_produto(chat_id: int):
    conn = conectar()
    conn.execute("UPDATE produtos SET ativo=0 WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()


def buscar_produto_usuario(chat_id: int):
    conn = conectar()
    row = conn.execute(
        "SELECT * FROM produtos WHERE chat_id=? AND ativo=1 LIMIT 1", (chat_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def produtos_por_horario(horario: str):
    """Retorna todos os produtos ativos para um determinado horário."""
    conn = conectar()
    rows = conn.execute("""
        SELECT p.*, u.chat_id as dest_chat_id
        FROM produtos p
        JOIN usuarios u ON u.chat_id = p.chat_id
        WHERE p.ativo=1 AND p.horario=? AND u.ativo=1
    """, (horario,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def todos_produtos_ativos():
    """Retorna todos os produtos ativos (para rodar buscas agendadas)."""
    conn = conectar()
    rows = conn.execute("""
        SELECT p.*, u.chat_id as dest_chat_id
        FROM produtos p
        JOIN usuarios u ON u.chat_id = p.chat_id
        WHERE p.ativo=1 AND u.ativo=1
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
