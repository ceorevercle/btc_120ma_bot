import os
import requests
import json
from datetime import datetime, timezone
from pathlib import Path

SYMBOL = "BTCUSDT"
MA_PERIOD = 120
PROXIMITY_PCT = 5.0
STATE_FILE = Path("state.json")

BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[DRY-RUN] 텔레그램 토큰/ID 없음")
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"텔레그램 전송: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"텔레그램 실패: {e}")

def get_klines(limit=121):
    params = {"symbol": SYMBOL, "interval": "1d", "limit": limit}
    r = requests.get(BINANCE_KLINE_URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def get_current_price():
    r = requests.get(BINANCE_TICKER_URL, params={"symbol": SYMBOL}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"state 저장: {state}")

def main():
    print("=== BTC 120MA 모니터 시작 ===")
    try:
        klines = get_klines(limit=MA_PERIOD+1)
    except Exception as e:
        print(f"바이낸스 조회 실패: {e}")
        return

    closes = [float(k[4]) for k in klines]
    yesterday_close = closes[-2]
    ma_yesterday = sum(closes[-MA_PERIOD-1:-1]) / MA_PERIOD
    yesterday_open_time = int(klines[-2][0]) / 1000
    yesterday_date = datetime.fromtimestamp(yesterday_open_time, tz=timezone.utc).strftime("%Y-%m-%d")

    try:
        current_price = get_current_price()
    except:
        current_price = closes[-1]
        print("현재가 조회 실패, 오늘 봉으로 대체")

    distance_pct = (current_price - ma_yesterday) / ma_yesterday * 100

    print(f"어제({yesterday_date}) 종가: {yesterday_close:,.2f}")
    print(f"120MA(어제 기준): {ma_yesterday:,.2f}")
    print(f"현재가: {current_price:,.2f} / 거리: {distance_pct:+.2f}%")

    state = load_state()
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if yesterday_close < ma_yesterday:
        last_breakdown = state.get("last_breakdown_alert_date")
        if last_breakdown != yesterday_date:
            msg = (
                f"💥 *BTC 일봉 120일선 이탈 확정*\n"
                f"어제({yesterday_date}) 종가가 120MA 아래서 마감\n"
                f"- 어제 종가: ${yesterday_close:,.2f}\n"
                f"- 120MA: ${ma_yesterday:,.2f}\n"
                f"- 괴리: {(yesterday_close-ma_yesterday)/ma_yesterday*100:+.2f}%\n"
                f"- 현재가: ${current_price:,.2f}\n\n"
                f"👉 수동 매도 검토 필요"
            )
            send_telegram(msg)
            state["last_breakdown_alert_date"] = yesterday_date
            state["last_proximity_alert_date"] = ""
            state["last_below_alert_date"] = ""
            save_state(state)
        else:
            print("이미 오늘 이탈 알림 보냄 - 스킵")
        return

    if distance_pct <= 0:
        last_below = state.get("last_below_alert_date")
        if last_below != today_utc:
            msg = (
                f"🚨 *BTC 120일선 하회 중 - 일봉 마감 대기*\n"
                f"- 현재가: ${current_price:,.2f}\n"
                f"- 120MA: ${ma_yesterday:,.2f}\n"
                f"- 괴리: {distance_pct:+.2f}% (하회)\n"
                f"- 어제 종가: ${yesterday_close:,.2f}\n\n"
                f"아직 마감 전이라 실행 안 함. 13시 마감 체크."
            )
            send_telegram(msg)
            state["last_below_alert_date"] = today_utc
            save_state(state)
        else:
            print("오늘 이미 하회중 알림 보냄 - 스킵")
        return

    if 0 < distance_pct <= PROXIMITY_PCT:
        last_prox = state.get("last_proximity_alert_date")
        prev_distance = state.get("last_distance")
        should_send = False
        if last_prox != today_utc:
            should_send = True
        if prev_distance is not None and prev_distance > PROXIMITY_PCT:
            should_send = True
        if not state:
            should_send = True

        if should_send:
            msg = (
                f"⚠️ *BTC 120일선 근접 중*\n"
                f"- 현재가: ${current_price:,.2f}\n"
                f"- 120MA: ${ma_yesterday:,.2f}\n"
                f"- 괴리: +{distance_pct:.2f}% (5% 이내)\n"
                f"- 어제 종가: ${yesterday_close:,.2f}\n\n"
                f"120일선까지 {distance_pct:.2f}% 남음."
            )
            send_telegram(msg)
            state["last_proximity_alert_date"] = today_utc
        else:
            print("근접 알림 오늘 이미 보냄 - 스킵")
    else:
        print(f"안정 구간 (괴리 +{distance_pct:.2f}% > 5%) - 알림 없음")

    state["last_distance"] = distance_pct
    state["last_check_utc"] = today_utc
    save_state(state)
    print("=== 종료 ===")

if __name__ == "__main__":
    main()