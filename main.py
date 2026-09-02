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
    INSTAGRAM_SESSION_ID,
    INSTAGRAM_SESSION_ID_2,
    CHECK_INTERVAL,
    SESSION_PATH
)

# ⭐ instagrapi 최신 미디어 URL pydantic ValidationError 무력화 몽키패치
import instagrapi.extractors
original_extract_media_v1_xma = instagrapi.extractors.extract_media_v1_xma

def safe_extract_media_v1_xma(data):
    try:
        return original_extract_media_v1_xma(data)
    except Exception:
        return None

instagrapi.extractors.extract_media_v1_xma = safe_extract_media_v1_xma

from db import (
    init_db,
    set_setting,
    get_setting,
    save_baseline_messages,
    save_new_incoming_messages,
    get_all_active_unreported_messages,
    mark_message_deleted
)
from telegram_notifier import alert_realtime_deleted_dm_batch, send_telegram_message, process_telegram_bot_commands

# 한국 표준시 (KST = UTC+9) 설정
KST = timezone(timedelta(hours=9))

# 전역 기준 시동 시각 (DB 보존)
SCRIPT_START_TIME = datetime.now(KST)

# 세션 만료 및 일시 차단 알림 중복 도배 방지용 캐시
reported_expired_accounts = set()
blocked_accounts = set()

# Render 무료 웹 서비스 포트 바인딩용 헬스체크 서버 (UptimeRobot 5분 모니터링 대응)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Instagram Multi-Account DM Monitor is Running!")
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

def get_session_clients() -> list:
    """등록된 인스타그램 계정 세션 클라이언트 리스트 반환"""
    session_ids = []
    
    # 1번 계정
    sid1 = os.getenv("INSTAGRAM_SESSION_ID", INSTAGRAM_SESSION_ID).strip()
    if sid1:
        session_ids.append(sid1)
        
    # 2번 계정
    sid2 = os.getenv("INSTAGRAM_SESSION_ID_2", INSTAGRAM_SESSION_ID_2).strip()
    if sid2:
        session_ids.append(sid2)

    clients = []
    for idx, sid in enumerate(session_ids, 1):
        try:
            cl = Client()
            cl.request_timeout = 15
            cl.login_by_sessionid(sid)
            acc_username = cl.username if hasattr(cl, 'username') and cl.username else cl.account_info().username
            print(f"🎉 [계정 {idx} 로그인 성공] @{acc_username} (PK: {cl.user_id})", flush=True)
            reported_expired_accounts.discard(acc_username)
            clients.append((acc_username, cl))
        except Exception as e:
            err_msg = f"❌ [계정 {idx} 세션 만료 / 로그인 실패]: {e}"
            print(err_msg, flush=True)
            if idx not in reported_expired_accounts:
                reported_expired_accounts.add(idx)
                alert_text = (
                    "⚠️ <b>[인스타그램 쿠키 만료 긴급 알림!]</b>\n\n"
                    f"📌 {idx}번 계정의 <code>sessionid</code> 쿠키가 만료되었거나 올바르지 않습니다.\n"
                    "인스타그램에서 새 sessionid 쿠키를 갱신해주셔야 감시가 정상 구동됩니다!"
                )
                send_telegram_message(alert_text)
            
    return clients

