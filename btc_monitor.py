import os, json, math, sys
from datetime import datetime, timezone, timedelta
import requests

STATE_FILE = "state.json"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_INTERVAL = "1d"

def get_klines(limit=200):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": BINANCE_SYMBOL, "interval": BINANCE_INTERVAL, "limit": limit}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def calc_ma(closes, period=120):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def send_telegram(token, chat_id, text):
    if not token or not chat_id:
        print("텔레그램 토큰/챗ID 없음")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=15)
        print(f"텔레그램 전송: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"state 저장: {state}")

def main():
    print("=== BTC 120MA 모니터 시작 ===")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    force_notify = os.getenv("FORCE_NOTIFY", "").lower() in ("1", "true", "yes")
    print(f"FORCE_NOTIFY={force_notify}")

    klines = get_klines(limit=200)
    closes = [float(k[4]) for k in klines]
    times = [int(k[0]) for k in klines]

    yesterday_close = closes[-2]
    yesterday_time = datetime.fromtimestamp(times[-2]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
    ma120_yesterday = calc_ma(closes[:-1], 120)
    current_price = closes[-1]

    if ma120_yesterday is None:
        print("120MA 계산 불가")
        return

    distance = (current_price - ma120_yesterday) / ma120_yesterday * 100
    print(f"어제({yesterday_time}) 종가: {yesterday_close:,.2f}")
    print(f"120MA(어제 기준): {ma120_yesterday:,.2f}")
    print(f"현재가: {current_price:,.2f} / 거리: {distance:+.2f}%")

    state = load_state()
    last_distance = state.get("last_distance")

    # 1) 이탈 확정: 어제 종가 < 120MA
    if yesterday_close < ma120_yesterday:
        msg = f"💥 BTC 120MA 이탈 확정\n어제({yesterday_time}) 종가 ${yesterday_close:,.2f} < 120MA ${ma120_yesterday:,.2f} ({((yesterday_close-ma120_yesterday)/ma120_yesterday*100):+.2f}%)\n현재가 ${current_price:,.2f}"
        send_telegram(token, chat_id, msg)
    # 2) 하회 중
    elif current_price < ma120_yesterday:
        msg = f"🚨 BTC 120MA 하회 중\n현재가 ${current_price:,.2f} < 120MA ${ma120_yesterday:,.2f} ({distance:+.2f}%)"
        send_telegram(token, chat_id, msg)
    # 3) 근접 중 (5% 이내)
    elif distance <= 5.0:
        if last_distance is None or last_distance > 5.0:
            msg = f"⚠️ BTC 120MA 근접\n현재가 ${current_price:,.2f}, 120MA ${ma120_yesterday:,.2f} ({distance:+.2f}%) - 5% 이내 진입"
            send_telegram(token, chat_id, msg)
        else:
            print("이미 근접 알림 보낸 상태 - 중복 방지")
    else:
        # 안정 구간
        if force_notify:
            msg = f"✅ BTC 일일 리포트 ({yesterday_time})\n어제 종가: ${yesterday_close:,.2f}\n120MA: ${ma120_yesterday:,.2f}\n현재가: ${current_price:,.2f}\n괴리: {distance:+.2f}%\n상태: 안정 구간 - 문제 없음"
            print("일일 리포트 발송 시도")
            send_telegram(token, chat_id, msg)
        else:
            print(f"안정 구간 (괴리 {distance:+.2f}% > 5%) - 알림 없음")

    save_state({"last_distance": distance, "last_check_utc": datetime.now(timezone.utc).isoformat()})
    print("=== 종료 ===")

if __name__ == "__main__":
    main()
