import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta

print("🧪 [로컬 자가 검증 테스트 시작]")

try:
    import config
    print("✅ config.py 모듈 로드 성공")
except Exception as e:
    print(f"❌ config.py 로드 실패: {e}")
    sys.exit(1)

try:
    import db
    db.init_db()
    print("✅ db.init_db() 스키마 생성 및 마이그레이션 성공")
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]
    required_cols = ["message_id", "thread_id", "sender_id", "sender_username", "sender_fullname", "text", "timestamp", "is_group", "is_deleted", "reported"]
    
    for col in required_cols:
        assert col in columns, f"컬럼 누락: {col}"
    print(f"✅ DB 테이블 컬럼 검증 완벽 (필수 컬럼 존재)")
    
    # DB 메시지 저장 테스트
    test_msg = {
        "message_id": "test_msg_100",
        "thread_id": "thread_100",
        "sender_id": "user_100",
        "sender_username": "testuser",
        "sender_fullname": "테스트유저",
        "text": "실시간 테스트 메시지",
        "timestamp": "2026-08-31 14:30:00",
        "is_group": 0
    }
    db.save_new_realtime_messages([test_msg])
    print("✅ save_new_realtime_messages() 정상 작동 확인")
    
    monitored = db.get_monitored_messages_for_thread("thread_100")
    assert "test_msg_100" in monitored, "오류: 메시지가 DB 감시 대상에 포함되지 않음"
    print("✅ 활성 메시지 스레드 조회 로직 정상 작동 확인")
    
    # 삭제 처리 및 조회 테스트
    deleted_info = db.mark_message_deleted("test_msg_100")
    assert deleted_info is not None and deleted_info["message_id"] == "test_msg_100", "오류: 삭제 처리 실패"
    print("✅ 메시지 삭제 마킹 및 정보 반환 정상 작동 확인")

except Exception as e:
    print(f"❌ DB 로직 검증 실패: {e}")
    sys.exit(1)

try:
    import telegram_notifier
    print("✅ telegram_notifier.py 모듈 로드 성공")
except Exception as e:
    print(f"❌ telegram_notifier.py 로드 실패: {e}")
    sys.exit(1)

try:
    import main
    assert hasattr(main, 'login_instagram')
    assert hasattr(main, 'extract_one_on_one_threads')
    assert hasattr(main, 'monitor_loop')
    print("✅ main.py 핵심 구조 및 함수 검증 완료")
except Exception as e:
    print(f"❌ main.py 검증 실패: {e}")
    sys.exit(1)

print("🎉 [모든 로컬 단위 검증 테스트 100% 통과!]")
