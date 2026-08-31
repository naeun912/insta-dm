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
                thread_title TEXT,
                sender_id TEXT,
                sender_username TEXT,
                sender_fullname TEXT,
                text TEXT,
                timestamp TEXT,
                is_group INTEGER DEFAULT 0,
                is_new_since_start INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        for col_name, col_type in [
            ("thread_title", "TEXT DEFAULT ''"),
            ("is_group", "INTEGER DEFAULT 0"),
            ("is_new_since_start", "INTEGER DEFAULT 0"),
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("reported", "INTEGER DEFAULT 0")
        ]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass

def save_baseline_messages(messages: List[dict]):
    """시동 시점 기존에 있던 메시지들은 과거 메시지(is_new_since_start=0)로 등록하여 새 메시지 및 삭제 알림에서 완전 제외"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, thread_id, thread_title, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_new_since_start, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """, (
                msg["message_id"],
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

def save_realtime_new_messages(messages: List[dict]):
    """시동 시각 이후(timestamp >= SCRIPT_START_TIME) 새로 도착한 DM만 감시 대상(is_new_since_start=1)으로 저장"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            cursor.execute("""
                INSERT OR REPLACE INTO messages 
                (message_id, thread_id, thread_title, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_new_since_start, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0)
            """, (
                msg["message_id"],
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

def get_realtime_monitored_messages(thread_id: str) -> Dict[str, dict]:
    """시동 이후 수신된 감시 대상 신규 메시지 목록만 조회 (is_new_since_start = 1, is_deleted = 0)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE thread_id = ? AND is_new_since_start = 1 AND is_deleted = 0
        """, (thread_id,))
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def mark_message_deleted(message_id: str) -> Optional[dict]:
    """시동 이후 새로 도착했던 DM이 삭제된 경우만 is_deleted=1 로 변경 및 정보 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ? AND is_new_since_start = 1 AND is_deleted = 0", (message_id,))
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
            WHERE is_deleted = 1
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
            WHERE is_deleted = 1 AND LOWER(sender_username) LIKE ?
            ORDER BY timestamp DESC
        """, (f"%{clean_username}%",))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
