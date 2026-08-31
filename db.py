import sqlite3
from typing import List, Dict, Optional
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """데이터베이스 테이블 초기화 및 스키마 마이그레이션"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT,
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
            ("is_group", "INTEGER DEFAULT 0"),
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("reported", "INTEGER DEFAULT 0")
        ]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass

def get_active_messages_for_thread(thread_id: str) -> Dict[str, dict]:
    """해당 1대1 스레드의 DB 저장 메시지 맵 반환 (is_deleted = 0)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE thread_id = ? AND is_deleted = 0 AND is_group = 0
        """, (thread_id,))
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def save_thread_messages(messages: List[dict]):
    """1대1 DM 메시지들을 DB에 저장 또는 갱신"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            if msg.get("is_group", 0) == 1:
                continue
            cursor.execute("""
                INSERT OR REPLACE INTO messages 
                (message_id, thread_id, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """, (
                msg["message_id"],
                msg.get("thread_id", ""),
                msg.get("sender_id", ""),
                msg.get("sender_username", "알 수 없음"),
                msg.get("sender_fullname", "알 수 없음"),
                msg.get("text", "(내용 없음 또는 미디어)"),
                msg.get("timestamp", "")
            ))
        conn.commit()

def mark_message_deleted(message_id: str) -> Optional[dict]:
    """메시지가 1대1 대화방에서 사라진 경우 is_deleted=1 로 변경 및 정보 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ? AND is_group = 0 AND is_deleted = 0", (message_id,))
        row = cursor.fetchone()
        if row:
            msg_dict = dict(row)
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            return msg_dict
        return None

def get_todays_deleted_messages() -> List[dict]:
    """오늘 감지 및 삭제된 모든 메시지 조회"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_deleted = 1 AND is_group = 0
            ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_deleted_messages_by_username(username: str) -> List[dict]:
    """특정 인스타그램 아이디(username)로 삭제된 내역 검색"""
    clean_username = username.lstrip("@").strip().lower()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_deleted = 1 AND is_group = 0 AND LOWER(sender_username) LIKE ?
            ORDER BY timestamp DESC
        """, (f"%{clean_username}%",))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
