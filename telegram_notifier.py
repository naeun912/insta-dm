import json
import urllib.request
import urllib.parse
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

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

def alert_deleted_dm(sender_username: str, sender_fullname: str, text: str, timestamp: str):
    """전송 취소(삭제)된 DM에 대해서만 텔레그램 알림 전송"""
    username_display = f"@{sender_username}" if sender_username and sender_username != "알 수 없음" else "알 수 없음"
    name_display = sender_fullname if sender_fullname else "이름 없음"
    
    message_html = (
        "🚨 <b>[인스타그램 삭제된 DM 감지!]</b>\n\n"
        f"👤 <b>보낸 사람:</b> {name_display} ({username_display})\n"
        f"💬 <b>삭제된 내용:</b> {text}\n"
        f"🕒 <b>발송 시간:</b> {timestamp}\n\n"
        "⚠️ <i>상대방이 인스타에서 위 메시지를 전송 취소(삭제)했습니다.</i>"
    )
    
    return send_telegram_message(message_html)