def extract_threads_for_client(username: str, cl: Client, amount_threads: int = 20, is_initial: bool = False) -> dict:
    """
    해당 계정의 1대1 및 단체방 포함 모든 direct_threads 스레드 메시지 수집.
    속도 제한(Blocked) 해제 시 자동 감지하여 텔레그램 푸시 알림 및 로그 출력.
    """
    threads_data = {}
    try:
        threads = cl.direct_threads(amount=amount_threads)
        
        # 이전 쿨타임/속도 제한(Blocked) 상태였다가 해제 성공 시 텔레그램 알림 및 로그 출력!
        if username in blocked_accounts:
            blocked_accounts.remove(username)
            unblocked_log = f"🎉 [@{username}] 인스타그램 속도 제한(Blocked) 해제 완료! 실시간 DM 감시가 정상 재개되었습니다."
            print(unblocked_log, flush=True)
            unblocked_alert = (
                "🎉 <b>[인스타그램 속도 제한(Blocked) 해제 완료!]</b>\n\n"
                f"📌 <b>계정:</b> @{username}\n"
                "인스타그램 일시 차단이 해제되어 실시간 DM 감시가 정상 재개되었습니다! 🚀"
            )
            send_telegram_message(unblocked_alert)

        # 성공 수집 시 세션 만료 캐시 차단 해제
        reported_expired_accounts.discard(username)
        
        for thread in threads:
            thread_id = str(thread.id)
            users_map = {str(u.pk): u for u in thread.users}
            
            is_group_chat = (getattr(thread, 'is_group', False) is True) or (getattr(thread, 'thread_type', '') == 'group') or len(thread.users) > 1
            thread_title = getattr(thread, 'thread_title', None) or getattr(thread, 'title', None)
            if not thread_title:
                if is_group_chat:
                    thread_title = "이름 없는 단체방"
                else:
                    thread_title = ""

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
                
                # 최초 시동 시각(SCRIPT_START_TIME) 이전 메시지는 무시
                if not is_initial and dt_kst < (SCRIPT_START_TIME - timedelta(seconds=10)):
                    continue
                
                timestamp_str = dt_kst.strftime("%Y-%m-%d %H:%M:%S")
                sender_info = users_map.get(user_pk)
                sender_name = sender_info.username if sender_info else "알 수 없음"
                fullname = sender_info.full_name if sender_info else sender_name
                text_content = msg.text if msg.text else f"[{msg.item_type} 미디어/스티커/이모지]"
                
                # 다중 계정 구분을 위해 message_id 식별키에 내 계정명 추가
                unique_msg_key = f"{username}_{msg_id}"
                
                thread_messages[unique_msg_key] = {
                    "message_id": unique_msg_key,
                    "my_account": username,
                    "thread_id": thread_id,
                    "thread_title": thread_title,
                    "sender_id": user_pk,
                    "sender_username": sender_name,
                    "sender_fullname": fullname,
                    "text": text_content,
                    "timestamp": timestamp_str,
                    "is_group": 1 if is_group_chat else 0
                }
            
            threads_data[thread_id] = thread_messages
    except Exception as e:
        err_str = str(e).lower()
        if "temporarily blocked" in err_str or "too fast" in err_str:
            if username not in blocked_accounts:
                blocked_accounts.add(username)
                print(f"⚠️ [@{username}] 인스타그램 속도 제한(Temporarily Blocked) 감지! 쿨타임 대기 중...", flush=True)
        elif any(keyword in err_str for keyword in ["login", "session", "401", "403", "unauthorized", "fail", "checkpoint", "challenge", "1404006"]):
            if username not in reported_expired_accounts and username not in blocked_accounts:
                reported_expired_accounts.add(username)
                print(f"⚠️ [@{username}] 인스타그램 세션 쿠키 만료 감지!: {e}", flush=True)
                alert_text = (
                    "⚠️ <b>[인스타그램 쿠키 만료 긴급 알림!]</b>\n\n"
                    f"📌 계정 <b>@{username}</b> 의 sessionid 쿠키가 만료되었습니다.\n"
                    "Render 설정에서 새 sessionid 쿠키를 갱신해주시면 감시가 다시 작동합니다!"
                )
                send_telegram_message(alert_text)
        else:
            print(f"⚠️ [@{username}] 스레드 수신 중 오류 발생: {e}", flush=True)
        
    return threads_data

