import sqlite3
from typing import List, Dict, Optional
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """데이터베이스 테이블 초기화 및 스키마 자동 마이그레이션"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                my_account TEXT DEFAULT '',
                thread_id TEXT,
                thread_title TEXT,
                sender_id TEXT,
                sender_username TEXT,
                sender_fullname TEXT,
                text TEXT,
                timestamp TEXT,
                is_group INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        for col_name, col_type in [
            ("my_account", "TEXT DEFAULT ''"),
            ("thread_title", "TEXT DEFAULT ''"),
            ("is_group", "INTEGER DEFAULT 0"),
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("reported", "INTEGER DEFAULT 0")
        ]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass

        # 더미 테스트 데이터 자동 청소
        cursor.execute("DELETE FROM messages WHERE message_id LIKE 'test%' OR message_id LIKE 'base%' OR sender_username IN ('olduser', 'friend_user', 'testuser')")
        conn.commit()

def save_baseline_messages(messages: List[dict]):
    """시동 시점 기존 과거 메시지는 reported=1 로 저장하여 알림 대상에서 완벽 제외"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, my_account, thread_id, thread_title, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
            """, (
                msg["message_id"],
                msg.get("my_account", ""),
                msg.get("thread_id", ""),
                msg.get("thread_title", ""),
                msg.get("sender_id", ""),
                msg.get("sender_username", "알 수 없음"),
                msg.get("sender_fullname", "알 수 없음"),
                msg.get("text", "(내용 없음 또는 미디어)"),
                msg.get("timestamp", ""),
                msg.get("is_group", 0)
            ))
        conn.commit()

def save_new_incoming_messages(messages: List[dict]):
    """실행 이후 새로 도착한 DM 저장 (my_account, thread_title, is_group 포함)"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            cursor.execute("""
                INSERT OR REPLACE INTO messages 
                (message_id, my_account, thread_id, thread_title, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """, (
                msg["message_id"],
                msg.get("my_account", ""),
                msg.get("thread_id", ""),
                msg.get("thread_title", ""),
                msg.get("sender_id", ""),
                msg.get("sender_username", "알 수 없음"),
                msg.get("sender_fullname", "알 수 없음"),
                msg.get("text", "(내용 없음 또는 미디어)"),
                msg.get("timestamp", ""),
                msg.get("is_group", 0)
            ))
        conn.commit()

def get_all_active_unreported_messages() -> Dict[str, dict]:
    """DB에 저장되어 있는 모든 감시 대상 활성 메시지 맵 반환 (is_deleted=0 AND reported=0)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE is_deleted = 0 AND reported = 0")
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def mark_message_deleted(message_id: str) -> Optional[dict]:
    """신규 메시지가 삭제된 경우 is_deleted=1, reported=1 로 변경 및 정보 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ? AND is_deleted = 0 AND reported = 0", (message_id,))
        row = cursor.fetchone()
        if row:
            msg_dict = dict(row)
            cursor.execute("UPDATE messages SET is_deleted = 1, reported = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            return msg_dict
        return None

def get_todays_deleted_messages() -> List[dict]:
    """오늘 삭제된 메시지 조회 명령용"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_deleted = 1
            ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_deleted_messages_by_username(username: str) -> List[dict]:
    """특정 사용자 아이디 삭제 내역 검색용"""
    clean_username = username.lstrip("@").strip().lower()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_deleted = 1 AND LOWER(sender_username) LIKE ?
            ORDER BY timestamp DESC
        """, (f"%{clean_username}%",))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
