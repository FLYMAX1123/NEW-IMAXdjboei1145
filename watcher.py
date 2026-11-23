#!/usr/bin/env python3
"""CGV 광교 IMAX 새 상영 감지 -> Discord 알림 (GitHub Actions용)"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from curl_cffi import requests

# ================= 설정 (여기만 고치면 됩니다) =================
SITE_NO = "0257"                 # CGV 광교 극장 코드
SITE_LABEL = "CGV 광교"          # 알림에 표시할 이름
SCREEN_KEYWORDS = ["IMAX"]       # 상영관/포맷 이름에 이 글자가 있으면 감지
NOTIFY_ON_FIRST_RUN = False      # 첫 실행 때 이미 열려있는 회차도 알릴지 (False=조용히 기록만)
SKIP_STARTED_TODAY = True        # 오늘 이미 시작한 회차는 제외
REQUEST_DELAY = 0.7              # 날짜별 요청 사이 대기(초)
ERROR_ALERT_COOLDOWN_HOURS = 12  # 오류 알림 최소 간격(시간)
# ==============================================================

KST = ZoneInfo("Asia/Seoul")
BASE = "https://cgv.co.kr/api/v1"
CO_CD = "A420"
BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movie"
HEADERS = {
    "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    "Accept": "application/json",
}
STATE_PATH = Path(__file__).resolve().parent / "state.json"


class BlockedError(Exception):
    """CGV가 접근을 막았을 때(403/429)."""


def api_get(path, params):
    r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS,
                     impersonate="chrome", timeout=30)
    if r.status_code in (403, 429):
        print(f"DEBUG status={r.status_code} cf-mitigated={r.headers.get('cf-mitigated')} server={r.headers.get('server')}", file=sys.stderr)
        print(f"DEBUG body={r.text[:300]!r}", file=sys.stderr)
        raise BlockedError(f"HTTP {r.status_code}")
    r.raise_for_status()
    body = r.json()
    if body.get("statusCode") not in (0, None):
        raise RuntimeError(f"API 오류 {body.get('statusCode')}: {body.get('statusMessage')}")
    data = body.get("data")
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return data or []


def get_open_dates():
    data = api_get("booking/searchSiteScnscYmdListBySite", {"coCd": CO_CD, "siteNo": SITE_NO})
    return sorted(d["scnYmd"] if isinstance(d, dict) else str(d) for d in data)


def get_shows(ymd):
    return api_get("booking/searchMovScnInfo",
                   {"coCd": CO_CD, "siteNo": SITE_NO, "scnYmd": ymd, "rtctlScopCd": "08"})


def start_hhmm(show):
    return re.sub(r"\D", "", str(show.get("scnsrtTm", "")))[:4]


def is_imax(show):
    text = " ".join(str(show.get(k, "")) for k in ("expoScnsNm", "scnsNm", "movkndDsplNm")).upper()
    return any(k.upper() in text for k in SCREEN_KEYWORDS)


def is_past(show, today, now_hhmm):
    ymd = str(show.get("scnYmd", ""))
    if ymd < today:
        return True
    if SKIP_STARTED_TODAY and ymd == today and start_hhmm(show) and start_hhmm(show) < now_hhmm:
        return True
    return False


def show_key(show):
    # 날짜가 맨 앞 -> 지난 날짜 기록을 쉽게 정리할 수 있음
    return "|".join(str(show.get(k, "")) for k in ("scnYmd", "scnsNo", "prodNo", "scnsrtTm"))


def fmt_date(ymd):
    dt = datetime.strptime(ymd, "%Y%m%d")
    return f"{dt.month}/{dt.day}({'월화수목금토일'[dt.weekday()]})"


def fmt_time(hhmm):
    return f"{hhmm[:2]}:{hhmm[2:]}" if len(hhmm) >= 4 else hhmm


# ---------------- Discord ----------------
def discord_send(webhook, payload):
    for _ in range(3):
        r = requests.post(webhook, json=payload, timeout=30,
                          headers={"User-Agent": "DiscordBot (cgv-imax-watch, 1.0)"})
        if r.status_code == 429:
            try:
                wait = float(r.json().get("retry_after", 2))
            except Exception:
                wait = 2
            time.sleep(min(wait, 10) + 0.5)
            continue
        if r.status_code >= 300:
            raise RuntimeError(f"Discord 전송 실패 HTTP {r.status_code}: {r.text[:200]}")
        return
    raise RuntimeError("Discord 전송 실패: 요청 제한(429)이 계속됨")


def send_new_shows(webhook, shows):
    groups = {}
    for s in shows:
        title = s.get("expoProdNm") or s.get("prodNm") or "제목 미상"
        screen = s.get("expoScnsNm") or s.get("scnsNm") or ""
        fmt = s.get("movkndDsplNm") or ""
        groups.setdefault((title, screen, fmt), {}).setdefault(str(s.get("scnYmd")), []).append(s)

    embeds = []
    for (title, screen, fmt), by_date in sorted(groups.items()):
        lines = []
        for ymd in sorted(by_date):
            items = sorted(by_date[ymd], key=start_hhmm)
            times = " · ".join(
                f"`{fmt_time(start_hhmm(s))}` ({s.get('frSeatCnt', '?')}/{s.get('stcnt', '?')})"
                for s in items)
            lines.append(f"**{fmt_date(ymd)}**  {times}")
        embeds.append({
            "title": f"🎬 {title}"[:250],
            "url": BOOKING_URL,
            "description": ("\n".join(lines))[:4000],
            "color": 0x00A0E9,
            "footer": {"text": f"{SITE_LABEL} · {screen or fmt} · (잔여/전체 좌석)"[:2000]},
        })

    for i in range(0, len(embeds), 10):  # 디스코드는 한 번에 embed 10개까지
        discord_send(webhook, {
            "content": f"🚨 **{SITE_LABEL} IMAX 새 상영 감지!**  [예매하러 가기]({BOOKING_URL})",
            "embeds": embeds[i:i + 10],
        })


# ---------------- 상태 저장 ----------------
def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"initialized": False, "notified": [], "last_error_alert": ""}


def save_state(state, notified, today):
    state["notified"] = sorted(k for k in notified if k[:8] >= today)  # 지난 날짜 기록 삭제
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def report_error(webhook, state, now, message):
    print(f"ERROR: {message}", file=sys.stderr)
    last = state.get("last_error_alert", "")
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(hours=ERROR_ALERT_COOLDOWN_HOURS):
                return
        except ValueError:
            pass
    try:
        discord_send(webhook, {"content": f"⚠️ **CGV 감시 오류** ({SITE_LABEL})\n{message}"})
        state["last_error_alert"] = now.isoformat()
    except Exception as e:
        print(f"오류 알림 전송도 실패: {e}", file=sys.stderr)


def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK_URL 이 설정되지 않았습니다.", file=sys.stderr)
        return 1

    now = datetime.now(KST)                    # 항상 한국 시간 기준
    today = now.strftime("%Y%m%d")
    now_hhmm = now.strftime("%H%M")
    state = load_state()
    notified = set(state.get("notified", []))

    try:
        dates = [d for d in get_open_dates() if d >= today]   # 과거 날짜 제외
        hits, site_name, total = [], "", 0
        for ymd in dates:
            for s in get_shows(ymd):
                total += 1
                site_name = site_name or s.get("siteNm", "")
                if is_imax(s) and not is_past(s, today, now_hhmm):
                    hits.append(s)
            time.sleep(REQUEST_DELAY)
    except BlockedError as e:
        report_error(webhook, state, now,
                     f"CGV가 접속을 막았습니다({e}). GitHub 서버 IP가 차단된 것일 수 있어요.")
        save_state(state, notified, today)
        return 0
    except Exception as e:
        report_error(webhook, state, now, f"조회 중 오류: {e}")
        save_state(state, notified, today)
        return 0

    new_hits = [s for s in hits if show_key(s) not in notified]
    print(f"[{now:%Y-%m-%d %H:%M} KST] 극장={site_name or '?'} 열린날짜={len(dates)} "
          f"전체회차={total} IMAX={len(hits)} 신규={len(new_hits)}")

    if not state.get("initialized"):
        if NOTIFY_ON_FIRST_RUN and new_hits:
            send_new_shows(webhook, new_hits)
        discord_send(webhook, {"content": (
            f"✅ **{SITE_LABEL} IMAX 감시 시작**\n"
            f"확인된 극장명: `{site_name or '데이터 없음'}` (코드 {SITE_NO})\n"
            f"현재 열린 날짜 {len(dates)}일 / 전체 {total}회차 / IMAX {len(hits)}회차\n"
            + ("이미 열린 IMAX 회차를 방금 알렸습니다." if NOTIFY_ON_FIRST_RUN
               else "이미 열린 IMAX 회차는 조용히 기록했고, 앞으로 **새로 열리는 것만** 알려드립니다.")
        )})
        notified.update(show_key(s) for s in hits)
        state["initialized"] = True
    else:
        if new_hits:
            send_new_shows(webhook, new_hits)       # 실패하면 예외 -> 기록 안 함 -> 다음에 재시도
            notified.update(show_key(s) for s in new_hits)
        if state.get("last_error_alert"):
            try:
                discord_send(webhook, {"content": f"✅ CGV 감시가 정상으로 복구됐습니다. ({SITE_LABEL})"})
                state["last_error_alert"] = ""
            except Exception:
                pass

    save_state(state, notified, today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
