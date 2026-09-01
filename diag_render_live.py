import os
import sys
import traceback
from config import INSTAGRAM_SESSION_ID, INSTAGRAM_SESSION_ID_2
import instagrapi.extractors

original_extract_media_v1_xma = instagrapi.extractors.extract_media_v1_xma
def safe_extract_media_v1_xma(data):
    try:
        return original_extract_media_v1_xma(data)
    except Exception:
        return None
instagrapi.extractors.extract_media_v1_xma = safe_extract_media_v1_xma

from instagrapi import Client

print("🔍 [실시간 2개 계정 쿠키 최종 연결 진단]")

# 1번 계정 진단
try:
    cl1 = Client()
    cl1.request_timeout = 15
    cl1.login_by_sessionid(INSTAGRAM_SESSION_ID)
    username1 = cl1.username if hasattr(cl1, 'username') and cl1.username else cl1.account_info().username
    print(f"✅ [1번 계정 정상!] @{username1} (PK: {cl1.user_id})")
except Exception as e:
    print(f"❌ [1번 계정 쿠키 에러]: {e}")

# 2번 계정 진단
try:
    cl2 = Client()
    cl2.request_timeout = 15
    cl2.login_by_sessionid(INSTAGRAM_SESSION_ID_2)
    username2 = cl2.username if hasattr(cl2, 'username') and cl2.username else cl2.account_info().username
    print(f"✅ [2번 계정 정상!] @{username2} (PK: {cl2.user_id})")
except Exception as e:
    print(f"❌ [2번 계정 쿠키 에러]: {e}")