def verify_real_deletion(client_map: dict, item: dict) -> bool:
    """
    ⭐ [2차 정밀 교차 검증]: 대화가 많이 진행되어 스크롤이 위로 밀린 것인지, 진짜 전송 취소(삭제)된 것인지 최종 확인!
    - 1시간 이상 지난 과거 메시지 ➡️ 무조건 False (옛날 대화 스크롤 밀림 오탐지 100% 방지!)
    - 최근 100개 대화 역사 속에 살아있으면 ➡️ False (스크롤 밀림 보존!)
    - 최근 1시간 이내 메시지이고 100개 역사에서도 완전히 사라졌으면 ➡️ True (100% 진짜 전송 취소!)
    - API 예외/네트워크 타임아웃 발생 시 ➡️ False (오탐지 방지를 위해 알림 보류)
    """
    try:
        my_acc = item.get("my_account", "")
        thread_id = item.get("thread_id", "")
        unique_msg_id = item.get("message_id", "")
        raw_msg_id = unique_msg_id.split("_", 1)[-1] if "_" in unique_msg_id else unique_msg_id
        
        # 1. 1시간 이상 지난 과거 메시지는 스크롤 밀림으로 처리하여 삭제 알림 100% 무조건 제외!
        ts_str = item.get("timestamp", "")
        if ts_str:
            try:
                msg_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                now_kst = datetime.now(KST)
                if (now_kst - msg_dt).total_seconds() > 3600:
                    print(f"🛡️ [과거 대화 보존] @{my_acc} 과거 메시지({ts_str})는 1시간 이상 경과하여 삭제 알림에서 무조건 제외.", flush=True)
                    return False
            except Exception:
                pass

        cl = client_map.get(my_acc)
        if not cl or not thread_id:
            return False
            
        # 최근 100개 메시지 깊이 수집 (대화 폭주 스크롤 밀림 완벽 대응)
        thread = cl.direct_thread(thread_id, amount=100)
        if thread and thread.messages:
            thread_msg_ids = {str(m.id) for m in thread.messages}
            if raw_msg_id in thread_msg_ids:
                # 최근 100개 대화 역사 속에 여전히 살아있음 ➡️ 단순 스크롤 밀림! (전송 취소 아님!)
                print(f"🛡️ [스크롤 밀림 보존] @{my_acc} 스레드 {thread_id} 최근 100개 내 메시지({raw_msg_id})가 살아있으므로 삭제 알림 제외.", flush=True)
                return False
                
        # 100개 깊이 탐색에서도 완벽하게 사라짐 ➡️ 100% 진짜 전송 취소(삭제)!
        return True
    except Exception as e:
        print(f"⚠️ 2차 검증 중 예외 발생 ({e}), 오탐지 방지를 위해 안전하게 알림 제외 처리", flush=True)
        return False

