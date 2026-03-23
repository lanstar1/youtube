#!/usr/bin/env python3
"""
LANstar YouTube Channel Analyzer
- YouTube Data API v3로 채널 전체 영상 메타데이터 수집
- 성과 분석 (조회수, 참여도, 패턴)
- 인터랙티브 HTML 대시보드 생성
"""

import json
import sys
import os
import re
import math
from datetime import datetime, timedelta
from collections import Counter

# ─── 설정 ───────────────────────────────────────────────
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CHANNEL_HANDLE = "@LANstar"  # 채널 핸들
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── YouTube API 클라이언트 ──────────────────────────────
from googleapiclient.discovery import build

def get_channel_id(youtube, handle):
    """채널 핸들로 채널 ID 조회"""
    # 직접 지정된 채널 ID (LANstar랜스타)
    KNOWN_CHANNEL_ID = "UC5flcH9DY01UpoCw3y0QgcA"
    if handle == "@LANstar":
        return KNOWN_CHANNEL_ID

    # @handle 방식으로 검색
    req = youtube.search().list(
        part="snippet",
        q=handle,
        type="channel",
        maxResults=1
    )
    res = req.execute()
    if res.get("items"):
        return res["items"][0]["snippet"]["channelId"]
    return None

def get_all_video_ids(youtube, channel_id):
    """채널의 모든 영상 ID 수집 (uploads 플레이리스트 활용)"""
    # 채널의 uploads 플레이리스트 ID 가져오기
    req = youtube.channels().list(
        part="contentDetails,statistics,snippet,brandingSettings",
        id=channel_id
    )
    res = req.execute()
    channel_info = res["items"][0]
    uploads_id = channel_info["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    next_page = None

    while True:
        req = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_page
        )
        res = req.execute()

        for item in res["items"]:
            video_ids.append(item["contentDetails"]["videoId"])

        next_page = res.get("nextPageToken")
        if not next_page:
            break

    print(f"  → 총 {len(video_ids)}개 영상 ID 수집 완료")
    return video_ids, channel_info

def get_video_details(youtube, video_ids):
    """영상 상세 정보 일괄 조회 (50개씩 배치)"""
    videos = []

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        req = youtube.videos().list(
            part="snippet,statistics,contentDetails,topicDetails",
            id=",".join(batch)
        )
        res = req.execute()

        for item in res["items"]:
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            content = item["contentDetails"]

            # ISO 8601 duration 파싱
            duration = parse_duration(content["duration"])

            videos.append({
                "id": item["id"],
                "title": snippet["title"],
                "description": snippet.get("description", ""),
                "publishedAt": snippet["publishedAt"],
                "tags": snippet.get("tags", []),
                "categoryId": snippet.get("categoryId", ""),
                "thumbnail": snippet["thumbnails"].get("high", snippet["thumbnails"].get("default", {})).get("url", ""),
                "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
                "commentCount": int(stats.get("commentCount", 0)),
                "duration": duration,
                "durationISO": content["duration"],
                "url": f"https://www.youtube.com/watch?v={item['id']}"
            })

        print(f"  → {min(i+50, len(video_ids))}/{len(video_ids)} 영상 상세 정보 수집...")

    return videos

def parse_duration(iso_duration):
    """ISO 8601 duration → 초 단위 변환"""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_duration)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s

# ─── 분석 엔진 ──────────────────────────────────────────

