import os
import sys
import traceback
from config import INSTAGRAM_SESSION_ID
import instagrapi.extractors

# pydantic URL validation 몽키패치
original_extract_media_v1_xma = instagrapi.extractors.extract_media_v1_xma
def safe_extract_media_v1_xma(data):
    try:
        return original_extract_media_v1_xma(data)
    except Exception:
        return None
instagrapi.extractors.extract_media_v1_xma = safe_extract_media_v1_xma

from instagrapi import Client

print("🔍 [cl.direct_thread() API 진단 시작]")

try:
    cl = Client()
    cl.request_timeout = 15
    cl.login_by_sessionid(INSTAGRAM_SESSION_ID)
    print(f"✅ 로그인 성공! 계정 PK: {cl.user_id}")
    
    threads = cl.direct_threads(amount=1)
    if threads:
        t = threads[0]
        print(f"📌 테스트 스레드 ID: {t.id} (타입: {type(t.id)})")
        
        print("🔄 cl.direct_thread(t.id) 호출 시도...")
        detail = cl.direct_thread(t.id)
        print(f"✅ cl.direct_thread(t.id) 성공! 메시지 개수: {len(detail.messages)}개")
    else:
        print("⚠️ 스레드가 존재하지 않습니다.")

except Exception as e:
    print(f"❌ direct_thread 진단 중 오류 발생:\n{traceback.format_exc()}")
