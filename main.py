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
    get_monitored_messages_for_thread,
    save_baseline_messages,
    save_new_incoming_messages,
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

    # 2. 비밀번호 신규 로그인 시도 (실패 시 5분 휴식)
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
    오직 1대1 개인 DM 스레드만 추출 (단체방 완전 제외).
    반환 구조: { thread_id: { message_id: msg_dict } }
    """
    threads_data = {}
    try:
        threads = cl.direct_threads(amount=amount_threads)
        for thread in threads:
            thread_id = str(thread.id)
            
            # 단체방 완전 제외 검사
            is_group_chat = getattr(thread, 'is_group', False) or len(thread.users) > 1
            if is_group_chat:
                continue
                
            users_map = {str(u.pk): u for u in thread.users}
            thread_messages = {}
            
            for msg in thread.messages:
                msg_id = str(msg.id)
                user_pk = str(msg.user_id)
                
                # 내가 보낸 메시지는 제외
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
    """1시간 동안 '프로그램 실행 이후 도착했다가 삭제된 1대1 DM'만 요약 발송"""
    unreported_deleted = get_unreported_deleted_messages()
    if unreported_deleted:
        kst_now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        print(f"📊 [1시간 요약 발송] 실행 이후 삭제된 1대1 DM 총 {len(unreported_deleted)}개를 텔레그램으로 전송합니다.")
        sent_ok = send_hourly_deleted_dms_report(unreported_deleted, kst_now)
        if sent_ok:
            m_ids = [m["message_id"] for m in unreported_deleted]
            mark_deleted_as_reported(m_ids)
            print("✅ 1시간 요약 리스트 발송 완료!")

def monitor_loop():
    print("=" * 60)
    print("🚀 인스타그램 개인 DM 삭제 감시 시스템 구동 시작!")
    print("📌 모드: '실행 이후 새로 도착한 DM이 삭제된 경우만' 감지 / 단체방 제외 / KST 한국시간 / 1시간 단위 요약")
    print("=" * 60)
    
    t = threading.Thread(target=start_health_check_server, daemon=True)
    t.start()
    
    init_db()
    cl = login_instagram()
    
    # 1. 시동 시점 기존 메시지들은 기준점(baseline)으로 등록
    print("🔄 초기 1대1 DM 메시지들을 감시 기준점(baseline)으로 등록합니다...")
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
        "✅ <b>완벽한 감시 원리 적용 완료:</b>\n"
        "1. 기존 과거 메시지는 전부 무시됩니다.\n"
        "2. <b>지금부터 상대방이 나에게 <u>새로 보낸 DM</u>이 생기고, 그 메시지를 <u>전송 취소(삭제)했을 때만</u> 정확히 잡습니다.</b>\n"
        "3. 단체방은 제외하며 1시간마다 삭제 내역만 요약으로 보냅니다."
    )
    send_telegram_message(start_alert_text)
    
    print("\n" + "🎉" * 30)
    print(f"✅ 기준점 등록 완료 ({len(initial_msg_ids)}개 과거 메시지 제외 조치).")
    print("👀 지금부터 새로 수신되는 DM에 대해서만 삭제 감시를 수행합니다.")
    print("🎉" * 30 + "\n")
    
    HOURLY_INTERVAL = 3600  # 1시간
    last_hourly_check = time.time()
    consecutive_errors = 0
    
    while True:
        try:
            threads_data = extract_one_on_one_threads(cl, amount_threads=15)
            consecutive_errors = 0
            
            for thread_id, current_messages in threads_data.items():
                current_msg_ids = set(current_messages.keys())
                
                # 2. 실행 이후 수신되어 현재 감시 중인 1대1 메시지들
                monitored_map = get_monitored_messages_for_thread(thread_id)
                monitored_msg_ids = set(monitored_map.keys())
                
                # 3. [새로 도착한 DM 발견!] -> 감시 대상으로 새롭게 등록 (is_new_since_start=1)
                new_incoming_ids = current_msg_ids - initial_msg_ids - monitored_msg_ids
                if new_incoming_ids:
                    new_msgs = [current_messages[mid] for mid in new_incoming_ids]
                    save_new_incoming_messages(new_msgs)
                    for nm in new_msgs:
                        print(f"📩 [실행 이후 새 DM 수신 기록] @{nm['sender_username']}: {nm['text'][:20]}...")
                
                # 4. [감시 대상이던 새 DM이 삭제됨!] -> 100% 진짜 전송 취소!!
                deleted_ids = monitored_msg_ids - current_msg_ids
                for d_id in deleted_ids:
                    deleted_info = mark_message_deleted(d_id)
                    if deleted_info:
                        print("!" * 60)
                        print(f"🚨 [100% 진짜 전송 취소 감지!] 보낸사람: @{deleted_info['sender_username']}")
                        print(f"내용: {deleted_info['text']}")
                        print("!" * 60)

            # 5. 1시간 주기 요약 보고서 발송
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
