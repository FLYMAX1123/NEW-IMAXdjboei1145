import json
import re
import urllib.error
import urllib.request

from curl_cffi import requests as cr

API = "https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListBySite?coCd=A420&siteNo=0257"
CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def clean(text):
    t = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:300]


def report(name, status, text):
    print(f"[{name}] status={status} body={clean(text)!r}", flush=True)


# 0) 이 서버의 IP / 국가
try:
    with urllib.request.urlopen("https://ipinfo.io/json", timeout=20) as r:
        d = json.loads(r.read().decode())
    print(f"[내 서버] ip={d.get('ip')} country={d.get('country')} org={d.get('org')}", flush=True)
except Exception as e:
    print(f"[내 서버] 확인 실패: {e}", flush=True)

# 1) 일반 urllib + 크롬 UA + Referer
try:
    req = urllib.request.Request(API, headers={
        "User-Agent": CHROME_UA,
        "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        report("1 urllib+UA", r.status, r.read().decode("utf-8", "ignore"))
except urllib.error.HTTPError as e:
    report("1 urllib+UA", e.code, e.read().decode("utf-8", "ignore"))
except Exception as e:
    print(f"[1 urllib+UA] 오류: {e}", flush=True)

# 2) curl_cffi 크롬 위장, 헤더 없이
try:
    r = cr.get(API, impersonate="chrome", timeout=30)
    report("2 cffi 기본", r.status_code, r.text)
except Exception as e:
    print(f"[2 cffi 기본] 오류: {e}", flush=True)

# 3) curl_cffi 크롬 위장 + 한국어 + Referer
try:
    r = cr.get(API, impersonate="chrome", timeout=30, headers={
        "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    report("3 cffi+한국어", r.status_code, r.text)
except Exception as e:
    print(f"[3 cffi+한국어] 오류: {e}", flush=True)

# 4) 홈페이지 자체
try:
    r = cr.get("https://cgv.co.kr/", impersonate="chrome", timeout=30)
    report("4 홈페이지", r.status_code, r.text)
except Exception as e:
    print(f"[4 홈페이지] 오류: {e}", flush=True)
