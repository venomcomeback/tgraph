"""
TGraph - SQLite Veritabanı Yönetimi
Senkron sqlite3 kullanılır (thread-safe erişim için her çağrıda bağlantı açılır).
"""
import sqlite3
import csv
import os
import datetime
from typing import List, Dict, Optional, Any

from .config import DB_PATH, DEFAULT_SETTINGS, STATUS_UNKNOWN


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """SQLite veritabanı sarmalayıcısı."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT UNIQUE NOT NULL,
                phone TEXT,
                name TEXT,
                api_id TEXT,
                api_hash TEXT,
                proxy_id INTEGER,
                is_active INTEGER DEFAULT 0,
                added_date TEXT,
                status TEXT DEFAULT 'unknown',
                FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                access_hash TEXT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                group_source TEXT,
                scraped_date TEXT,
                is_added INTEGER DEFAULT 0,
                added_by_account TEXT,
                last_seen TEXT,
                lang_code TEXT,
                is_bot INTEGER DEFAULT 0,
                UNIQUE(user_id, group_source)
            );

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                group_name TEXT,
                group_link TEXT,
                member_count INTEGER DEFAULT 0,
                last_scraped TEXT
            );

            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_type TEXT DEFAULT 'socks5',
                host TEXT,
                port INTEGER,
                username TEXT,
                password TEXT,
                is_active INTEGER DEFAULT 1,
                last_check TEXT,
                is_working INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS api_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_id TEXT NOT NULL,
                api_hash TEXT NOT NULL,
                extra TEXT DEFAULT '',
                added_date TEXT
            );
            """
        )
        conn.commit()
        # --- Geriye dönük uyumlu şema göçleri (yalnızca eksik kolon ekleme) ---
        self._ensure_column(cur, "accounts", "assigned_proxy_id", "INTEGER")
        conn.commit()
        # Varsayılan ayarları ekle
        for k, v in DEFAULT_SETTINGS.items():
            cur.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        conn.commit()
        conn.close()

    @staticmethod
    def _ensure_column(cur, table: str, column: str, coltype: str):
        """Tabloda kolon yoksa ekler (veri kaybı olmadan, geriye dönük uyumlu)."""
        cols = [r["name"] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    # ================================================================== #
    #  ACCOUNTS
    # ================================================================== #
    def add_account(self, session_name: str, phone: str = "", name: str = "",
                    api_id: str = "", api_hash: str = "", proxy_id: Optional[int] = None,
                    status: str = STATUS_UNKNOWN) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO accounts
               (id, session_name, phone, name, api_id, api_hash, proxy_id, is_active, added_date, status)
               VALUES (
                 (SELECT id FROM accounts WHERE session_name = ?),
                 ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (session_name, session_name, phone, name, api_id, api_hash, proxy_id, _now(), status),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    def update_account(self, account_id: int, **fields):
        if not fields:
            return
        keys = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [account_id]
        conn = self._connect()
        conn.execute(f"UPDATE accounts SET {keys} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    def get_accounts(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """SELECT a.*, p.host AS proxy_host, p.port AS proxy_port, p.proxy_type AS proxy_type
               FROM accounts a LEFT JOIN proxies p ON a.proxy_id = p.id
               ORDER BY a.id"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_active_accounts(self) -> List[Dict[str, Any]]:
        return [a for a in self.get_accounts() if a.get("is_active")]

    def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_account(self, account_id: int):
        conn = self._connect()
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()

    def get_account_proxy(self, account: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Hesabın kullanacağı proxy'yi döndürür.
        Öncelik: atanmış proxy (assigned_proxy_id) > manuel proxy (proxy_id).
        """
        if not account:
            return None
        pid = account.get("assigned_proxy_id") or account.get("proxy_id")
        if not pid:
            return None
        return self.get_proxy(pid)

    def assign_proxies_to_accounts(self, account_ids: Optional[List[int]] = None,
                                   only_working: bool = True) -> Dict[str, Any]:
        """TR (çalışan) proxy havuzunu aktif hesaplara round-robin dağıtır.

        * account_ids verilmezse tüm aktif hesaplar kullanılır.
        * only_working=True ise yalnızca test edilip çalışan proxy'ler dağıtılır;
          çalışan yoksa tüm proxy'lere düşülür.
        Dönüş: {'accounts': N, 'proxies': M, 'assigned': K}
        """
        # Hedef hesaplar
        if account_ids:
            accounts = [a for a in self.get_accounts() if a["id"] in set(account_ids)]
        else:
            accounts = self.get_active_accounts()

        # Proxy havuzu
        proxies = self.get_proxies()
        pool = [p for p in proxies if p.get("is_working")] if only_working else list(proxies)
        if only_working and not pool:
            # Çalışan proxy yoksa tüm proxy havuzuna düş
            pool = list(proxies)

        result = {"accounts": len(accounts), "proxies": len(pool), "assigned": 0}
        if not accounts or not pool:
            return result

        conn = self._connect()
        try:
            for i, acc in enumerate(accounts):
                proxy = pool[i % len(pool)]
                conn.execute(
                    "UPDATE accounts SET assigned_proxy_id = ? WHERE id = ?",
                    (proxy["id"], acc["id"]),
                )
                result["assigned"] += 1
            conn.commit()
        finally:
            conn.close()
        return result

    # ================================================================== #
    #  MEMBERS
    # ================================================================== #
    def add_member(self, member: Dict[str, Any]) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """INSERT OR IGNORE INTO members
               (user_id, access_hash, username, first_name, last_name, phone,
                group_source, scraped_date, is_added, added_by_account, last_seen, lang_code, is_bot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                member.get("user_id"),
                str(member.get("access_hash", "")),
                member.get("username", ""),
                member.get("first_name", ""),
                member.get("last_name", ""),
                member.get("phone", ""),
                member.get("group_source", ""),
                member.get("scraped_date", _now()),
                int(member.get("is_added", 0)),
                member.get("added_by_account", ""),
                member.get("last_seen", ""),
                member.get("lang_code", ""),
                int(member.get("is_bot", 0)),
            ),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    def add_members_bulk(self, members: List[Dict[str, Any]]) -> int:
        count = 0
        conn = self._connect()
        cur = conn.cursor()
        for member in members:
            cur.execute(
                """INSERT OR IGNORE INTO members
                   (user_id, access_hash, username, first_name, last_name, phone,
                    group_source, scraped_date, is_added, added_by_account, last_seen, lang_code, is_bot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    member.get("user_id"),
                    str(member.get("access_hash", "")),
                    member.get("username", ""),
                    member.get("first_name", ""),
                    member.get("last_name", ""),
                    member.get("phone", ""),
                    member.get("group_source", ""),
                    member.get("scraped_date", _now()),
                    int(member.get("is_added", 0)),
                    member.get("added_by_account", ""),
                    member.get("last_seen", ""),
                    member.get("lang_code", ""),
                    int(member.get("is_bot", 0)),
                ),
            )
            count += cur.rowcount
        conn.commit()
        conn.close()
        return count

    def get_members(self, group_source: Optional[str] = None,
                    only_not_added: bool = False) -> List[Dict[str, Any]]:
        conn = self._connect()
        q = "SELECT * FROM members WHERE 1=1"
        params: List[Any] = []
        if group_source:
            q += " AND group_source = ?"
            params.append(group_source)
        if only_not_added:
            q += " AND is_added = 0"
        q += " ORDER BY id DESC"
        rows = conn.execute(q, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_member_groups(self) -> List[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT group_source FROM members WHERE group_source != '' ORDER BY group_source"
        ).fetchall()
        conn.close()
        return [r["group_source"] for r in rows]

    def mark_member_added(self, member_id: int, account: str):
        conn = self._connect()
        conn.execute(
            "UPDATE members SET is_added = 1, added_by_account = ? WHERE id = ?",
            (account, member_id),
        )
        conn.commit()
        conn.close()

    def delete_members_by_group(self, group_source: str):
        conn = self._connect()
        conn.execute("DELETE FROM members WHERE group_source = ?", (group_source,))
        conn.commit()
        conn.close()

    # ================================================================== #
    #  GROUPS
    # ================================================================== #
    def save_group(self, group_id: int, group_name: str, group_link: str,
                   member_count: int = 0) -> int:
        conn = self._connect()
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT id FROM groups WHERE group_link = ?", (group_link,)
        ).fetchone()
        if existing:
            cur.execute(
                "UPDATE groups SET group_id=?, group_name=?, member_count=?, last_scraped=? WHERE id=?",
                (group_id, group_name, member_count, _now(), existing["id"]),
            )
            rid = existing["id"]
        else:
            cur.execute(
                "INSERT INTO groups(group_id, group_name, group_link, member_count, last_scraped) VALUES (?,?,?,?,?)",
                (group_id, group_name, group_link, member_count, _now()),
            )
            rid = cur.lastrowid
        conn.commit()
        conn.close()
        return rid

    def get_groups(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM groups ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ================================================================== #
    #  PROXIES
    # ================================================================== #
    def add_proxy(self, proxy_type: str, host: str, port: int,
                  username: str = "", password: str = "") -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO proxies(proxy_type, host, port, username, password, is_active) VALUES (?,?,?,?,?,1)",
            (proxy_type, host, port, username, password),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    def get_proxies(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM proxies ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_proxy(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_proxy(self, proxy_id: int, **fields):
        if not fields:
            return
        keys = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [proxy_id]
        conn = self._connect()
        conn.execute(f"UPDATE proxies SET {keys} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    def delete_proxy(self, proxy_id: int):
        conn = self._connect()
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        conn.commit()
        conn.close()

    def proxy_exists(self, proxy_type: str, host: str, port: int) -> bool:
        """(tip, host, port) üçlüsüne göre proxy zaten kayıtlı mı?"""
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM proxies WHERE proxy_type = ? AND host = ? AND port = ? LIMIT 1",
            (proxy_type, host, int(port)),
        ).fetchone()
        conn.close()
        return row is not None

    def add_proxy_unique(self, proxy_type: str, host: str, port: int,
                         username: str = "", password: str = "") -> Optional[int]:
        """Proxy'yi yalnızca (tip, host, port) daha önce yoksa ekler.
        Eklendiyse yeni id, zaten varsa None döndürür."""
        if self.proxy_exists(proxy_type, host, port):
            return None
        return self.add_proxy(proxy_type, host, port, username, password)

    # ================================================================== #
    #  API HAVUZU  (Cgraph ApiSettings.api ile uyumlu)
    # ================================================================== #
    def add_api_credential(self, api_id: str, api_hash: str, extra: str = "") -> Optional[int]:
        """API ID/Hash çiftini havuza ekler (aynı çift varsa eklemez, None döner)."""
        api_id = str(api_id or "").strip()
        api_hash = str(api_hash or "").strip()
        if not api_id or not api_hash:
            return None
        conn = self._connect()
        exists = conn.execute(
            "SELECT 1 FROM api_pool WHERE api_id = ? AND api_hash = ? LIMIT 1",
            (api_id, api_hash),
        ).fetchone()
        if exists:
            conn.close()
            return None
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO api_pool(api_id, api_hash, extra, added_date) VALUES (?,?,?,?)",
            (api_id, api_hash, extra or "", _now()),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid

    def get_api_pool(self) -> List[Dict[str, Any]]:
        """Havuzdaki tüm API ID/Hash çiftlerini döndürür."""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM api_pool ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_api_credential(self, cred_id: int):
        conn = self._connect()
        conn.execute("DELETE FROM api_pool WHERE id = ?", (cred_id,))
        conn.commit()
        conn.close()

    def clear_api_pool(self):
        conn = self._connect()
        conn.execute("DELETE FROM api_pool")
        conn.commit()
        conn.close()

    # ================================================================== #
    #  SETTINGS
    # ================================================================== #
    def get_setting(self, key: str, default: str = "") -> str:
        conn = self._connect()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(value))
        )
        conn.commit()
        conn.close()

    def get_all_settings(self) -> Dict[str, str]:
        conn = self._connect()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows}

    # ================================================================== #
    #  CSV IMPORT / EXPORT (Cgraph uyumlu)
    #  Kolonlar: username,user_id,access_hash,first_name,last_name,phone
    # ================================================================== #
    CSV_FIELDS = ["username", "user_id", "access_hash", "first_name", "last_name", "phone"]

    def export_members_csv(self, filepath: str, members: List[Dict[str, Any]]) -> int:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.CSV_FIELDS)
            for m in members:
                writer.writerow([
                    m.get("username", "") or "",
                    m.get("user_id", "") or "",
                    m.get("access_hash", "") or "",
                    m.get("first_name", "") or "",
                    m.get("last_name", "") or "",
                    m.get("phone", "") or "",
                ])
        return len(members)

    def import_members_csv(self, filepath: str, group_source: str = "") -> List[Dict[str, Any]]:
        """Cgraph CSV formatını okur. Başlık olsun olmasın çalışır."""
        members: List[Dict[str, Any]] = []
        if not group_source:
            group_source = os.path.splitext(os.path.basename(filepath))[0]
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            sample = f.read(2048)
            f.seek(0)
            has_header = "user_id" in sample.lower() or "username" in sample.lower()
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return members
        start = 1 if has_header else 0
        for row in rows[start:]:
            if not row or all(not str(c).strip() for c in row):
                continue
            # Esnek kolon eşleme
            d = {k: "" for k in self.CSV_FIELDS}
            for i, key in enumerate(self.CSV_FIELDS):
                if i < len(row):
                    d[key] = str(row[i]).strip()
            # user_id yoksa atla
            uid = d.get("user_id", "")
            try:
                uid_int = int(float(uid)) if uid else None
            except (ValueError, TypeError):
                uid_int = None
            if uid_int is None and not d.get("username"):
                continue
            members.append({
                "user_id": uid_int,
                "access_hash": d.get("access_hash", ""),
                "username": d.get("username", ""),
                "first_name": d.get("first_name", ""),
                "last_name": d.get("last_name", ""),
                "phone": d.get("phone", ""),
                "group_source": group_source,
                "scraped_date": _now(),
            })
        return members

    def backup_db(self, dest_path: str) -> str:
        import shutil
        shutil.copy2(self.db_path, dest_path)
        return dest_path
