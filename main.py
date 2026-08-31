import time
import sys
import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from config import (
    INSTAGRAM_USERNAME,
    INSTAGRAM_PASSWORD,
    CHECK_INTERVAL,
    SESSION_PATH
)
from db import init_db, get_active_messages_map, save_new_messages, mark_message_deleted
from telegram_notifier import alert_deleted_dm

# Render 무료 웹 서비스 포트 바인딩용 헬스체크 서버
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Instagram DM Monitor is Running!")
    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# instagrapi Import
try:
    from instagrapi import Client
    from instagrapi.exceptions import TwoFactorRequired, LoginRequired
except ImportError as e:
    print(f"❌ instagrapi 라이브러리가 설치되지 않았습니다 ({e}).")
    sys.exit(1)

def login_instagram() -> Client:
    """인스타그램 로그인 (안전 방어 로직 적용)"""
    cl = Client()
    cl.request_timeout = 15
    
    # 0. INSTAGRAM_SESSION_ID 최우선 사용 (2FA 및 로그인 알림 100% 차단)
    session_id = os.getenv("INSTAGRAM_SESSION_ID", "").strip()
    if session_id:
        try:
            print("🔑 sessionid 쿠키 값으로 인스타그램에 로그인합니다...")
            cl.login_by_sessionid(session_id)
            print("🎉 sessionid 쿠키로 로그인 100% 성공! (로그인 알림 및 2FA 요청 없음)")
            return cl
        except Exception as e:
            print(f"❌ sessionid 쿠키 로그인 실패: {e}")
            print("⚠️ 연속 로그인 알림 방지를 위해 5분간 대기합니다.")
            time.sleep(300)
            sys.exit(1)

    # 1. 환경변수 INSTAGRAM_SESSION_SETTINGS
    session_env = os.getenv("INSTAGRAM_SESSION_SETTINGS", "").strip()
    if session_env:
        try:
            print("🔄 세션 환경 변수로 로그인을 시도합니다...")
            cl.set_settings(json.loads(session_env))
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("✅ 2FA 세션 환경 변수로 로그인 성공!")
            return cl
        except Exception as e:
            print(f"⚠️ 세션 환경 변수 로그인 실패: {e}")

    # 2. 비밀번호 신규 로그인 시도 (알림 도배 방지: 실패 시 즉시 종료/대기)
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("❌ INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD / INSTAGRAM_SESSION_ID 중 설정이 누락되었습니다.")
        sys.exit(1)
        
    print(f"🔑 인스타그램 계정({INSTAGRAM_USERNAME}) 신규 로그인 시도 중...")
    try:
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        cl.dump_settings(SESSION_PATH)
        print("✅ 비밀번호 로그인 성공!")
        return cl
    except Exception as e:
        print(f"\n❌ 로그인 시도 실패: {e}")
        print("⚠️ 폰으로 로그인 승인 알림이 폭주하는 것을 방지하기 위해 추가 로그인 시도를 즉시 중단하고 5분간 휴식합니다.")
        time.sleep(300)
        sys.exit(1)

def extract_thread_messages(cl: Client, amount_threads: int = 15) -> dict:
    current_messages = {}
    threads = cl.direct_threads(amount=amount_threads)
    for thread in threads:
        thread_id = str(thread.id)
        users_map = {str(u.pk): u for u in thread.users}
        
        for msg in thread.messages:
            msg_id = str(msg.id)
            user_pk = str(msg.user_id)
            
            if user_pk == str(cl.user_id):
                continue
            
            sender_info = users_map.get(user_pk)
            username = sender_info.username if sender_info else "알 수 없음"
            fullname = sender_info.full_name if sender_info else username
            text_content = msg.text if msg.text else f"[{msg.item_type} 미디어/스티커/이모지]"
            timestamp_str = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if getattr(msg, 'timestamp', None) else ""
            
            current_messages[msg_id] = {
                "message_id": msg_id,
                "thread_id": thread_id,
                "sender_id": user_pk,
                "sender_username": username,
                "sender_fullname": fullname,
                "text": text_content,
                "timestamp": timestamp_str
            }
        
    return current_messages

def monitor_loop():
    print("=" * 60)
    print("🚀 인스타그램 삭제 DM 감시 시스템 구동 시작!")
    print("📌 원리: 도착한 메시지를 기록해 두었다가, 상대방이 전송 취소하면 텔레그램으로 알림을 보냅니다.")
    print("=" * 60)
    
    # 헬스체크 웹서버 구동
    t = threading.Thread(target=start_health_check_server, daemon=True)
    t.start()
    
    init_db()
    cl = login_instagram()
    
    print(f"👀 DM 모니터링을 정상적으로 시작합니다. (감시 주기: {CHECK_INTERVAL}초)")
    print("💡 일반 DM은 텔레그램으로 보내지 않으며, '삭제된 DM'만 텔레그램 알림이 발송됩니다.")
    
    first_run = True
    consecutive_errors = 0
    
    while True:
        try:
            current_messages = extract_thread_messages(cl, amount_threads=15)
            current_msg_ids = set(current_messages.keys())
            consecutive_errors = 0  # 정상 수행 시 에러 카운트 리셋
            
            stored_active_map = get_active_messages_map()
            stored_msg_ids = set(stored_active_map.keys())
            
            if first_run:
                save_new_messages(list(current_messages.values()))
                print(f"✅ 초기 메시지 {len(current_messages)}개 동기화 완료.")
                first_run = False
            else:
                new_msg_ids = current_msg_ids - stored_msg_ids
                if new_msg_ids:
                    new_msgs = [current_messages[mid] for mid in new_msg_ids]
                    save_new_messages(new_msgs)
                    for nm in new_msgs:
                        print(f"📩 [신규 메시지 도착 기록] @{nm['sender_username']}: {nm['text'][:20]}...")

                deleted_msg_ids = stored_msg_ids - current_msg_ids
                for d_id in deleted_msg_ids:
                    deleted_msg_info = mark_message_deleted(d_id)
                    if deleted_msg_info:
                        print("!" * 60)
                        print(f"🚨 [전송 취소 DM 감지!] 보낸사람: @{deleted_msg_info['sender_username']}")
                        print(f"내용: {deleted_msg_info['text']}")
                        print("!" * 60)
                        
                        alert_deleted_dm(
                            sender_username=deleted_msg_info["sender_username"],
                            sender_fullname=deleted_msg_info["sender_fullname"],
                            text=deleted_msg_info["text"],
                            timestamp=deleted_msg_info["timestamp"]
                        )
                        
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n👋 모니터링을 종료합니다.")
            break
        except Exception as e:
            consecutive_errors += 1
            print(f"⚠️ 메시지 확인 중 오류 발생 ({e}). 에러 횟수: {consecutive_errors}")
            # 연속 에러 발생 시 알림 폭주 방지를 위한 대기 시간 증가
            sleep_time = min(CHECK_INTERVAL * (2 ** consecutive_errors), 300)
            print(f"⏳ 인스타 알림 보호를 위해 {sleep_time}초 동안 대기 후 다시 확인합니다.")
            time.sleep(sleep_time)

if __name__ == "__main__":
    monitor_loop()
