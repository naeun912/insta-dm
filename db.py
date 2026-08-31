import sqlite3
from typing import List, Dict, Optional
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
                is_group INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def get_active_messages_for_thread(thread_id: str) -> Dict[str, dict]:
    """특정 1대1 스레드에 대해 DB에 삭제되지 않고 활성 상태인 메시지 맵 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE thread_id = ? AND is_deleted = 0 AND is_group = 0", (thread_id,))
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def save_new_messages(messages: List[dict]):
    """새로 수신된 1대1 DM 메시지들을 DB에 저장"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            # 단체방 메시지는 아예 무시 (is_group == 1)
            if msg.get("is_group", 0) == 1:
                continue
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
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
    """1대1 메시지를 삭제 상태(is_deleted=1)로 변경"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ? AND is_group = 0", (message_id,))
        row = cursor.fetchone()
        if row:
            msg_dict = dict(row)
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            return msg_dict
        return None

def get_unreported_deleted_messages() -> List[dict]:
    """한 시간 동안 삭제되었지만 아직 텔레그램 요약 리스트로 발송되지 않은 1대1 DM 목록 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_deleted = 1 AND reported = 0 AND is_group = 0
            ORDER BY timestamp ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def mark_deleted_as_reported(message_ids: List[str]):
    """텔레그램 리스트 발송 완료 상태로 변경 (reported=1)"""
    if not message_ids:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(message_ids))
        cursor.execute(f"UPDATE messages SET reported = 1 WHERE message_id IN ({placeholders})", message_ids)
        conn.commit()
