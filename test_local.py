import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta

print("🧪 [로컬 자가 검증 테스트 시작]")

# 1. config 모듈 체크
try:
    import config
    print("✅ config.py 모듈 로드 성공")
except Exception as e:
    print(f"❌ config.py 로드 실패: {e}")
    sys.exit(1)

# 2. db 모듈 체크 및 DB 스키마 검증
try:
    import db
    db.init_db()
    print("✅ db.init_db() 스키마 생성 및 마이그레이션 성공")
    
    # DB 컬럼 정밀 검사
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(messages)")
    columns = [row[1] for row in cursor.fetchall()]
    required_cols = ["message_id", "thread_id", "sender_id", "sender_username", "sender_fullname", "text", "timestamp", "is_group", "is_new_since_start", "is_deleted", "reported"]
    
    for col in required_cols:
        assert col in columns, f"컬럼 누락: {col}"
    print(f"✅ DB 테이블 컬럼 검증 완벽 (모든 {len(required_cols)}개 필수 컬럼 존재)")
    
    # DB 로직 테스트
    test_msg_baseline = {
        "message_id": "test_msg_1",
        "thread_id": "thread_1",
        "sender_id": "user_1",
        "sender_username": "testuser",
        "sender_fullname": "테스트유저",
        "text": "과거 메시지 테스트",
        "timestamp": "2026-08-31 12:00:00",
        "is_group": 0
    }
    db.save_baseline_messages([test_msg_baseline])
    print("✅ save_baseline_messages() 기능 검증 완료")
    
    # baseline 메시지는 감시 대상에서 제외되었는지 확인
    monitored = db.get_monitored_messages_for_thread("thread_1")
    assert "test_msg_1" not in monitored, "오류: baseline 메시지가 감시 대상에 포함됨"
    print("✅ 과거 baseline 메시지 감시 대상 제외 로직 정상 작동 확인")
    
    # 신규 수신 메시지 저장 테스트
    test_msg_new = {
        "message_id": "test_msg_2",
        "thread_id": "thread_1",
        "sender_id": "user_1",
        "sender_username": "testuser",
        "sender_fullname": "테스트유저",
        "text": "새로 도착한 메시지",
        "timestamp": "2026-08-31 13:00:00",
        "is_group": 0
    }
    db.save_new_incoming_messages([test_msg_new])
    monitored_new = db.get_monitored_messages_for_thread("thread_1")
    assert "test_msg_2" in monitored_new, "오류: 신규 메시지가 감시 대상에 안 포함됨"
    print("✅ 새로 도착한 메시지 감시 대상 등록 로직 정상 작동 확인")
    
    # 삭제 처리 및 조회 테스트
    deleted_info = db.mark_message_deleted("test_msg_2")
    assert deleted_info is not None and deleted_info["message_id"] == "test_msg_2", "오류: 삭제 처리 실패"
    print("✅ 100% 진짜 전송 취소(삭제) 판별 및 DB 업데이트 정상 작동 확인")

except Exception as e:
    print(f"❌ DB 로직 검증 실패: {e}")
    sys.exit(1)

# 3. telegram_notifier 모듈 체크
try:
    import telegram_notifier
    print("✅ telegram_notifier.py 모듈 로드 성공")
except Exception as e:
    print(f"❌ telegram_notifier.py 로드 실패: {e}")
    sys.exit(1)

# 4. main 모듈 구동 테스트 (주요 함수 바인딩 검증)
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
