import time
import sys
import os
import json
import atexit
import signal
import traceback
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
    get_monitored_messages_for_thread,
    save_baseline_messages,
    save_new_incoming_messages,
    mark_message_deleted,
    get_unreported_deleted_messages,
    mark_deleted_as_reported
)
from telegram_notifier import alert_realtime_deleted_dm, send_telegram_message, process_telegram_bot_commands

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

def start_telegram_command_listener():
    """텔레그램 대화창 명령어 리스너 (/list, @아이디 검색 등)"""
    last_offset = 0
    while True:
        try:
            last_offset = process_telegram_bot_commands(last_offset)
            time.sleep(1)
        except Exception:
            time.sleep(2)

def log_system_exit(reason="알 수 없음"):
    """프로그램 종료 직전 상세 로그 및 텔레그램 알림"""
    kst_now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    msg = f"🛑 [시스템 종료 알림] 시각: {kst_now} (KST) / 원인: {reason}"
    print(f"\n{'='*60}\n{msg}\n{'='*60}\n", flush=True)
    try:
        send_telegram_message(f"⚠️ <b>[감시 시스템 종료]</b>\n⏰ <b>시간:</b> {kst_now} (KST)\n📌 <b>원인:</b> {reason}")
    except Exception:
        pass

def sig_handler(signum, frame):
    log_system_exit(f"시그널 수신 ({signum}) - 서버 재배포/중지")
    sys.exit(0)

signal.signal(signal.SIGTERM, sig_handler)
signal.signal(signal.SIGINT, sig_handler)
atexit.register(lambda: log_system_exit("정상 종료 또는 프로세스 중단"))

# instagrapi Import
try:
    from instagrapi import Client
    from instagrapi.exceptions import TwoFactorRequired, LoginRequired
except ImportError as e:
    err = f"instagrapi 라이브러리가 설치되지 않았습니다 ({e})."
    log_system_exit(err)
    sys.exit(1)

def login_instagram() -> Client:
    """인스타그램 로그인 (sessionid 최우선 및 안전 방어 로직)"""
    cl = Client()
    cl.request_timeout = 15
    
    # 0. INSTAGRAM_SESSION_ID 최우선 사용
    session_id = os.getenv("INSTAGRAM_SESSION_ID", "").strip()
    if session_id:
        try:
            print("🔑 sessionid 쿠키 값으로 인스타그램에 로그인합니다...", flush=True)
            cl.login_by_sessionid(session_id)
            print("🎉 sessionid 쿠키로 로그인 100% 성공! (로그인 알림 및 2FA 요청 없음)", flush=True)
            return cl
        except Exception as e:
            err_details = traceback.format_exc()
            print(f"❌ sessionid 쿠키 로그인 실패:\n{err_details}", flush=True)
            log_system_exit(f"sessionid 로그인 실패 ({e})")
            time.sleep(300)
            sys.exit(1)

    # 1. 환경변수 INSTAGRAM_SESSION_SETTINGS
    session_env = os.getenv("INSTAGRAM_SESSION_SETTINGS", "").strip()
    if session_env:
        try:
            print("🔄 세션 환경 변수로 로그인을 시도합니다...", flush=True)
            cl.set_settings(json.loads(session_env))
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("✅ 2FA 세션 환경 변수로 로그인 성공!", flush=True)
            return cl
        except Exception as e:
            print(f"⚠️ 세션 환경 변수 로그인 실패: {e}", flush=True)

    # 2. 비밀번호 신규 로그인 시도
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        err_msg = "INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD / INSTAGRAM_SESSION_ID 중 설정이 누락되었습니다."
        log_system_exit(err_msg)
        sys.exit(1)
        
    print(f"🔑 인스타그램 계정({INSTAGRAM_USERNAME}) 신규 로그인 시도 중...", flush=True)
    try:
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        cl.dump_settings(SESSION_PATH)
        print("✅ 비밀번호 로그인 성공!", flush=True)
        return cl
    except Exception as e:
        err_details = traceback.format_exc()
        print(f"\n❌ 로그인 시도 실패 상세:\n{err_details}", flush=True)
        log_system_exit(f"로그인 시도 실패 ({e})")
        time.sleep(300)
        sys.exit(1)

def extract_one_on_one_threads(cl: Client, amount_threads: int = 15) -> dict:
    threads_data = {}
    try:
        threads = cl.direct_threads(amount=amount_threads)
        for thread in threads:
            thread_id = str(thread.id)
            
            is_group_chat = getattr(thread, 'is_group', False) or len(thread.users) > 1
            if is_group_chat:
                continue
                
            users_map = {str(u.pk): u for u in thread.users}
            thread_messages = {}
            
            for msg in thread.messages:
                msg_id = str(msg.id)
                user_pk = str(msg.user_id)
                
                if user_pk == str(cl.user_id):
                    continue
                
                sender_info = users_map.get(user_pk)
                username = sender_info.username if sender_info else "알 수 없음"
                fullname = sender_info.full_name if sender_info else username
                text_content = msg.text if msg.text else f"[{msg.item_type} 미디어/스티커/이모지]"
                
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
        print(f"⚠️ 1대1 스레드 메시지 수신 중 오류 발생: {e}", flush=True)
        
    return threads_data

