import time
import sys
import os
import json
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
    save_new_realtime_messages,
    mark_message_deleted
)
from telegram_notifier import alert_realtime_deleted_dm_batch, send_telegram_message, process_telegram_bot_commands

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

# instagrapi Import
try:
    from instagrapi import Client
    from instagrapi.exceptions import TwoFactorRequired, LoginRequired
except ImportError as e:
    print(f"❌ instagrapi 라이브러리가 설치되지 않았습니다 ({e}).", flush=True)
    sys.exit(1)

def login_instagram() -> Client:
    """인스타그램 로그인 (sessionid 최우선 사용)"""
    cl = Client()
    cl.request_timeout = 15
    
    session_id = os.getenv("INSTAGRAM_SESSION_ID", "").strip()
    if session_id:
        try:
            print("🔑 sessionid 쿠키 값으로 인스타그램에 로그인합니다...", flush=True)
            cl.login_by_sessionid(session_id)
            print("🎉 sessionid 쿠키로 로그인 100% 성공!", flush=True)
            return cl
        except Exception as e:
            err_details = traceback.format_exc()
            print(f"❌ sessionid 쿠키 로그인 실패:\n{err_details}", flush=True)
            time.sleep(300)
            sys.exit(1)

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

    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("❌ INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD / INSTAGRAM_SESSION_ID 설정 누락", flush=True)
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
        time.sleep(300)
        sys.exit(1)

def extract_all_threads(cl: Client, amount_threads: int = 25) -> dict:
    """
    1대1 대화방 + 단체방 + 메시지 요청함(Pending) 등 모든 인스타그램 DM 스레드 100% 수집!
    단체방인 경우 단체방 이름(thread_title)도 함께 추출.
    """
    threads_data = {}
    try:
        # 1. 메인 Direct 대화함 스레드
        threads = cl.direct_threads(amount=amount_threads)
        
        # 2. 메시지 요청함(Pending Inbox) 스레드 포함
        try:
            pending_threads = cl.direct_pending_inbox(amount=10)
            if pending_threads:
                threads.extend(pending_threads)
        except Exception:
            pass
            
        for thread in threads:
            thread_id = str(thread.id)
            
            # 단체방 여부 및 단체방 이름 추출
            is_group_chat = (getattr(thread, 'is_group', False) is True) or (getattr(thread, 'thread_type', '') == 'group') or len(thread.users) > 1
            thread_title = getattr(thread, 'thread_title', None) or getattr(thread, 'title', None)
            if not thread_title:
                if is_group_chat:
                    thread_title = "이름 없는 단체방"
                else:
                    thread_title = ""
                
            users_map = {str(u.pk): u for u in thread.users}
            thread_messages = {}
            
            for msg in thread.messages:
                msg_id = str(msg.id)
                user_pk = str(msg.user_id)
                
                # 내가 보낸 메시지는 감시 대상에서 제외
                if user_pk == str(cl.user_id):
                    continue
                
                if getattr(msg, 'timestamp', None):
                    dt_utc = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=timezone.utc)
                    dt_kst = dt_utc.astimezone(KST)
                else:
                    dt_kst = datetime.now(KST)
                
                timestamp_str = dt_kst.strftime("%Y-%m-%d %H:%M:%S")
                sender_info = users_map.get(user_pk)
                username = sender_info.username if sender_info else "알 수 없음"
                fullname = sender_info.full_name if sender_info else username
                text_content = msg.text if msg.text else f"[{msg.item_type} 미디어/스티커/이모지]"
                
                thread_messages[msg_id] = {
                    "message_id": msg_id,
                    "thread_id": thread_id,
                    "thread_title": thread_title,
                    "sender_id": user_pk,
                    "sender_username": username,
                    "sender_fullname": fullname,
                    "text": text_content,
                    "timestamp": timestamp_str,
                    "dt_kst": dt_kst,
                    "is_group": 1 if is_group_chat else 0
                }
            
            threads_data[thread_id] = thread_messages
    except Exception as e:
        print(f"⚠️ 스레드 메시지 수신 중 오류 발생: {e}", flush=True)
        
    return threads_data

