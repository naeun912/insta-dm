import time
import sys
import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from config import (
    INSTAGRAM_USERNAME,
    INSTAGRAM_PASSWORD,
    CHECK_INTERVAL,
    SESSION_PATH
)
from db import (
    init_db,
    get_active_messages_for_thread,
    save_new_messages,
    mark_message_deleted,
    get_unreported_deleted_messages,
    mark_deleted_as_reported
)
from telegram_notifier import send_hourly_deleted_dms_report, send_telegram_message

# 한국 표준시 (KST = UTC+9) 설정
KST = timezone(timedelta(hours=9))

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
    """인스타그램 로그인 (sessionid 최우선 및 안전 방어 로직)"""
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

    # 2. 비밀번호 신규 로그인 시도 (실패 시 알림 도배 방지 5분 휴식)
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
        print("⚠️ 폰 알림 폭주 방지를 위해 추가 로그인 시도를 중단하고 5분간 휴식합니다.")
        time.sleep(300)
        sys.exit(1)

def extract_one_on_one_threads(cl: Client, amount_threads: int = 15) -> dict:
    """
    단체방 제외! 오직 1대1 개인 DM 스레드만 추출.
    반환 구조: { thread_id: { message_id: msg_dict } }
    """
    threads_data = {}
    try:
        threads = cl.direct_threads(amount=amount_threads)
        for thread in threads:
            thread_id = str(thread.id)
            
            # 단체방 제외 검사 (is_group이 True이거나 참여 유저가 2명 이상이면 단체방으로 간주)
            is_group_chat = getattr(thread, 'is_group', False) or len(thread.users) > 1
            if is_group_chat:
                continue # 단체방은 완전히 건너뜀
                
            users_map = {str(u.pk): u for u in thread.users}
            thread_messages = {}
            
            for msg in thread.messages:
                msg_id = str(msg.id)
                user_pk = str(msg.user_id)
                
                # 내가 보낸 메시지는 대상에서 제외
                if user_pk == str(cl.user_id):
                    continue
                
                sender_info = users_map.get(user_pk)
                username = sender_info.username if sender_info else "알 수 없음"
                fullname = sender_info.full_name if sender_info else username
                text_content = msg.text if msg.text else f"[{msg.item_type} 미디어/스티커/이모지]"
                
                # 한국 시간(KST = UTC+9)으로 시각 변환
                if getattr(msg, 'timestamp', None):
                    dt_utc = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=timezone.utc)
                    dt_kst = dt_utc.astimezone(KST)
                    timestamp_str = dt_kst.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    timestamp_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                
                thread_messages[msg_id] = {
                    "message_id": msg_id,
                    "thread_id": thread_id,
                    "sender_id": user_pk,
                    "sender_username": username,
                    "sender_fullname": fullname,
                    "text": text_content,
                    "timestamp": timestamp_str,
                    "is_group": 0
                }
            
            threads_data[thread_id] = thread_messages
    except Exception as e:
        print(f"⚠️ 1대1 스레드 메시지 수신 중 오류 발생: {e}")
        
    return threads_data

def process_hourly_report():
    """1시간 단위로 모인 삭제 DM이 있을 경우 요약 리스트 텔레그램 발송"""
    unreported_deleted = get_unreported_deleted_messages()
    if unreported_deleted:
        kst_now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        print(f"📊 [1시간 요약 발송] 총 {len(unreported_deleted)}개의 1대1 삭제 DM을 텔레그램으로 전송합니다.")
        sent_ok = send_hourly_deleted_dms_report(unreported_deleted, kst_now)
        if sent_ok:
            m_ids = [m["message_id"] for m in unreported_deleted]
            mark_deleted_as_reported(m_ids)
            print("✅ 1시간 요약 리스트 발송 완료!")

def monitor_loop():
    print("=" * 60)
    print("🚀 인스타그램 개인 DM 삭제 감시 시스템 구동 시작!")
    print("📌 모드: 단체방 완전 제외 / 오직 1대1 DM만 감시 / 한국시간(KST) 적용 / 1시간 단위 요약 리스트 발송")
    print("=" * 60)
    
    t = threading.Thread(target=start_health_check_server, daemon=True)
    t.start()
    
    init_db()
    cl = login_instagram()
    
    # 시스템 시작 알림 (한국시간 표기)
    kst_start_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    start_alert_text = (
        "🎉 <b>[인스타그램 개인 DM 삭제 감시 작동 시작!]</b>\n\n"
        f"⏰ <b>시작 시각:</b> {kst_start_str} (한국시간)\n"
        "✅ 단체방 제외 / 오직 1대1 개인 DM만 감시하도록 설정 완료!\n"
        "📊 실시간 알림 대신 <b>1시간마다 삭제된 내역만 요약 리스트</b>로 정리해서 보냅니다.\n"
        "💡 <i>(지난 1시간 동안 삭제된 DM이 없으면 알림을 보내지 않습니다.)</i>"
    )
    send_telegram_message(start_alert_text)
    
    print("\n" + "🎉" * 30)
    print(f"✅ 로그인 완료 ({kst_start_str} KST). 1대1 DM 삭제 감시 모드가 작동 중입니다.")
    print("🎉" * 30 + "\n")
    
    first_run = True
    consecutive_errors = 0
    HOURLY_INTERVAL = 3600  # 1시간 = 3600초
    last_hourly_check = time.time()
    
    while True:
        try:
            # 1. 단체방 제외 1대1 개인 스레드들만 가져오기
            threads_data = extract_one_on_one_threads(cl, amount_threads=15)
            consecutive_errors = 0
            
            for thread_id, current_messages in threads_data.items():
                current_msg_ids = set(current_messages.keys())
                
                # DB에서 해당 스레드의 활성 메시지 목록 조회
                stored_active_map = get_active_messages_for_thread(thread_id)
                stored_msg_ids = set(stored_active_map.keys())
                
                if first_run:
                    # 첫 실행 시에는 가져온 1대1 메시지들을 동기화 저장
                    save_new_messages(list(current_messages.values()))
                else:
                    # 신규 수신 메시지 저장
                    new_msg_ids = current_msg_ids - stored_msg_ids
                    if new_msg_ids:
                        new_msgs = [current_messages[mid] for mid in new_msg_ids]
                        save_new_messages(new_msgs)
                    
                    # 스레드 내에서 실제 삭제/전송 취소된 메시지 감지
                    deleted_msg_ids = stored_msg_ids - current_msg_ids
                    for d_id in deleted_msg_ids:
                        deleted_info = mark_message_deleted(d_id)
                        if deleted_info:
                            print(f"🔍 [1대1 DM 삭제 감지] @{deleted_info['sender_username']}: '{deleted_info['text']}' (1시간 단위 요약 리스트에 기록됨)")

            if first_run:
                print("✅ 1대1 개인 DM 메시지 동기화 완료. 감시를 계속합니다.")
                first_run = False

            # 2. 1시간 주기 검사 및 요약 리스트 발송
            if time.time() - last_hourly_check >= HOURLY_INTERVAL:
                process_hourly_report()
                last_hourly_check = time.time()
                
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n👋 모니터링을 종료합니다.")
            break
        except Exception as e:
            consecutive_errors += 1
            print(f"⚠️ 감시 루프 오류 발생 ({e}). 에러 횟수: {consecutive_errors}")
            sleep_time = min(CHECK_INTERVAL * (2 ** consecutive_errors), 300)
            time.sleep(sleep_time)

if __name__ == "__main__":
    monitor_loop()