def analyze_videos(videos, channel_info):
    """전체 분석 수행"""
    if not videos:
        return {}

    # 기본 통계
    total = len(videos)
    total_views = sum(v["viewCount"] for v in videos)
    total_likes = sum(v["likeCount"] for v in videos)
    total_comments = sum(v["commentCount"] for v in videos)
    avg_views = total_views / total if total else 0
    avg_likes = total_likes / total if total else 0
    avg_duration = sum(v["duration"] for v in videos) / total if total else 0

    # 채널 통계
    ch_stats = channel_info.get("statistics", {})
    subscriber_count = int(ch_stats.get("subscriberCount", 0))

    # 참여도 계산 (engagement rate)
    for v in videos:
        views = max(v["viewCount"], 1)
        v["engagementRate"] = round((v["likeCount"] + v["commentCount"]) / views * 100, 2)
        v["likeRatio"] = round(v["likeCount"] / views * 100, 2)

    # 시간별 분석
    for v in videos:
        dt = datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00"))
        v["year"] = dt.year
        v["month"] = dt.month
        v["yearMonth"] = f"{dt.year}-{dt.month:02d}"
        v["dayOfWeek"] = dt.strftime("%A")
        v["hour"] = dt.hour

    # 월별 업로드 & 조회수 추이
    monthly = {}
    for v in videos:
        ym = v["yearMonth"]
        if ym not in monthly:
            monthly[ym] = {"count": 0, "views": 0, "likes": 0, "comments": 0}
        monthly[ym]["count"] += 1
        monthly[ym]["views"] += v["viewCount"]
        monthly[ym]["likes"] += v["likeCount"]
        monthly[ym]["comments"] += v["commentCount"]

    # 태그 분석
    all_tags = []
    for v in videos:
        all_tags.extend([t.lower() for t in v["tags"]])
    tag_counts = Counter(all_tags).most_common(50)

    # 제목 키워드 분석
    title_words = []
    for v in videos:
        words = re.findall(r'[가-힣]+|[a-zA-Z]+', v["title"])
        title_words.extend([w.lower() for w in words if len(w) > 1])
    # 불용어 제거
    stopwords = {"the", "and", "for", "is", "in", "to", "of", "a", "an", "it", "with",
                 "이", "그", "저", "것", "수", "등", "및", "를", "을", "에", "의", "가",
                 "는", "은", "로", "으로", "에서", "와", "과", "도", "만", "까지", "부터"}
    title_words = [w for w in title_words if w not in stopwords]
    keyword_counts = Counter(title_words).most_common(40)

    # 영상 길이별 성과 분석
    duration_buckets = {
        "0-1분 (Shorts)": (0, 60),
        "1-3분": (60, 180),
        "3-5분": (180, 300),
        "5-10분": (300, 600),
        "10-20분": (600, 1200),
        "20분+": (1200, 99999)
    }
    duration_analysis = {}
    for label, (lo, hi) in duration_buckets.items():
        bucket_videos = [v for v in videos if lo <= v["duration"] < hi]
        if bucket_videos:
            duration_analysis[label] = {
                "count": len(bucket_videos),
                "avgViews": round(sum(v["viewCount"] for v in bucket_videos) / len(bucket_videos)),
                "avgEngagement": round(sum(v["engagementRate"] for v in bucket_videos) / len(bucket_videos), 2),
                "avgLikes": round(sum(v["likeCount"] for v in bucket_videos) / len(bucket_videos)),
            }

    # TOP 성과 영상
    top_by_views = sorted(videos, key=lambda x: x["viewCount"], reverse=True)[:20]
    top_by_engagement = sorted(videos, key=lambda x: x["engagementRate"], reverse=True)[:20]
    top_by_likes = sorted(videos, key=lambda x: x["likeCount"], reverse=True)[:20]

    # 최근 트렌드 (최근 6개월 vs 이전)
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)
    recent = [v for v in videos if datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00")).replace(tzinfo=None) > six_months_ago]
    older = [v for v in videos if datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00")).replace(tzinfo=None) <= six_months_ago]

    recent_stats = {
        "count": len(recent),
        "avgViews": round(sum(v["viewCount"] for v in recent) / max(len(recent), 1)),
        "avgEngagement": round(sum(v["engagementRate"] for v in recent) / max(len(recent), 1), 2),
    }
    older_stats = {
        "count": len(older),
        "avgViews": round(sum(v["viewCount"] for v in older) / max(len(older), 1)),
        "avgEngagement": round(sum(v["engagementRate"] for v in older) / max(len(older), 1), 2),
    }

    # 리메이크 우선순위 (높은 조회수 + 오래된 영상)
    remake_candidates = []
    for v in videos:
        dt = datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00")).replace(tzinfo=None)
        age_days = (now - dt).days
        if age_days > 365 and v["viewCount"] > avg_views:
            score = (v["viewCount"] / avg_views) * (age_days / 365)
            remake_candidates.append({**v, "remakeScore": round(score, 2), "ageDays": age_days})
    remake_candidates.sort(key=lambda x: x["remakeScore"], reverse=True)

    # 카테고리 분류 (기획안의 5대 카테고리 기반)
    categories = {
        "홈오피스/재택": ["usb", "독", "dock", "kvm", "모니터", "암", "허브", "hub", "재택", "홈오피스", "데스크", "desk"],
        "선정리/인테리어": ["케이블", "cable", "정리", "랩핑", "튜브", "매직", "선정리", "타이", "tie"],
        "영상/방송": ["hdmi", "분배기", "캡쳐", "capture", "splitter", "switch", "스위치", "방송", "영상"],
        "네트워크/서버": ["랜", "lan", "네트워크", "network", "서버", "server", "카드", "nic", "스위칭", "허브", "패치", "cat"],
        "트러블슈팅": ["테스터", "tester", "컨버터", "converter", "문제", "해결", "오류", "느림", "안됨"]
    }

    for v in videos:
        text = (v["title"] + " " + " ".join(v["tags"])).lower()
        v["category"] = "기타"
        max_match = 0
        for cat, keywords in categories.items():
            matches = sum(1 for kw in keywords if kw in text)
            if matches > max_match:
                max_match = matches
                v["category"] = cat

    category_stats = {}
    for cat in list(categories.keys()) + ["기타"]:
        cat_videos = [v for v in videos if v["category"] == cat]
        if cat_videos:
            category_stats[cat] = {
                "count": len(cat_videos),
                "avgViews": round(sum(v["viewCount"] for v in cat_videos) / len(cat_videos)),
                "avgEngagement": round(sum(v["engagementRate"] for v in cat_videos) / len(cat_videos), 2),
                "totalViews": sum(v["viewCount"] for v in cat_videos),
            }

    # 요일별 업로드 성과
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_kr = {"Monday": "월", "Tuesday": "화", "Wednesday": "수", "Thursday": "목", "Friday": "금", "Saturday": "토", "Sunday": "일"}
    day_stats = {}
    for day in day_order:
        day_videos = [v for v in videos if v["dayOfWeek"] == day]
        if day_videos:
            day_stats[day_kr[day]] = {
                "count": len(day_videos),
                "avgViews": round(sum(v["viewCount"] for v in day_videos) / len(day_videos)),
            }

    return {
        "channelName": channel_info["snippet"]["title"],
        "subscriberCount": subscriber_count,
        "totalVideos": total,
        "totalViews": total_views,
        "totalLikes": total_likes,
        "totalComments": total_comments,
        "avgViews": round(avg_views),
        "avgLikes": round(avg_likes),
        "avgDuration": round(avg_duration),
        "avgEngagement": round(sum(v["engagementRate"] for v in videos) / total, 2),
        "monthly": dict(sorted(monthly.items())),
        "tagCounts": tag_counts,
        "keywordCounts": keyword_counts,
        "durationAnalysis": duration_analysis,
        "topByViews": top_by_views[:20],
        "topByEngagement": top_by_engagement[:20],
        "topByLikes": top_by_likes[:20],
        "recentStats": recent_stats,
        "olderStats": older_stats,
        "remakeCandidates": remake_candidates[:30],
        "categoryStats": category_stats,
        "dayStats": day_stats,
        "allVideos": videos,
    }

# ─── 대시보드 HTML 생성 ─────────────────────────────────

def generate_dashboard(analysis):
    """인터랙티브 HTML 대시보드 생성"""

    # 월별 데이터
    months = list(analysis["monthly"].keys())
    monthly_views = [analysis["monthly"][m]["views"] for m in months]
    monthly_counts = [analysis["monthly"][m]["count"] for m in months]

    # 태그/키워드
    tag_labels = [t[0] for t in analysis["tagCounts"][:20]]
    tag_values = [t[1] for t in analysis["tagCounts"][:20]]
    kw_labels = [k[0] for k in analysis["keywordCounts"][:20]]
    kw_values = [k[1] for k in analysis["keywordCounts"][:20]]

    # 영상 길이별
    dur_labels = list(analysis["durationAnalysis"].keys())
    dur_views = [analysis["durationAnalysis"][d]["avgViews"] for d in dur_labels]
    dur_counts = [analysis["durationAnalysis"][d]["count"] for d in dur_labels]
    dur_engagement = [analysis["durationAnalysis"][d]["avgEngagement"] for d in dur_labels]

    # 카테고리별
    cat_labels = list(analysis["categoryStats"].keys())
    cat_views = [analysis["categoryStats"][c]["avgViews"] for c in cat_labels]
    cat_counts = [analysis["categoryStats"][c]["count"] for c in cat_labels]
    cat_engagement = [analysis["categoryStats"][c]["avgEngagement"] for c in cat_labels]

    # 요일별
    day_labels = list(analysis["dayStats"].keys())
    day_views = [analysis["dayStats"][d]["avgViews"] for d in day_labels]
    day_counts = [analysis["dayStats"][d]["count"] for d in day_labels]

    # TOP 영상 테이블 데이터
    top_views_json = json.dumps(analysis["topByViews"][:20], ensure_ascii=False)
    top_engagement_json = json.dumps(analysis["topByEngagement"][:20], ensure_ascii=False)
    remake_json = json.dumps(analysis["remakeCandidates"][:30], ensure_ascii=False)
    all_videos_json = json.dumps(analysis["allVideos"], ensure_ascii=False)

    def fmt(n):
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        if n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)

    def fmt_duration(sec):
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}시간 {m}분"
        return f"{m}분 {s}초"

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LANstar YouTube 채널 분석 대시보드</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', -apple-system, sans-serif; background: #0f1117; color: #e4e4e7; }}
.header {{ background: linear-gradient(135deg, #1a1b2e 0%, #16213e 100%); padding: 32px 40px; border-bottom: 1px solid #2a2d3e; }}
.header h1 {{ font-size: 28px; font-weight: 700; color: #fff; }}
.header .subtitle {{ color: #9ca3af; margin-top: 6px; font-size: 14px; }}
.header .date {{ color: #6b7280; font-size: 12px; margin-top: 4px; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px; }}
.kpi {{ background: #1a1b2e; border: 1px solid #2a2d3e; border-radius: 12px; padding: 20px; }}
.kpi .label {{ font-size: 12px; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi .value {{ font-size: 28px; font-weight: 700; color: #fff; margin-top: 4px; }}
.kpi .sub {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
.kpi.highlight {{ border-color: #3b82f6; background: linear-gradient(135deg, #1e2a4a 0%, #1a1b2e 100%); }}
.section {{ margin-bottom: 28px; }}
.section-title {{ font-size: 18px; font-weight: 600; color: #fff; margin-bottom: 16px; padding-left: 12px; border-left: 3px solid #3b82f6; }}
.chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(580px, 1fr)); gap: 20px; }}
.chart-card {{ background: #1a1b2e; border: 1px solid #2a2d3e; border-radius: 12px; padding: 20px; }}
.chart-card h3 {{ font-size: 14px; color: #9ca3af; margin-bottom: 12px; }}
.chart-container {{ position: relative; height: 300px; }}
.tabs {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
.tab {{ padding: 8px 16px; border-radius: 8px; border: 1px solid #2a2d3e; background: transparent; color: #9ca3af; cursor: pointer; font-size: 13px; transition: all 0.2s; }}
.tab:hover {{ border-color: #3b82f6; color: #fff; }}
.tab.active {{ background: #3b82f6; border-color: #3b82f6; color: #fff; }}
.table-wrap {{ overflow-x: auto; max-height: 500px; overflow-y: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #252736; color: #9ca3af; text-align: left; padding: 10px 12px; position: sticky; top: 0; z-index: 1; font-weight: 600; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #2a2d3e; }}
tr:hover {{ background: #1e2030; }}
.thumb {{ width: 120px; height: 68px; border-radius: 6px; object-fit: cover; }}
a {{ color: #60a5fa; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
.badge-up {{ background: #064e3b; color: #34d399; }}
.badge-down {{ background: #4c0519; color: #fb7185; }}
.trend-box {{ display: flex; gap: 16px; flex-wrap: wrap; }}
.trend-item {{ background: #1a1b2e; border: 1px solid #2a2d3e; border-radius: 12px; padding: 16px 20px; flex: 1; min-width: 200px; }}
.trend-item .label {{ font-size: 12px; color: #9ca3af; }}
.trend-item .val {{ font-size: 22px; font-weight: 700; color: #fff; margin: 4px 0; }}
.search-box {{ padding: 10px 16px; background: #252736; border: 1px solid #2a2d3e; border-radius: 8px; color: #fff; width: 100%; max-width: 400px; margin-bottom: 16px; font-size: 14px; }}
.search-box::placeholder {{ color: #6b7280; }}
.insight-box {{ background: linear-gradient(135deg, #1e2a4a 0%, #1a1b2e 100%); border: 1px solid #3b82f6; border-radius: 12px; padding: 20px; margin-bottom: 28px; }}
.insight-box h3 {{ color: #60a5fa; font-size: 16px; margin-bottom: 12px; }}
.insight-box p {{ color: #d1d5db; font-size: 14px; line-height: 1.7; }}
.insight-box .highlight-text {{ color: #fbbf24; font-weight: 600; }}
@media (max-width: 768px) {{
  .chart-grid {{ grid-template-columns: 1fr; }}
  .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>📊 {analysis["channelName"]} YouTube 채널 분석</h1>
  <div class="subtitle">Phase 1: 기존 영상 분석 — 콘텐츠 성과 패턴 및 리메이크 우선순위</div>
  <div class="date">분석일: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 총 {analysis["totalVideos"]}개 영상</div>
</div>

<div class="container">

<!-- KPI 카드 -->
<div class="kpi-grid">
  <div class="kpi highlight">
    <div class="label">구독자</div>
    <div class="value">{fmt(analysis["subscriberCount"])}</div>
  </div>
  <div class="kpi">
    <div class="label">총 영상 수</div>
    <div class="value">{analysis["totalVideos"]:,}</div>
  </div>
  <div class="kpi">
    <div class="label">총 조회수</div>
    <div class="value">{fmt(analysis["totalViews"])}</div>
  </div>
  <div class="kpi">
    <div class="label">평균 조회수</div>
    <div class="value">{fmt(analysis["avgViews"])}</div>
    <div class="sub">영상당</div>
  </div>
  <div class="kpi">
    <div class="label">총 좋아요</div>
    <div class="value">{fmt(analysis["totalLikes"])}</div>
  </div>
  <div class="kpi">
    <div class="label">평균 참여도</div>
    <div class="value">{analysis["avgEngagement"]}%</div>
    <div class="sub">(좋아요+댓글)/조회수</div>
  </div>
  <div class="kpi">
    <div class="label">평균 영상 길이</div>
    <div class="value">{fmt_duration(analysis["avgDuration"])}</div>
  </div>
  <div class="kpi">
    <div class="label">총 댓글</div>
    <div class="value">{fmt(analysis["totalComments"])}</div>
  </div>
</div>

<!-- AI 인사이트 -->
<div class="insight-box">
  <h3>💡 핵심 인사이트 요약</h3>
  <p id="insightText">데이터 분석 결과가 여기에 표시됩니다.</p>
</div>

<!-- 최근 vs 과거 트렌드 -->
<div class="section">
  <div class="section-title">📈 최근 6개월 vs 이전 트렌드</div>
  <div class="trend-box">
    <div class="trend-item">
      <div class="label">최근 6개월 영상 수</div>
      <div class="val">{analysis["recentStats"]["count"]}개</div>
    </div>
    <div class="trend-item">
      <div class="label">최근 6개월 평균 조회수</div>
      <div class="val">{fmt(analysis["recentStats"]["avgViews"])}</div>
      <div>
        {"<span class='badge badge-up'>↑ 성장</span>" if analysis["recentStats"]["avgViews"] > analysis["olderStats"]["avgViews"] else "<span class='badge badge-down'>↓ 하락</span>"}
        vs 이전 {fmt(analysis["olderStats"]["avgViews"])}
      </div>
    </div>
    <div class="trend-item">
      <div class="label">최근 참여도</div>
      <div class="val">{analysis["recentStats"]["avgEngagement"]}%</div>
      <div>
        {"<span class='badge badge-up'>↑ 성장</span>" if analysis["recentStats"]["avgEngagement"] > analysis["olderStats"]["avgEngagement"] else "<span class='badge badge-down'>↓ 하락</span>"}
        vs 이전 {analysis["olderStats"]["avgEngagement"]}%
      </div>
    </div>
  </div>
</div>

<!-- 차트 섹션 -->
<div class="section">
  <div class="section-title">📊 시간별 분석</div>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>월별 조회수 추이</h3>
      <div class="chart-container"><canvas id="monthlyViewsChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>월별 업로드 빈도</h3>
      <div class="chart-container"><canvas id="monthlyCountChart"></canvas></div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">🎯 콘텐츠 성과 분석</div>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>카테고리별 평균 조회수</h3>
      <div class="chart-container"><canvas id="categoryChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>영상 길이별 평균 조회수</h3>
      <div class="chart-container"><canvas id="durationChart"></canvas></div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">🏷️ 키워드 & 태그 분석</div>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>제목 키워드 TOP 20</h3>
      <div class="chart-container"><canvas id="keywordChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>태그 사용 빈도 TOP 20</h3>
      <div class="chart-container"><canvas id="tagChart"></canvas></div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">📅 요일별 업로드 성과</div>
  <div class="chart-grid">
    <div class="chart-card">
      <h3>요일별 평균 조회수 & 업로드 수</h3>
      <div class="chart-container"><canvas id="dayChart"></canvas></div>
    </div>
    <div class="chart-card">
      <h3>카테고리별 참여도</h3>
      <div class="chart-container"><canvas id="catEngagementChart"></canvas></div>
    </div>
  </div>
</div>

<!-- 테이블 섹션 -->
<div class="section">
  <div class="section-title">🏆 TOP 영상 랭킹</div>
  <div class="tabs">
    <button class="tab active" onclick="showTable('views')">조회수 TOP 20</button>
    <button class="tab" onclick="showTable('engagement')">참여도 TOP 20</button>
    <button class="tab" onclick="showTable('remake')">리메이크 후보</button>
    <button class="tab" onclick="showTable('all')">전체 영상</button>
  </div>
  <input type="text" class="search-box" id="searchInput" placeholder="🔍 영상 제목 검색..." oninput="filterTable()">
  <div class="chart-card">
    <div class="table-wrap" id="tableContainer"></div>
  </div>
</div>

</div>

<script>
// ─── 데이터 ───
const topViews = {top_views_json};
const topEngagement = {top_engagement_json};
const remakeCandidates = {remake_json};
const allVideos = {all_videos_json};

// ─── Chart.js 글로벌 설정 ───
Chart.defaults.color = '#9ca3af';
Chart.defaults.borderColor = '#2a2d3e';
Chart.defaults.font.family = "'Segoe UI', sans-serif";

// ─── 차트 생성 ───
// 월별 조회수
new Chart(document.getElementById('monthlyViewsChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(months)},
    datasets: [{{
      label: '월별 조회수',
      data: {json.dumps(monthly_views)},
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.1)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 12 }} }},
      y: {{ ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }} }}
    }}
  }}
}});

// 월별 업로드
new Chart(document.getElementById('monthlyCountChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(months)},
    datasets: [{{
      label: '업로드 수',
      data: {json.dumps(monthly_counts)},
      backgroundColor: '#6366f1',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ ticks: {{ maxTicksLimit: 12 }} }} }}
  }}
}});

// 카테고리별 조회수
new Chart(document.getElementById('categoryChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(cat_labels)},
    datasets: [{{
      label: '평균 조회수',
      data: {json.dumps(cat_views)},
      backgroundColor: ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899'],
      borderRadius: 6,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }} }} }}
  }}
}});

// 영상 길이별
new Chart(document.getElementById('durationChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(dur_labels)},
    datasets: [{{
      label: '평균 조회수',
      data: {json.dumps(dur_views)},
      backgroundColor: '#10b981',
      borderRadius: 6,
    }},{{
      label: '영상 수',
      data: {json.dumps(dur_counts)},
      backgroundColor: '#6366f1',
      borderRadius: 6,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{ y: {{ ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }} }} }}
  }}
}});

// 키워드
new Chart(document.getElementById('keywordChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(kw_labels)},
    datasets: [{{
      label: '빈도',
      data: {json.dumps(kw_values)},
      backgroundColor: '#f59e0b',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// 태그
new Chart(document.getElementById('tagChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(tag_labels)},
    datasets: [{{
      label: '빈도',
      data: {json.dumps(tag_values)},
      backgroundColor: '#ec4899',
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

// 요일별
new Chart(document.getElementById('dayChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(day_labels)},
    datasets: [{{
      label: '평균 조회수',
      data: {json.dumps(day_views)},
      backgroundColor: '#3b82f6',
      borderRadius: 6,
      yAxisID: 'y',
    }},{{
      label: '업로드 수',
      data: {json.dumps(day_counts)},
      type: 'line',
      borderColor: '#f59e0b',
      pointBackgroundColor: '#f59e0b',
      yAxisID: 'y1',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{
      y: {{ position: 'left', ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }} }},
      y1: {{ position: 'right', grid: {{ display: false }} }}
    }}
  }}
}});

// 카테고리 참여도
new Chart(document.getElementById('catEngagementChart'), {{
  type: 'radar',
  data: {{
    labels: {json.dumps(cat_labels)},
    datasets: [{{
      label: '참여도 (%)',
      data: {json.dumps(cat_engagement)},
      borderColor: '#8b5cf6',
      backgroundColor: 'rgba(139,92,246,0.2)',
      pointBackgroundColor: '#8b5cf6',
    }},{{
      label: '영상 수',
      data: {json.dumps(cat_counts)},
      borderColor: '#10b981',
      backgroundColor: 'rgba(16,185,129,0.1)',
      pointBackgroundColor: '#10b981',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    scales: {{ r: {{ grid: {{ color: '#2a2d3e' }}, angleLines: {{ color: '#2a2d3e' }} }} }}
  }}
}});

// ─── 테이블 렌더링 ───
let currentTab = 'views';

function fmtNum(n) {{
  if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n/1000).toFixed(1) + 'K';
  return n.toString();
}}

function fmtDur(sec) {{
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m + ':' + String(s).padStart(2, '0');
}}

function renderTable(data, type) {{
  let html = '<table><thead><tr>';
  html += '<th>#</th><th>썸네일</th><th>제목</th><th>조회수</th><th>좋아요</th><th>참여도</th><th>길이</th>';
  if (type === 'remake') html += '<th>리메이크 점수</th><th>경과일</th>';
  html += '<th>게시일</th></tr></thead><tbody>';

  data.forEach((v, i) => {{
    html += '<tr>';
    html += `<td>${{i+1}}</td>`;
    html += `<td><img class="thumb" src="${{v.thumbnail}}" alt="" loading="lazy"></td>`;
    html += `<td><a href="${{v.url}}" target="_blank">${{v.title}}</a></td>`;
    html += `<td>${{fmtNum(v.viewCount)}}</td>`;
    html += `<td>${{fmtNum(v.likeCount)}}</td>`;
    html += `<td>${{v.engagementRate}}%</td>`;
    html += `<td>${{fmtDur(v.duration)}}</td>`;
    if (type === 'remake') {{
      html += `<td style="color:#fbbf24;font-weight:700">${{v.remakeScore}}</td>`;
      html += `<td>${{v.ageDays}}일</td>`;
    }}
    html += `<td>${{v.publishedAt?.slice(0,10) || ''}}</td>`;
    html += '</tr>';
  }});

  html += '</tbody></table>';
  return html;
}}

function showTable(type) {{
  currentTab = type;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');

  let data;
  switch(type) {{
    case 'views': data = topViews; break;
    case 'engagement': data = topEngagement; break;
    case 'remake': data = remakeCandidates; break;
    case 'all': data = allVideos.sort((a,b) => b.viewCount - a.viewCount); break;
  }}
  document.getElementById('tableContainer').innerHTML = renderTable(data, type);
}}

function filterTable() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  let data;
  switch(currentTab) {{
    case 'views': data = topViews; break;
    case 'engagement': data = topEngagement; break;
    case 'remake': data = remakeCandidates; break;
    case 'all': data = allVideos; break;
  }}
  const filtered = data.filter(v => v.title.toLowerCase().includes(q));
  document.getElementById('tableContainer').innerHTML = renderTable(filtered, currentTab);
}}

// 초기 렌더
showTable('views');

// ─── AI 인사이트 생성 ───
(function() {{
  const bestCat = Object.entries({json.dumps(analysis["categoryStats"], ensure_ascii=False)})
    .sort((a,b) => b[1].avgViews - a[1].avgViews)[0];
  const bestDur = Object.entries({json.dumps(analysis["durationAnalysis"], ensure_ascii=False)})
    .sort((a,b) => b[1].avgViews - a[1].avgViews)[0];
  const bestDay = Object.entries({json.dumps(analysis["dayStats"], ensure_ascii=False)})
    .sort((a,b) => b[1].avgViews - a[1].avgViews)[0];

  const recent = {json.dumps(analysis["recentStats"])};
  const older = {json.dumps(analysis["olderStats"])};
  const trend = recent.avgViews > older.avgViews ? '상승' : '하락';
  const trendPct = older.avgViews > 0 ? Math.abs(Math.round((recent.avgViews - older.avgViews) / older.avgViews * 100)) : 0;

  let text = '';
  text += `<span class="highlight-text">[카테고리]</span> "${{bestCat[0]}}" 카테고리가 평균 ${{fmtNum(bestCat[1].avgViews)}} 조회수로 가장 높은 성과. `;
  text += `<span class="highlight-text">[영상 길이]</span> "${{bestDur[0]}}" 길이가 평균 ${{fmtNum(bestDur[1].avgViews)}} 조회수로 최적 구간. `;
  text += `<span class="highlight-text">[업로드 타이밍]</span> ${{bestDay[0]}}요일 업로드가 평균 ${{fmtNum(bestDay[1].avgViews)}} 조회수로 최고 성과. `;
  text += `<span class="highlight-text">[트렌드]</span> 최근 6개월 평균 조회수 ${{trend}} (${{trendPct}}%). `;
  text += `<span class="highlight-text">[리메이크]</span> 고성과+오래된 영상 ${{remakeCandidates.length}}개 리메이크 후보 발굴.`;

  document.getElementById('insightText').innerHTML = text;
}})();
</script>

</body>
</html>'''

    return html


# ─── 메인 실행 ──────────────────────────────────────────

def main():
    if not API_KEY:
        print("❌ YOUTUBE_API_KEY 환경변수를 설정해주세요.")
        print("   사용법: YOUTUBE_API_KEY=your_key python youtube_analyzer.py")
        sys.exit(1)

    print("🚀 LANstar YouTube 채널 분석 시작...")

    youtube = build("youtube", "v3", developerKey=API_KEY)

    # 1. 채널 ID 조회
    print("\n📡 채널 ID 조회 중...")
    channel_id = get_channel_id(youtube, CHANNEL_HANDLE)
    if not channel_id:
        print("❌ 채널을 찾을 수 없습니다.")
        sys.exit(1)
    print(f"  → 채널 ID: {channel_id}")

    # 2. 전체 영상 ID 수집
    print("\n📋 전체 영상 목록 수집 중...")
    video_ids, channel_info = get_all_video_ids(youtube, channel_id)

    # 3. 영상 상세 정보 조회
    print("\n🎬 영상 상세 정보 수집 중...")
    videos = get_video_details(youtube, video_ids)

    # 4. 분석 수행
    print("\n🔍 성과 분석 수행 중...")
    analysis = analyze_videos(videos, channel_info)

    # 5. JSON 데이터 저장
    json_path = os.path.join(OUTPUT_DIR, "lanstar_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 분석 데이터 저장: {json_path}")

    # 6. HTML 대시보드 생성
    print("\n📊 대시보드 생성 중...")
    html = generate_dashboard(analysis)
    html_path = os.path.join(OUTPUT_DIR, "lanstar_dashboard.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 대시보드 저장: {html_path}")

    # 요약
    print(f"\n{'='*50}")
    print(f"📊 분석 완료!")
    print(f"   총 영상: {analysis['totalVideos']}개")
    print(f"   총 조회수: {analysis['totalViews']:,}")
    print(f"   평균 조회수: {analysis['avgViews']:,}")
    print(f"   평균 참여도: {analysis['avgEngagement']}%")
    print(f"   리메이크 후보: {len(analysis['remakeCandidates'])}개")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