def monitor_loop():
    global SCRIPT_START_TIME, reported_expired_accounts, blocked_accounts
    init_db()
    
    # DB에 보존된 최초 시동 시간 확인 또는 새로 설정
    saved_time_str = get_setting("INITIAL_BASELINE_TIME")
    now_kst = datetime.now(KST)
    
    if saved_time_str:
        try:
            SCRIPT_START_TIME = datetime.strptime(saved_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except Exception:
            SCRIPT_START_TIME = now_kst
            set_setting("INITIAL_BASELINE_TIME", now_kst.strftime("%Y-%m-%d %H:%M:%S"))
    else:
        SCRIPT_START_TIME = now_kst
        set_setting("INITIAL_BASELINE_TIME", now_kst.strftime("%Y-%m-%d %H:%M:%S"))
        
    kst_start_str = SCRIPT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 60, flush=True)
    print("🚀 인스타그램 다중 계정 실시간 DM 삭제 감시 시스템 구동 시작!", flush=True)
    print(f"📌 감시 영구 기준 시각(Baseline): {kst_start_str} (KST)", flush=True)
    print("=" * 60, flush=True)
    
    t_web = threading.Thread(target=start_health_check_server, daemon=True)
    t_web.start()
    
    t_cmd = threading.Thread(target=start_telegram_command_listener, daemon=True)
    t_cmd.start()
    
    clients = get_session_clients()
    
    if not clients:
        print("❌ 로그인에 성공한 인스타그램 계정이 없습니다.", flush=True)
        sys.exit(1)

    client_map = {acc: cl for acc, cl in clients}
    account_names_str = ", ".join([f"@{acc}" for acc, _ in clients])
    
    # 1단계: 시동 시점 각 계정 수신함 기존 메시지 동기화 (Baseline)
    print(f"🔄 감시 기준 시각({kst_start_str}) 이전 메시지들을 감시 제외(Baseline)로 등록합니다...", flush=True)
    initial_msg_ids = set()
    all_initial_msgs = []
    
    for username, cl in clients:
        init_threads = extract_threads_for_client(username, cl, amount_threads=20, is_initial=True)
        for t_id, msgs in init_threads.items():
            all_initial_msgs.extend(msgs.values())
            initial_msg_ids.update(msgs.keys())
            
    save_baseline_messages(all_initial_msgs)
    print(f"✅ 총 {len(clients)}개 계정({account_names_str}) 기존 과거 메시지 감시 제외(Baseline) 등록 완료!", flush=True)

    start_alert_text = (
        "🎉 <b>[인스타그램 DM 삭제 감시 가동 완료!]</b>\n\n"
        f"⏰ <b>감시 영구 기준 시각:</b> {kst_start_str} (KST)\n"
        f"📱 <b>감시 계정 ({len(clients)}개):</b> {account_names_str}\n"
        f"⚡ <b>감시 주기:</b> {CHECK_INTERVAL}초 단위 실시간 순환 감시\n"
        "🎯 <b>[속도 제한 해제 실시간 푸시 알림 탑재 완료]</b>\n"
        "새로 도착하는 DM 삭제 시 즉시 텔레그램으로 알려드립니다!"
    )
    send_telegram_message(start_alert_text)
    
    print("\n" + "🎉" * 30, flush=True)
    print(f"✅ 총 {len(clients)}개 계정({account_names_str}) {CHECK_INTERVAL}초 간격 다중 실시간 DM 감시 가동 중.", flush=True)
    print("🎉" * 30 + "\n", flush=True)
    
    consecutive_errors = 0
    loop_count = 0
    
    while True:
        try:
            loop_count += 1
            all_current_msg_ids = set()
            all_current_messages_map = {}
            
            for username, cl in clients:
                threads_data = extract_threads_for_client(username, cl, amount_threads=20, is_initial=False)
                for t_id, msgs in threads_data.items():
                    all_current_msg_ids.update(msgs.keys())
                    all_current_messages_map.update(msgs)
                    
            consecutive_errors = 0

            # DB에 저장된 시동 이후 활성 감시 메시지 집합
            all_monitored_map = get_all_active_unreported_messages()
            all_monitored_msg_ids = set(all_monitored_map.keys())

            # 1. 시동 이후 새로 수신된 DM 발견 ➡️ DB 감시 대상 저장
            new_incoming_ids = all_current_msg_ids - initial_msg_ids - all_monitored_msg_ids
            if new_incoming_ids:
                new_msgs = [all_current_messages_map[mid] for mid in new_incoming_ids]
                save_new_incoming_messages(new_msgs)
                for nm in new_msgs:
                    room_str = f" [👥 {nm['thread_title']}]" if nm['is_group'] == 1 and nm['thread_title'] else ""
                    print(f"📩 [새 DM 수신] @{nm['my_account']} ⬅️ @{nm['sender_username']}{room_str}: {nm['text']}", flush=True)

            # 2. 감시 대상 메시지가 대화방 상위 목록에서 사라짐 ➡️ 2차 교차 검증 수행 후 100% 진짜 전송 취소(삭제)만 발송!!
            deleted_ids = all_monitored_msg_ids - all_current_msg_ids
            if deleted_ids:
                print(f"🔍 [사라진 DM {len(deleted_ids)}개 감지] 2차 이중 검증 진행 중...", flush=True)
                deleted_items = []
                for d_id in deleted_ids:
                    candidate_item = all_monitored_map.get(d_id)
                    if candidate_item:
                        print(f"  • 검증 중: @{candidate_item.get('sender_username')}: '{candidate_item.get('text')}'", flush=True)
                        is_truly_deleted = verify_real_deletion(client_map, candidate_item)
                        if is_truly_deleted:
                            print(f"  ✅ [100% 삭제 확정!]: '{candidate_item.get('text')}'", flush=True)
                            deleted_info = mark_message_deleted(d_id)
                            if deleted_info:
                                deleted_items.append(deleted_info)
                        else:
                            print(f"  🛡️ [스크롤 밀림 보존]: '{candidate_item.get('text')}'", flush=True)
                
                if deleted_items:
                    print("!" * 60, flush=True)
                    print(f"🚨 [100% 진짜 전송 취소 감지!] 총 {len(deleted_items)}개 삭제됨.", flush=True)
                    for item in deleted_items:
                        print(f" - 계정: @{item['my_account']} / 보낸사람: @{item['sender_username']} / 내용: {item['text']}", flush=True)
                    print("!" * 60, flush=True)
                    
                    alert_realtime_deleted_dm_batch(deleted_items)

            if loop_count % 10 == 0:
                print(f"🔄 [다중 계정 감시 가동 중] {loop_count}번째 {CHECK_INTERVAL}초 감시 완료 (계정: {account_names_str} / 활성 메시지: {len(all_current_msg_ids)}개)", flush=True)

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
