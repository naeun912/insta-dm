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
    from instagrapi.exceptions import TwoFactorRequired, TwoFactorCodeRequired
except ImportError:
    print("❌ instagrapi 라이브러리가 설치되지 않았습니다. 'pip3 install -r requirements.txt'를 실행해주세요.")
    sys.exit(1)

def login_instagram() -> Client:
    """인스타그램 로그인 및 세션 (2FA 대응) 관리"""
    cl = Client()
    cl.request_timeout = 10
    
    # 1. 환경변수 INSTAGRAM_SESSION_SETTINGS가 주어졌을 때 (Render용)
    session_env = os.getenv("INSTAGRAM_SESSION_SETTINGS", "").strip()
    if session_env:
        try:
            print("🔄 환경 변수에 등록된 2FA 세션 설정으로 로그인합니다...")
            cl.set_settings(json.loads(session_env))
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("✅ 2FA 세션 환경 변수로 로그인 성공!")
            return cl
        except Exception as e:
            print(f"⚠️ 환경 변수 세션 로그인 실패 ({e}). 기본 로그인으로 재시도합니다.")

    # 2. 로컬 session.json 파일이 존재하는 경우
    if SESSION_PATH.exists():
        try:
            print(f"🔄 로컬 세션 파일({SESSION_PATH.name})에서 로그인을 시도합니다...")
            cl.load_settings(SESSION_PATH)
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("✅ 로컬 세션 로그인 성공!")
            return cl
        except Exception as e:
            print(f"⚠️ 로컬 세션 로그인 실패 ({e}). 신규 로그인을 진행합니다...")

    # 3. 신규 로그인 시도 (2FA 처리 지원)
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("❌ INSTAGRAM_USERNAME과 INSTAGRAM_PASSWORD 설정이 누락되었습니다.")
        sys.exit(1)
        
    print(f"🔑 인스타그램 계정({INSTAGRAM_USERNAME}) 신규 로그인 시도 중...")
    try:
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
    except (TwoFactorRequired, TwoFactorCodeRequired, Exception) as e:
        err_msg = str(e).lower()
        if "two-factor" in err_msg or "verification_code" in err_msg or "2fa" in err_msg or isinstance(e, (TwoFactorRequired, TwoFactorCodeRequired)):
            print("\n📱 인스타그램 2단계 인증(2FA)이 설정되어 있습니다!")
            try:
                verification_code = input("👉 폰으로 전송된 6자리 2FA 보안 코드를 입력하세요: ").strip()
                cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, verification_code=verification_code)
            except Exception as login_err:
                print(f"❌ 2FA 코드 로그인 실패: {login_err}")
                sys.exit(1)
        else:
            print(f"❌ 로그인 실패: {e}")
            sys.exit(1)

    # 로그인 성공 후 세션 파일 저장
    cl.dump_settings(SESSION_PATH)
    print("✅ 로그인 성공 및 세션 저장 완료!")
    
    # 2FA 계정을 위한 세션 문자열 출력 (Render 환경변수 등록용)
    session_json_str = json.dumps(cl.get_settings())
    print("\n" + "="*60)
    print("💡 Render 서버 2FA 세션 설정 문자열 (Render 환경 변수에 등록 시 2FA 재인증 불필요):")
    print(session_json_str)
    print("="*60 + "\n")
    
    return cl

def extract_thread_messages(cl: Client, amount_threads: int = 15) -> dict:
    current_messages = {}
    try:
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
    except Exception as e:
        print(f"⚠️ 스레드 메시지 수신 중 오류 발생: {e}")
        
    return current_messages

def monitor_loop():
    print("=" * 60)
    print("🚀 인스타그램 삭제 DM 감시 시스템 구동 시작!")
    print("📌 원리: 도착한 메시지를 기록해 두었다가, 상대방이 전송 취소하면 텔레그램으로 알림을 보냅니다.")
    print("=" * 60)
    
    t = threading.Thread(target=start_health_check_server, daemon=True)
    t.start()
    
    init_db()
    cl = login_instagram()
    
    print(f"👀 DM 모니터링을 시작합니다. (감시 주기: {CHECK_INTERVAL}초)")
    print("💡 일반 DM은 텔레그램으로 보내지 않으며, '삭제된 DM'만 텔레그램 알림이 발송됩니다.")
    
    first_run = True
    
    while True:
        try:
            current_messages = extract_thread_messages(cl, amount_threads=15)
            current_msg_ids = set(current_messages.keys())
            
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
            print(f"⚠️ 감시 루프 실행 중 에러 발생: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor_loop()
