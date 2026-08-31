import os
import sys
import json
import traceback
from datetime import datetime, timezone, timedelta
from config import INSTAGRAM_SESSION_ID

# ⭐ [핵심 패치]: instagrapi 최신 인스타그램 instagram:// 미디어 URL pydantic 에러 무력화
import instagrapi.extractors
original_extract_media_v1_xma = instagrapi.extractors.extract_media_v1_xma

def safe_extract_media_v1_xma(data):
    try:
        return original_extract_media_v1_xma(data)
    except Exception:
        return None

instagrapi.extractors.extract_media_v1_xma = safe_extract_media_v1_xma

print("🔍 [인스타그램 실시간 안전 진단 시작]")

session_id = INSTAGRAM_SESSION_ID.strip()

try:
    from instagrapi import Client
    cl = Client()
    cl.request_timeout = 15
    
    print(f"🔑 sessionid({session_id[:10]}...)로 인스타 로그인 중...")
    cl.login_by_sessionid(session_id)
    print(f"✅ 로그인 성공! 내 계정 PK: {cl.user_id}\n")
    
    print("📩 [스레드 메시지 수집 진단]")
    threads = cl.direct_threads(amount=10)
    print(f"🎉 성공! 총 {len(threads)}개의 스레드를 에러 없이 무사히 가져왔습니다!\n")
    
    for idx, thread in enumerate(threads, 1):
        users_str = ", ".join([f"@{u.username}" for u in thread.users])
        print(f"--- 스레드 {idx} (ID: {thread.id}) ---")
        print(f"  • 대화 상대: {users_str}")
        print(f"  • 메시지 개수: {len(thread.messages)}개")
        for msg in thread.messages[:3]:
            is_me = str(msg.user_id) == str(cl.user_id)
            print(f"    - 메시지 ID: {msg.id} | 보낸이: {'나' if is_me else msg.user_id} | 내용: '{msg.text}' | 시간: {msg.timestamp}")
        print()

except Exception as e:
    print(f"❌ 진단 중 오류 발생:\n{traceback.format_exc()}")
