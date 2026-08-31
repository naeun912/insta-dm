import time
import sys
from datetime import datetime
from config import (
    INSTAGRAM_USERNAME,
    INSTAGRAM_PASSWORD,
    CHECK_INTERVAL,
    SESSION_PATH
)
from db import init_db, get_active_messages_map, save_new_messages, mark_message_deleted
from telegram_notifier import alert_deleted_dm

# instagrapi Import
try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired
except ImportError:
    print("❌ instagrapi 라이브러리가 설치되지 않았습니다. 'pip install -r requirements.txt'를 먼저 실행해주세요.")
    sys.exit(1)

def login_instagram() -> Client:
    """인스타그램 로그인 및 세션 관리"""
    cl = Client()
    
    # 보안 제재 방지를 위한 타임아웃/딜레이 설정
    cl.request_timeout = 10
    
    # 세션 파일이 있는 경우 세션 로드 시도
    if SESSION_PATH.exists():
        try:
            print(f"🔄 기존 세션 파일({SESSION_PATH.name})에서 로그인을 시도합니다...")
            cl.load_settings(SESSION_PATH)
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            print("✅ 기존 세션으로 로그인 성공!")
            return cl
        except Exception as e:
            print(f"⚠️ 기존 세션 로그인 실패 ({e}). 새로 로그인을 진행합니다...")

    # 세션이 없거나 실패한 경우 신규 로그인
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        print("❌ .env 파일에 INSTAGRAM_USERNAME과 INSTAGRAM_PASSWORD를 작성해주세요.")
        sys.exit(1)
        
    print(f"🔑 인스타그램 계정({INSTAGRAM_USERNAME}) 신규 로그인 시도 중...")
    try:
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
        cl.dump_settings(SESSION_PATH)
        print("✅ 로그인 성공 및 세션 저장 완료!")
        return cl
    except Exception as e:
        print(f"❌ 로그인 실패: {e}")
        sys.exit(1)

def extract_thread_messages(cl: Client, amount_threads: int = 15) -> dict:
    """최근 스레드의 메시지들을 읽어와 dict 구조로 변환"""
    current_messages = {}
    
    try:
        threads = cl.direct_threads(amount=amount_threads)
        for thread in threads:
            thread_id = str(thread.id)
            users_map = {str(u.pk): u for u in thread.users}
            
            for msg in thread.messages:
                msg_id = str(msg.id)
                user_pk = str(msg.user_id)
                
                # 내 계정에서 보낸 메시지는 감시 대상 제외 (상대방 메시지만 감시)
                if user_pk == str(cl.user_id):
                    continue
                
                sender_info = users_map.get(user_pk)
                username = sender_info.username if sender_info else "알 수 없음"
                fullname = sender_info.full_name if sender_info else username
                
                # 텍스트 내용 처리
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
    
    # 1. DB 초기화
    init_db()
    
    # 2. 인스타 로그인
    cl = login_instagram()
    
    print(f"👀 DM 모니터링을 시작합니다. (감시 주기: {CHECK_INTERVAL}초)")
    print("💡 일반 DM은 텔레그램으로 보내지 않으며, '삭제된 DM'만 텔레그램 알림이 발송됩니다.")
    
    first_run = True
    
    while True:
        try:
            # 3. 현재 인스타 최근 메시지 목록 가져오기
            current_messages = extract_thread_messages(cl, amount_threads=15)
            current_msg_ids = set(current_messages.keys())
            
            # 4. 이전 모니터링 시점의 DB 내 활성 메시지 목록
            stored_active_map = get_active_messages_map()
            stored_msg_ids = set(stored_active_map.keys())
            
            if first_run:
                # 첫 실행 시점에는 현재 존재하는 메시지들을 DB에 초기 기입 (알림 쏘지 않음)
                save_new_messages(list(current_messages.values()))
                print(f"✅ 초기 메시지 {len(current_messages)}개 동기화 완료.")
                first_run = False
            else:
                # 5. [신규 메시지 감지] -> DB에만 살며시 저장
                new_msg_ids = current_msg_ids - stored_msg_ids
                if new_msg_ids:
                    new_msgs = [current_messages[mid] for mid in new_msg_ids]
                    save_new_messages(new_msgs)
                    for nm in new_msgs:
                        print(f"📩 [신규 메시지 도착 기록] @{nm['sender_username']}: {nm['text'][:20]}...")

                # 6. [전송 취소/삭제된 메시지 감지!] -> 텔레그램으로 즉시 알림!!
                deleted_msg_ids = stored_msg_ids - current_msg_ids
                for d_id in deleted_msg_ids:
                    deleted_msg_info = mark_message_deleted(d_id)
                    if deleted_msg_info:
                        print("!" * 60)
                        print(f"🚨 [전송 취소 DM 감지!] 보낸사람: @{deleted_msg_info['sender_username']}")
                        print(f"내용: {deleted_msg_info['text']}")
                        print("!" * 60)
                        
                        # 텔레그램 알림 발송!
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
