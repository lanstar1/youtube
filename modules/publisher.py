"""
Stage 5-B: YouTube 업로드 + 숏폼 리퍼포징 모듈
- YouTube Data API v3 업로드 (OAuth2 인증)
- 예약 업로드 지원
- 숏폼 (Shorts/Reels) 자동 추출 + 업로드
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import YOUTUBE_API_KEY, OUTPUT_DIR

# Google OAuth2 (업로드용 - API 키로는 업로드 불가)
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]
TOKEN_FILE = str(OUTPUT_DIR / ".youtube_token.json")
CLIENT_SECRET_FILE = str(OUTPUT_DIR / "client_secret.json")


# ─── OAuth2 인증 ─────────────────────────────────────────

def get_authenticated_service():
    """YouTube API OAuth2 인증 서비스 생성"""
    if not GOOGLE_AUTH_AVAILABLE:
        raise ImportError(
            "google-auth-oauthlib 패키지 필요: "
            "pip install google-auth-oauthlib google-api-python-client"
        )

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if not os.path.exists(CLIENT_SECRET_FILE):
            raise FileNotFoundError(
                f"OAuth2 클라이언트 시크릿 파일이 필요합니다: {CLIENT_SECRET_FILE}\n"
                "Google Cloud Console → 사용자 인증 정보 → OAuth 2.0 클라이언트 ID 생성 후 다운로드"
            )
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ─── YouTube 업로드 ──────────────────────────────────────

def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    category_id: str = "28",  # 28 = Science & Technology
    privacy: str = "private",  # private → 검토 후 public 전환
    scheduled_time: str = None,  # ISO 8601 (예약 업로드)
    thumbnail_path: str = None,
    playlist_id: str = None,
) -> dict:
    """
    YouTube 영상 업로드

    Args:
        video_path: 영상 파일 경로
        title: 영상 제목
        description: 설명문
        tags: 태그 리스트
        category_id: YouTube 카테고리 (28=과학기술)
        privacy: public/unlisted/private
        scheduled_time: 예약 시간 (ISO 8601)
        thumbnail_path: 썸네일 이미지 경로
        playlist_id: 추가할 재생목록 ID

    Returns:
        업로드 결과 (video_id, url 등)
    """
    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # 예약 업로드
    if scheduled_time and privacy == "private":
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = scheduled_time

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB 청크
    )

    print(f"📤 업로드 시작: {title}")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  ⏳ 업로드 진행: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"✅ 업로드 완료! ID: {video_id}")
    print(f"   URL: https://www.youtube.com/watch?v={video_id}")

    # 썸네일 설정
    if thumbnail_path and os.path.exists(thumbnail_path):
        set_thumbnail(youtube, video_id, thumbnail_path)

    # 재생목록 추가
    if playlist_id:
        add_to_playlist(youtube, video_id, playlist_id)

    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "privacy": privacy,
        "scheduled": scheduled_time,
    }


def set_thumbnail(youtube, video_id: str, thumbnail_path: str):
    """커스텀 썸네일 설정"""
    media = MediaFileUpload(thumbnail_path, mimetype="image/png")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"  🖼️ 썸네일 설정 완료")


def add_to_playlist(youtube, video_id: str, playlist_id: str):
    """재생목록에 추가"""
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()
    print(f"  📂 재생목록 추가 완료")


# ─── 스크립트 기반 업로드 ─────────────────────────────────

def upload_from_script(
    script: dict,
    video_path: str,
    thumbnail_path: str = None,
    privacy: str = "private",
    scheduled_time: str = None,
) -> dict:
    """
    Video Notation JSON의 SEO 데이터를 활용해 업로드

    Args:
        script: Video Notation Schema JSON
        video_path: 완성된 영상 경로
        thumbnail_path: 썸네일 경로
        privacy: 공개 설정
        scheduled_time: 예약 시간
    """
    headline = script.get("headline", {})
    seo = script.get("seo", {})

    title = headline.get("main_title", "LANstar 영상")
    description = seo.get("description", "")
    tags = seo.get("tags", [])

    # 해시태그를 설명문 상단에 추가
    hashtags = seo.get("hashtags", [])
    if hashtags:
        description = " ".join(hashtags[:3]) + "\n\n" + description

    return upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        privacy=privacy,
        scheduled_time=scheduled_time,
        thumbnail_path=thumbnail_path,
    )


# ─── 숏폼 리퍼포징 ──────────────────────────────────────

def extract_shorts_clips(
    script: dict,
    video_path: str,
    output_dir: str = None,
) -> list:
    """
    Video Notation의 shorts_repurpose 데이터 기반 숏폼 클립 추출

    Args:
        script: Video Notation JSON
        video_path: 원본 롱폼 영상
        output_dir: 숏폼 저장 디렉토리

    Returns:
        추출된 숏폼 파일 경로 리스트
    """
    from modules.video_composer import create_shorts_clip

    shorts_data = script.get("shorts_repurpose", {})
    clips = shorts_data.get("recommended_clips", [])

    if not clips:
        print("ℹ️ 숏폼 클립 추천 데이터가 없습니다.")
        # scenes에서 자동 추출 시도
        clips = auto_detect_shorts_segments(script)

    if output_dir is None:
        output_dir = str(OUTPUT_DIR / "shorts")
    os.makedirs(output_dir, exist_ok=True)

    results = []
    scenes = script.get("scenes", [])

    for i, clip in enumerate(clips):
        scene_ids = clip.get("scene_ids", [])
        hook = clip.get("hook_text", "")
        score = clip.get("virality_score", 5)

        if score < 7:
            print(f"  ⏭️ Clip {i+1}: virality score {score} < 7, 건너뜀")
            continue

        # scene_ids로 시간 범위 계산
        start_time = "0:00"
        duration = 60

        if scene_ids and scenes:
            target_scenes = [s for s in scenes if s.get("scene_id") in scene_ids]
            if target_scenes:
                start_time = target_scenes[0].get("start_time", "0:00")
                total_dur = sum(
                    _parse_seconds(s.get("duration", "5초"))
                    for s in target_scenes
                )
                duration = min(int(total_dur), 60)

        output_path = os.path.join(output_dir, f"short_{i+1:02d}.mp4")

        try:
            create_shorts_clip(video_path, start_time, duration, output_path)
            results.append({
                "file": output_path,
                "hook": hook,
                "score": score,
                "duration": duration,
            })
        except Exception as e:
            print(f"  ❌ Clip {i+1} 추출 실패: {e}")

    print(f"\n✅ 숏폼 {len(results)}개 추출 완료")
    return results


def auto_detect_shorts_segments(script: dict) -> list:
    """스크립트에서 바이럴 잠재력 높은 구간 자동 감지"""
    scenes = script.get("scenes", [])
    candidates = []

    for scene in scenes:
        section = scene.get("section", "")
        narration = scene.get("narration", {})
        text = narration.get("text", "")

        # hook과 problem 섹션은 바이럴 잠재력 높음
        if section in ("hook", "problem"):
            candidates.append({
                "scene_ids": [scene.get("scene_id", 0)],
                "hook_text": text[:50] if text else "",
                "virality_score": 8 if section == "hook" else 7,
            })

        # 강조 단어가 3개 이상인 장면
        emphasis = narration.get("emphasis_words", [])
        if len(emphasis) >= 3:
            candidates.append({
                "scene_ids": [scene.get("scene_id", 0)],
                "hook_text": text[:50] if text else "",
                "virality_score": 7,
            })

    return candidates[:3]  # 최대 3개


def _parse_seconds(duration_str: str) -> float:
    """간단한 초 파싱"""
    import re
    m = re.match(r'(\d+)', duration_str)
    return float(m.group(1)) if m else 5.0


# ─── 업로드 스케줄러 ─────────────────────────────────────

def create_upload_schedule(
    scripts: list,
    start_date: str = None,
    uploads_per_week: int = 3,
    preferred_days: list = None,
    preferred_time: str = "18:00",
) -> list:
    """
    주간 업로드 스케줄 생성

    Args:
        scripts: 스크립트 리스트
        start_date: 시작일 (YYYY-MM-DD)
        uploads_per_week: 주당 업로드 횟수
        preferred_days: 선호 요일 (0=월~6=일)
        preferred_time: 업로드 시간 (HH:MM)

    Returns:
        스케줄 리스트 [{script, scheduled_time, ...}]
    """
    if preferred_days is None:
        preferred_days = [1, 3, 5]  # 화, 목, 토

    if start_date:
        current = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        current = datetime.now() + timedelta(days=1)

    hour, minute = map(int, preferred_time.split(":"))
    schedule = []

    for script in scripts:
        # 다음 선호 요일 찾기
        while current.weekday() not in preferred_days:
            current += timedelta(days=1)

        scheduled = current.replace(hour=hour, minute=minute, second=0)
        iso_time = scheduled.strftime("%Y-%m-%dT%H:%M:%S+09:00")  # KST

        schedule.append({
            "title": script.get("headline", {}).get("main_title", ""),
            "scheduled_time": iso_time,
            "day_of_week": ["월", "화", "수", "목", "금", "토", "일"][current.weekday()],
            "script_file": script.get("_file_path", ""),
        })

        current += timedelta(days=1)

    return schedule


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar YouTube 퍼블리셔")
    sub = parser.add_subparsers(dest="command")

    upload_p = sub.add_parser("upload", help="영상 업로드")
    upload_p.add_argument("--script", required=True)
    upload_p.add_argument("--video", required=True)
    upload_p.add_argument("--thumbnail", default=None)
    upload_p.add_argument("--privacy", default="private")
    upload_p.add_argument("--schedule-time", default=None)

    shorts_p = sub.add_parser("shorts", help="숏폼 추출")
    shorts_p.add_argument("--script", required=True)
    shorts_p.add_argument("--video", required=True)

    schedule_p = sub.add_parser("schedule", help="업로드 스케줄 생성")
    schedule_p.add_argument("--scripts-dir", required=True)
    schedule_p.add_argument("--per-week", type=int, default=3)

    args = parser.parse_args()

    if args.command == "upload":
        with open(args.script) as f:
            script = json.load(f)
        upload_from_script(script, args.video, args.thumbnail, args.privacy, args.schedule_time)
    elif args.command == "shorts":
        with open(args.script) as f:
            script = json.load(f)
        extract_shorts_clips(script, args.video)
    elif args.command == "schedule":
        # 디렉토리에서 스크립트 로드
        scripts = []
        for f in sorted(os.listdir(args.scripts_dir)):
            if f.endswith(".json"):
                with open(os.path.join(args.scripts_dir, f)) as fh:
                    scripts.append(json.load(fh))
        schedule = create_upload_schedule(scripts, uploads_per_week=args.per_week)
        for s in schedule:
            print(f"  {s['day_of_week']} {s['scheduled_time'][:16]} - {s['title'][:50]}")
    else:
        parser.print_help()