def monitor_loop():
    print("=" * 60, flush=True)
    print("🚀 인스타그램 개인 DM 삭제 감시 시스템 구동 시작!", flush=True)
    print(f"📌 모드: 3초 초고속 감지 / 텔레그램 명령어 지원 (/list, @아이디 검색) / KST", flush=True)
    print("=" * 60, flush=True)
    
    # 1. 헬스체크 웹서버 구동
    t_web = threading.Thread(target=start_health_check_server, daemon=True)
    t_web.start()
    
    # 2. 텔레그램 인터랙티브 명령어 리스너 구동
    t_cmd = threading.Thread(target=start_telegram_command_listener, daemon=True)
    t_cmd.start()
    
    init_db()
    cl = login_instagram()
    
    print("🔄 초기 1대1 DM 메시지들을 감시 기준점(baseline)으로 등록합니다...", flush=True)
    initial_threads = extract_one_on_one_threads(cl, amount_threads=15)
    all_initial_msgs = []
    initial_msg_ids = set()
    for t_id, msgs in initial_threads.items():
        all_initial_msgs.extend(msgs.values())
        initial_msg_ids.update(msgs.keys())
        
    save_baseline_messages(all_initial_msgs)
    
    kst_start_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    start_alert_text = (
        "🎉 <b>[인스타그램 DM 삭제 감시 시스템 구동 시작!]</b>\n\n"
        f"⏰ <b>시작 시각:</b> {kst_start_str} (한국시간)\n"
        f"⚡ <b>감시 주기:</b> {CHECK_INTERVAL}초 단위 초고속 모니터링\n\n"
        "🤖 <b>[사용 가능한 대화창 명령어]</b>\n"
        "• <code>/list</code> 또는 <code>리스트</code> : 오늘 삭제된 DM 히스토리 전체 출력\n"
        "• <code>@인스타아이디</code> : 해당 인스타 계정이 삭제한 DM 내역 검색\n"
        "  <i>(예시: <code>@suho_ov</code>)</i>"
    )
    send_telegram_message(start_alert_text)
    
    print("\n" + "🎉" * 30, flush=True)
    print(f"✅ 로그인 및 초기화 완료 ({kst_start_str} KST). 텔레그램 명령어 반응 모드 활성화 완료.", flush=True)
    print("🎉" * 30 + "\n", flush=True)
    
    consecutive_errors = 0
    
    while True:
        try:
            threads_data = extract_one_on_one_threads(cl, amount_threads=15)
            consecutive_errors = 0
            
            for thread_id, current_messages in threads_data.items():
                current_msg_ids = set(current_messages.keys())
                monitored_map = get_monitored_messages_for_thread(thread_id)
                monitored_msg_ids = set(monitored_map.keys())
                
                new_incoming_ids = current_msg_ids - initial_msg_ids - monitored_msg_ids
                if new_incoming_ids:
                    new_msgs = [current_messages[mid] for mid in new_incoming_ids]
                    save_new_incoming_messages(new_msgs)
                    for nm in new_msgs:
                        print(f"📩 [새 DM 수신] @{nm['sender_username']}: {nm['text'][:20]}...", flush=True)
                
                deleted_ids = monitored_msg_ids - current_msg_ids
                for d_id in deleted_ids:
                    deleted_info = mark_message_deleted(d_id)
                    if deleted_info:
                        print("!" * 60, flush=True)
                        print(f"🚨 [100% 진짜 전송 취소 감지!] 보낸사람: @{deleted_info['sender_username']}", flush=True)
                        print(f"내용: {deleted_info['text']}", flush=True)
                        print("!" * 60, flush=True)
                        
                        alert_realtime_deleted_dm(
                            sender_username=deleted_info["sender_username"],
                            sender_fullname=deleted_info["sender_fullname"],
                            text=deleted_info["text"],
                            timestamp_kst=deleted_info["timestamp"]
                        )
                        mark_deleted_as_reported([d_id])

            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            log_system_exit("사용자 수동 중단 (KeyboardInterrupt)")
            break
        except Exception as e:
            consecutive_errors += 1
            err_str = traceback.format_exc()
            print(f"⚠️ 감시 루프 오류 발생 ({e}). 에러 횟수: {consecutive_errors}\n{err_str}", flush=True)
            sleep_time = min(CHECK_INTERVAL * (2 ** consecutive_errors), 300)
            time.sleep(sleep_time)

if __name__ == "__main__":
    try:
        monitor_loop()
    except Exception as fatal_e:
        log_system_exit(f"치명적 오류 발생 ({fatal_e})\n{traceback.format_exc()}")
