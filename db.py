import sqlite3
from typing import List, Dict, Set, Optional
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """데이터베이스 테이블 초기화"""
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
                is_deleted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def get_active_messages_map() -> Dict[str, dict]:
    """현재 DB에 정상(삭제 안 됨) 상태로 기록된 메시지 맵 {message_id: message_dict} 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE is_deleted = 0")
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def save_new_messages(messages: List[dict]):
    """새로 수신된 메시지들을 DB에 저장 (is_deleted=0)"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, thread_id, sender_id, sender_username, sender_fullname, text, timestamp, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
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
    """메시지를 삭제 상태(is_deleted=1)로 변경하고, 삭제된 메시지 정보 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,))
        row = cursor.fetchone()
        if row:
            msg_dict = dict(row)
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            return msg_dict
        return None
