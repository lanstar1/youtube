"""
Stage 5-A: SEO 최적화 + 썸네일 자동생성 모듈
- YouTube SEO 최적화 (제목/설명/태그)
- 경쟁 키워드 분석
- 썸네일 이미지 생성
"""

import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ANTHROPIC_API_KEY, OUTPUT_DIR


# ─── SEO 최적화 ──────────────────────────────────────────

def optimize_seo(script: dict, channel_data: dict = None) -> dict:
    """
    스크립트 JSON의 SEO 데이터를 검증하고 보강

    Args:
        script: Video Notation Schema JSON
        channel_data: lanstar_data.json (경쟁 키워드 분석용)

    Returns:
        최적화된 SEO 데이터
    """
    seo = script.get("seo", {})
    headline = script.get("headline", {})
    metadata = script.get("metadata", {})
    errors = []

    # 1. 제목 최적화
    title = headline.get("main_title", "")
    if len(title) > 60:
        errors.append(f"⚠️ 제목 길이 초과: {len(title)}자 (60자 이내 권장)")
    if len(title) < 20:
        errors.append(f"⚠️ 제목이 너무 짧음: {len(title)}자 (20자 이상 권장)")

    # 숫자/특수문자 포함 여부 (CTR 향상)
    has_number = bool(re.search(r'\d', title))
    has_special = bool(re.search(r'[?!]', title))
    if not has_number:
        errors.append("💡 제목에 숫자 포함 권장 (CTR +36%)")
    if not has_special:
        errors.append("💡 제목에 물음표/느낌표 권장 (CTR +22%)")

    # 2. 설명문 최적화
    desc = seo.get("description", "")
    if len(desc) < 200:
        errors.append(f"⚠️ 설명문 너무 짧음: {len(desc)}자 (200자 이상 권장)")

    # 타임스탬프 포함 여부
    has_timestamps = bool(re.search(r'\d{1,2}:\d{2}', desc))
    if not has_timestamps:
        # 자동 타임스탬프 생성
        timestamps = generate_timestamps(script)
        if timestamps:
            desc = desc.rstrip() + "\n\n📌 타임스탬프\n" + timestamps
            seo["description"] = desc

    # lanstar.co.kr 링크 포함 여부
    if "lanstar.co.kr" not in desc:
        desc += "\n\n🛒 제품 구매: https://lanstar.co.kr"
        seo["description"] = desc

    # 3. 태그 최적화
    tags = seo.get("tags", [])
    # 필수 태그 확인
    required_tags = ["랜스타", "LANstar", "IT"]
    for rt in required_tags:
        if not any(rt.lower() in t.lower() for t in tags):
            tags.append(rt)

    # 채널 데이터 기반 인기 태그 보강
    if channel_data:
        popular_tags = [t[0] for t in channel_data.get("tagCounts", [])[:20]]
        category = metadata.get("category", "")
        for pt in popular_tags[:5]:
            if pt not in [t.lower() for t in tags]:
                tags.append(pt)

    seo["tags"] = tags[:30]  # YouTube 최대 30개

    # 4. 해시태그 최적화
    hashtags = seo.get("hashtags", [])
    if "#랜스타" not in hashtags:
        hashtags.insert(0, "#랜스타")
    if "#LANstar" not in hashtags:
        hashtags.insert(1, "#LANstar")
    seo["hashtags"] = hashtags[:15]

    # 결과 리포트
    score = calculate_seo_score(headline, seo)

    result = {
        "seo": seo,
        "headline": headline,
        "score": score,
        "issues": errors,
    }

    print(f"📊 SEO 점수: {score}/100")
    for e in errors:
        print(f"  {e}")

    return result


def generate_timestamps(script: dict) -> str:
    """스크립트 scenes에서 타임스탬프 자동 생성"""
    scenes = script.get("scenes", [])
    timestamps = []
    current_sections = {}

    for scene in scenes:
        section = scene.get("section", "")
        start = scene.get("start_time", "")

        if section and section not in current_sections and start:
            section_names = {
                "hook": "인트로",
                "problem": "문제 상황",
                "solution": "해결 방법",
                "product": "제품 소개",
                "cta": "마무리",
            }
            name = section_names.get(section, section)
            timestamps.append(f"{start} {name}")
            current_sections[section] = True

    return "\n".join(timestamps)


def calculate_seo_score(headline: dict, seo: dict) -> int:
    """SEO 점수 계산 (100점 만점)"""
    score = 0

    # 제목 (30점)
    title = headline.get("main_title", "")
    if 20 <= len(title) <= 60:
        score += 10
    if re.search(r'\d', title):
        score += 10
    if re.search(r'[?!]', title):
        score += 5
    if any(kw in title for kw in ["방법", "이유", "비밀", "팁", "추천"]):
        score += 5

    # 설명문 (25점)
    desc = seo.get("description", "")
    if len(desc) >= 200:
        score += 10
    if re.search(r'\d{1,2}:\d{2}', desc):
        score += 10  # 타임스탬프
    if "lanstar.co.kr" in desc:
        score += 5

    # 태그 (25점)
    tags = seo.get("tags", [])
    if len(tags) >= 15:
        score += 15
    elif len(tags) >= 10:
        score += 10
    if any("랜스타" in t for t in tags):
        score += 5
    if any("LANstar" in t for t in tags):
        score += 5

    # 해시태그 (10점)
    hashtags = seo.get("hashtags", [])
    if len(hashtags) >= 3:
        score += 5
    if "#랜스타" in hashtags:
        score += 5

    # 후크 (10점)
    hook = headline.get("hook_line", "")
    if hook and len(hook) > 10:
        score += 5
    clickbait = headline.get("clickbait_score", 0)
    if clickbait >= 7:
        score += 5

    return min(score, 100)


