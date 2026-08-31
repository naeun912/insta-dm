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
                is_new_since_start INTEGER DEFAULT 0,
                is_deleted INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # 기존 DB 테이블에 신규 컬럼이 없을 경우 자동 추가 마이그레이션
        for col_name, col_type in [
            ("is_group", "INTEGER DEFAULT 0"),
            ("is_new_since_start", "INTEGER DEFAULT 0"),
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("reported", "INTEGER DEFAULT 0")
        ]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass  # 이미 컬럼이 존재하는 경우 무시

def get_monitored_messages_for_thread(thread_id: str) -> Dict[str, dict]:
    """프로그램 구동 이후 수신된 신규 1대1 메시지 중 활성 상태인 메시지 맵 반환"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE thread_id = ? AND is_new_since_start = 1 AND is_deleted = 0 AND is_group = 0
        """, (thread_id,))
        rows = cursor.fetchall()
        return {row["message_id"]: dict(row) for row in rows}

def save_baseline_messages(messages: List[dict]):
    """시작 시점 기존 메시지들은 baseline(is_new_since_start=0)으로 기입하여 삭제 알림에서 완전 제외"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            if msg.get("is_group", 0) == 1:
                continue
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, thread_id, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_new_since_start, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
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

def save_new_incoming_messages(messages: List[dict]):
    """구동 이후 '새로 도착한' 1대1 DM 메시지 저장 (is_new_since_start=1)"""
    if not messages:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for msg in messages:
            if msg.get("is_group", 0) == 1:
                continue
            cursor.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, thread_id, sender_id, sender_username, sender_fullname, text, timestamp, is_group, is_new_since_start, is_deleted, reported)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, 0, 0)
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
    """구동 이후 도착했던 메시지가 삭제된 경우만 is_deleted=1 로 변경"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id = ? AND is_new_since_start = 1 AND is_group = 0", (message_id,))
        row = cursor.fetchone()
        if row:
            msg_dict = dict(row)
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE message_id = ?", (message_id,))
            conn.commit()
            return msg_dict
        return None

def get_unreported_deleted_messages() -> List[dict]:
    """구동 이후 새로 왔다가 삭제된 1대1 DM 중 미발송 내역 조회"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM messages 
            WHERE is_new_since_start = 1 AND is_deleted = 1 AND reported = 0 AND is_group = 0
            ORDER BY timestamp ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def mark_deleted_as_reported(message_ids: List[str]):
    if not message_ids:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join(["?"] * len(message_ids))
        cursor.execute(f"UPDATE messages SET reported = 1 WHERE message_id IN ({placeholders})", message_ids)
        conn.commit()