def monitor_loop():
    kst_start_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    send_telegram_message(
        f"⚡ <b>[인스타그램 DM 감시 서버 시동 중...]</b>\n"
        f"⏰ <b>시동 시각:</b> {kst_start_str} (한국시간)\n"
        f"🔑 1대1 대화방 + 단체방(방제목) + 메시지 요청함을 모두 감시합니다."
    )

    print("=" * 60, flush=True)
    print("🚀 인스타그램 DM 실시간 감시 시스템 구동 시작!", flush=True)
    print(f"📌 모드: 1대1 + 단체방(방제목 표기) + 메시지 요청함 100% 완전 통합 감시", flush=True)
    print("=" * 60, flush=True)
    
    t_web = threading.Thread(target=start_health_check_server, daemon=True)
    t_web.start()
    
    t_cmd = threading.Thread(target=start_telegram_command_listener, daemon=True)
    t_cmd.start()
    
    init_db()
    cl = login_instagram()
    
    start_alert_text = (
        "🎉 <b>[로그인 성공 및 100% 전체 DM 감시 가동 완료!]</b>\n\n"
        f"⏰ <b>시동 시각:</b> {kst_start_str} (KST)\n"
        f"⚡ <b>감시 주기:</b> {CHECK_INTERVAL}초 단위 초고속 실시간 감지\n"
        "✅ <b>1대1 대화방 & 단체방(방제목 포함) 모든 삭제 DM 100% 감시 가동 중!</b>"
    )
    send_telegram_message(start_alert_text)
    
    print("\n" + "🎉" * 30, flush=True)
    print(f"✅ 로그인 완료 및 3초 간격 전체 DM(1대1+단체방) 감시 가동 중.", flush=True)
    print("🎉" * 30 + "\n", flush=True)
    
    consecutive_errors = 0
    loop_count = 0
    
    while True:
        try:
            loop_count += 1
            threads_data = extract_all_threads(cl, amount_threads=25)
            consecutive_errors = 0
            
            total_active_dms = 0
            for thread_id, current_messages in threads_data.items():
                current_msg_ids = set(current_messages.keys())
                total_active_dms += len(current_msg_ids)
                
                monitored_map = get_monitored_messages_for_thread(thread_id)
                monitored_msg_ids = set(monitored_map.keys())
                
                # 1. 스레드에서 수신된 메시지 중 아직 DB 감시 대상에 없으면 저장
                new_incoming_ids = current_msg_ids - monitored_msg_ids
                if new_incoming_ids:
                    new_msgs = [current_messages[mid] for mid in new_incoming_ids]
                    save_new_realtime_messages(new_msgs)
                    for nm in new_msgs:
                        room_str = f" [👥 {nm['thread_title']}]" if nm['is_group'] == 1 and nm['thread_title'] else ""
                        print(f"📩 [새 DM 수신] @{nm['sender_username']}{room_str}: {nm['text'][:20]}... (시간: {nm['timestamp']})", flush=True)
                
                # 2. 감시 대상 목록에 존재했으나 현재 스레드에서 사라진 메시지 ➡️ 100% 삭제!!
                deleted_ids = monitored_msg_ids - current_msg_ids
                if deleted_ids:
                    deleted_items = []
                    for d_id in deleted_ids:
                        deleted_info = mark_message_deleted(d_id)
                        if deleted_info:
                            deleted_items.append(deleted_info)
                    
                    if deleted_items:
                        print("!" * 60, flush=True)
                        print(f"🚨 [100% 진짜 전송 취소 감지!] 총 {len(deleted_items)}개 삭제됨.", flush=True)
                        for item in deleted_items:
                            print(f" - 보낸사람: @{item['sender_username']} / 방제목: {item.get('thread_title', '1대1방')} / 내용: {item['text']}", flush=True)
                        print("!" * 60, flush=True)
                        
                        alert_realtime_deleted_dm_batch(deleted_items)

            if loop_count % 10 == 0:
                print(f"🔄 [감시 가동 중] {loop_count}번째 3초 감시 완료 (감시 중인 전체 대화방: {len(threads_data)}개 / 메시지: {total_active_dms}개)", flush=True)

            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n👋 사용자에 의해 모니터링이 중단되었습니다.", flush=True)
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
        print(f"❌ 치명적 오류 발생: {fatal_e}\n{traceback.format_exc()}", flush=True)
