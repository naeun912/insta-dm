import json
import urllib.request
import urllib.parse
from typing import List, Tuple
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from db import get_todays_deleted_messages, get_deleted_messages_by_username

def send_telegram_message(text: str) -> bool:
    """텔레그램 봇으로 메시지를 발송하는 함수"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ [텔레그램] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("ok", False)
    except Exception as e:
        print(f"❌ [텔레그램 알림 발송 실패]: {e}")
        return False

def alert_realtime_deleted_dm(sender_username: str, sender_fullname: str, text: str, timestamp_kst: str) -> bool:
    """새로 온 1대1 DM이 삭제된 순간 즉시 실시간 텔레그램 발송"""
    username_display = f"@{sender_username}" if sender_username and sender_username != "알 수 없음" else "알 수 없음"
    name_display = sender_fullname if sender_fullname else username_display
    
    message_html = (
        "🚨 <b>[인스타그램 삭제된 DM 감지!]</b>\n\n"
        f"👤 <b>보낸 사람:</b> {name_display} ({username_display})\n"
        f"💬 <b>삭제된 내용:</b> {text}\n"
        f"🕒 <b>원래 발송시간:</b> {timestamp_kst} (한국시간)\n\n"
        "⚠️ <i>상대방이 인스타에서 위 메시지를 전송 취소(삭제)했습니다.</i>"
    )
    
    return send_telegram_message(message_html)

def fetch_telegram_updates(offset: int = 0) -> Tuple[list, int]:
    """텔레그램 사용자 수신 명령어 폴링"""
    if not TELEGRAM_BOT_TOKEN:
        return [], offset

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=1"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if res_data.get("ok"):
                result = res_data.get("result", [])
                new_offset = offset
                if result:
                    new_offset = result[-1]["update_id"] + 1
                return result, new_offset
    except Exception:
        pass
    return [], offset

def process_telegram_bot_commands(last_offset: int) -> int:
    """텔레그램 사용자 명령어 처리 (/list, @아이디, /help 등)"""
    updates, new_offset = fetch_telegram_updates(last_offset)
    for update in updates:
        message = update.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))
        
        # 지정된 본인 Chat ID에서 온 명령어가 아니면 무시
        if str(chat_id) != str(TELEGRAM_CHAT_ID):
            continue
            
        if not text:
            continue
            
        cmd = text.lower()
        
        # 1. /list 또는 /today 또는 '리스트' -> 오늘 하루 전체 삭제 내역 출력
        if cmd in ["/list", "/today", "리스트", "목록", "/start"]:
            deleted_list = get_todays_deleted_messages()
            if not deleted_list:
                send_telegram_message("📭 <b>오늘 감지되어 삭제된 1대1 DM 내역이 없습니다!</b>")
            else:
                items_text = []
                for idx, item in enumerate(deleted_list, 1):
                    username = item.get("sender_username", "알 수 없음")
                    fullname = item.get("sender_fullname", username)
                    display_user = f"{fullname} (@{username})" if username != "알 수 없음" else fullname
                    items_text.append(
                        f"<b>{idx}. 보낸 사람:</b> {display_user}\n"
                        f"💬 <b>삭제된 내용:</b> {item.get('text')}\n"
                        f"🕒 <b>발송 시각:</b> {item.get('timestamp')} (KST)\n"
                    )
                header = f"📊 <b>[오늘 하루 삭제된 DM 전체 리스트 (총 {len(deleted_list)}건)]</b>\n━━━━━━━━━━━━━━━━━━━\n"
                full_resp = header + "\n".join(items_text) + "\n━━━━━━━━━━━━━━━━━━━"
                send_telegram_message(full_resp)

        # 2. @아이디 또는 /user @아이디 -> 특정 유저 삭제 내역 검색
        elif text.startswith("@") or text.startswith("/user"):
            username = text.replace("/user", "").strip().lstrip("@")
            if not username:
                send_telegram_message("⚠️ 검색할 인스타 아이디를 입력해주세요. (예: <code>@suho_ov</code>)")
                continue
                
            user_deleted = get_deleted_messages_by_username(username)
            if not user_deleted:
                send_telegram_message(f"🔍 <b>@{username}</b> 님의 삭제된 DM 기록이 없습니다.")
            else:
                items_text = []
                for idx, item in enumerate(user_deleted, 1):
                    items_text.append(
                        f"<b>{idx}. 내용:</b> {item.get('text')}\n"
                        f"🕒 <b>발송 시각:</b> {item.get('timestamp')} (KST)\n"
                    )
                header = f"👤 <b>[@{username} 님의 삭제된 DM 히스토리 (총 {len(user_deleted)}건)]</b>\n━━━━━━━━━━━━━━━━━━━\n"
                full_resp = header + "\n".join(items_text) + "\n━━━━━━━━━━━━━━━━━━━"
                send_telegram_message(full_resp)

        # 3. /help 명령어 안내
        elif cmd in ["/help", "도움말", "명령어"]:
            help_text = (
                "🤖 <b>[인스타그램 삭제 DM 감시 봇 명령어 안내]</b>\n\n"
                "• <code>/list</code> 또는 <code>리스트</code> : 오늘 삭제된 모든 DM 히스토리 출력\n"
                "• <code>@인스타아이디</code> : 해당 사용자가 보냈다 삭제한 DM 히스토리 검색\n"
                "  <i>(예시: <code>@suho_ov</code> 입력)</i>\n"
                "• <code>/help</code> : 본 도움말 보기"
            )
            send_telegram_message(help_text)

    return new_offset