# ─── 썸네일 생성 ─────────────────────────────────────────

def generate_thumbnail_prompt(script: dict) -> str:
    """
    스크립트 썸네일 정보를 기반으로 상세 이미지 프롬프트 생성

    Returns:
        DALL-E/Flux용 이미지 프롬프트
    """
    thumb = script.get("thumbnail", {})
    metadata = script.get("metadata", {})

    base_prompt = thumb.get("image_prompt", "")
    text_overlay = thumb.get("text_overlay", "")
    emotion = thumb.get("emotion", "professional")

    # 썸네일 최적화 프롬프트 보강
    enhanced = f"""{base_prompt}, YouTube thumbnail style, eye-catching composition, \
bold vibrant colors, high contrast, {emotion} mood, \
16:9 aspect ratio, ultra sharp, professional product photography, \
clean background, dramatic lighting, no text, no watermark, 4K quality"""

    return enhanced


def create_thumbnail(
    script: dict,
    image_provider: str = "dalle",
    output_path: str = None,
) -> str:
    """
    썸네일 이미지 생성 (AI)

    Args:
        script: Video Notation JSON
        image_provider: "dalle" 또는 "flux"
        output_path: 저장 경로
    """
    from modules.media_generator import generate_dalle_image, generate_flux_image

    prompt = generate_thumbnail_prompt(script)

    if output_path is None:
        title = script.get("metadata", {}).get("title", "untitled")
        safe = "".join(c for c in title if c.isalnum() or c in " -_")[:30].strip()
        output_path = str(OUTPUT_DIR / f"thumb_{safe}.png")

    if image_provider == "flux":
        return generate_flux_image(prompt, width=1280, height=720, output_path=output_path)
    else:
        return generate_dalle_image(prompt, size="1792x1024", quality="hd", output_path=output_path)


# ─── 경쟁 분석 ──────────────────────────────────────────

def analyze_competition(keyword: str, channel_data: dict = None) -> dict:
    """
    키워드 기반 간단한 경쟁 분석

    Args:
        keyword: 분석할 키워드
        channel_data: lanstar_data.json

    Returns:
        경쟁 분석 결과
    """
    if not channel_data:
        return {"keyword": keyword, "status": "채널 데이터 없음"}

    all_videos = channel_data.get("allVideos", [])

    # 키워드 포함 영상 필터
    matching = [v for v in all_videos if keyword.lower() in v.get("title", "").lower()]

    if not matching:
        return {
            "keyword": keyword,
            "existing_videos": 0,
            "recommendation": "새로운 주제 - 선점 기회!",
        }

    avg_views = sum(v["viewCount"] for v in matching) / len(matching)
    max_views = max(v["viewCount"] for v in matching)
    avg_engagement = sum(v.get("engagementRate", 0) for v in matching) / len(matching)

    return {
        "keyword": keyword,
        "existing_videos": len(matching),
        "avg_views": round(avg_views),
        "max_views": max_views,
        "avg_engagement": round(avg_engagement, 2),
        "top_video": max(matching, key=lambda x: x["viewCount"])["title"],
        "recommendation": "리메이크 적합" if avg_views > 10000 else "보강 필요",
    }


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar SEO 최적화")
    sub = parser.add_subparsers(dest="command")

    opt_p = sub.add_parser("optimize", help="스크립트 SEO 최적화")
    opt_p.add_argument("--script", required=True)
    opt_p.add_argument("--channel-data", default="lanstar_data.json")

    comp_p = sub.add_parser("competition", help="키워드 경쟁 분석")
    comp_p.add_argument("--keyword", required=True)
    comp_p.add_argument("--channel-data", default="lanstar_data.json")

    thumb_p = sub.add_parser("thumbnail", help="썸네일 생성")
    thumb_p.add_argument("--script", required=True)
    thumb_p.add_argument("--provider", choices=["dalle", "flux"], default="dalle")

    args = parser.parse_args()

    if args.command == "optimize":
        with open(args.script) as f:
            script = json.load(f)
        channel_data = None
        if os.path.exists(args.channel_data):
            with open(args.channel_data) as f:
                channel_data = json.load(f)
        optimize_seo(script, channel_data)
    elif args.command == "competition":
        channel_data = None
        if os.path.exists(args.channel_data):
            with open(args.channel_data) as f:
                channel_data = json.load(f)
        result = analyze_competition(args.keyword, channel_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "thumbnail":
        with open(args.script) as f:
            script = json.load(f)
        create_thumbnail(script, args.provider)
    else:
        parser.print_help()
