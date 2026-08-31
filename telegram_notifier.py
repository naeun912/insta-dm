import json
import urllib.request
import urllib.parse
from typing import List
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

def send_hourly_deleted_dms_report(deleted_msgs: List[dict], kst_now_str: str) -> bool:
    """한 시간 동안 1대1 DM에서 삭제된 메시지들만 모아서 요약 리스트로 발송"""
    if not deleted_msgs:
        return True
        
    count = len(deleted_msgs)
    header = (
        f"📊 <b>[지난 1시간 동안 삭제된 개인 DM 리스트]</b>\n"
        f"⏰ <b>집계 기준:</b> {kst_now_str} (한국시간)\n"
        f"총 <b>{count}개</b>의 삭제된 메시지가 감지되었습니다.\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )
    
    body_items = []
    for idx, item in enumerate(deleted_msgs, 1):
        username = item.get("sender_username", "알 수 없음")
        fullname = item.get("sender_fullname", username)
        display_user = f"{fullname} (@{username})" if username != "알 수 없음" else fullname
        text = item.get("text", "(내용 없음)")
        ts = item.get("timestamp", "")
        
        item_str = (
            f"<b>{idx}. 보낸 사람:</b> {display_user}\n"
            f"💬 <b>삭제된 내용:</b> {text}\n"
            f"🕒 <b>원래 발송시간:</b> {ts} (한국시간)\n"
        )
        body_items.append(item_str)
        
    footer = "━━━━━━━━━━━━━━━━━━━\n💡 <i>단체방은 제외되며, 개인 DM에서 실제 전송 취소된 내역만 집계됩니다.</i>"
    
    full_text = header + "\n".join(body_items) + "\n" + footer
    return send_telegram_message(full_text)
