import os
import sys
import traceback
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

session_id_1 = "2049927310%3ApL3eGs6r2zeslI%3A16%3AAYgEMF0FUNQj_-LpaCcCw8a7IVoxbZOp6vNZh9B0oHU"
session_id_2 = "44919071763%3AusEEjk6rcFCqnM%3A13%3AAYg298045TUVSTLz_uV6rY0dloOCAAHMdkFbgIMRww"

print("🔍 [다중 계정 2개 로그인 진단 시작]")

# 계정 1 진단
try:
    cl1 = Client()
    cl1.request_timeout = 15
    cl1.login_by_sessionid(session_id_1)
    username1 = cl1.username if hasattr(cl1, 'username') and cl1.username else cl1.account_info().username
    print(f"✅ [계정 1 로그인 성공] 계정명: @{username1} (PK: {cl1.user_id})")
except Exception as e:
    print(f"❌ [계정 1 로그인 실패]: {e}")

# 계정 2 진단
try:
    cl2 = Client()
    cl2.request_timeout = 15
    cl2.login_by_sessionid(session_id_2)
    username2 = cl2.username if hasattr(cl2, 'username') and cl2.username else cl2.account_info().username
    print(f"✅ [계정 2 로그인 성공] 계정명: @{username2} (PK: {cl2.user_id})")
except Exception as e:
    print(f"❌ [계정 2 로그인 실패]: {e}")
