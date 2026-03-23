"""
Stage 3-B: 미디어 소스 생성 모듈
- AI 이미지: OpenAI DALL-E 3 / Flux (fal.ai)
- 스톡 영상/이미지: Pexels API
- 각 scene의 visual 타입에 따라 자동 분배
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, PEXELS_API_KEY, OUTPUT_DIR


# ─── AI 이미지 생성 (DALL-E 3) ───────────────────────────

def generate_dalle_image(
    prompt: str,
    size: str = "1792x1024",  # 16:9에 가장 가까운 옵션
    quality: str = "standard",
    style: str = "natural",
    output_path: str = None,
) -> str:
    """
    DALL-E 3로 AI 이미지 생성

    Args:
        prompt: 이미지 프롬프트 (영어)
        size: 1024x1024, 1024x1792, 1792x1024
        quality: standard / hd
        style: natural / vivid
        output_path: 저장 경로
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY 환경변수를 설정해주세요.")

    # 브랜드 톤 접미사 자동 추가
    brand_suffix = ", professional product photography, clean modern tech aesthetic, no human faces, studio lighting"
    enhanced_prompt = prompt.rstrip(".") + brand_suffix

    res = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "dall-e-3",
            "prompt": enhanced_prompt,
            "n": 1,
            "size": size,
            "quality": quality,
            "style": style,
        },
    )
    res.raise_for_status()
    image_url = res.json()["data"][0]["url"]

    # 이미지 다운로드
    if output_path is None:
        output_path = str(OUTPUT_DIR / f"dalle_{int(time.time())}.png")

    img_data = requests.get(image_url).content
    with open(output_path, "wb") as f:
        f.write(img_data)

    return output_path


# ─── AI 이미지 생성 (Flux via fal.ai) ────────────────────

def generate_flux_image(
    prompt: str,
    width: int = 1920,
    height: int = 1080,
    output_path: str = None,
    fal_key: str = None,
) -> str:
    """
    Flux (fal.ai) 이미지 생성 - DALL-E 대체/보완

    Args:
        prompt: 이미지 프롬프트 (영어)
        width, height: 해상도
        output_path: 저장 경로
        fal_key: fal.ai API 키
    """
    fal_key = fal_key or os.environ.get("FAL_KEY", "")
    if not fal_key:
        raise ValueError("FAL_KEY 환경변수를 설정해주세요.")

    brand_suffix = ", professional product photography, clean modern tech aesthetic, no human faces, studio lighting, 8k"
    enhanced_prompt = prompt.rstrip(".") + brand_suffix

    res = requests.post(
        "https://queue.fal.run/fal-ai/flux/dev",
        headers={
            "Authorization": f"Key {fal_key}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": enhanced_prompt,
            "image_size": {"width": width, "height": height},
            "num_images": 1,
            "enable_safety_checker": True,
        },
    )
    res.raise_for_status()

    # fal.ai는 비동기 큐 → 결과 폴링
    request_id = res.json().get("request_id")
    if request_id:
        # 상태 폴링
        for _ in range(60):
            status_res = requests.get(
                f"https://queue.fal.run/fal-ai/flux/dev/requests/{request_id}/status",
                headers={"Authorization": f"Key {fal_key}"},
            )
            status = status_res.json()
            if status.get("status") == "COMPLETED":
                result_res = requests.get(
                    f"https://queue.fal.run/fal-ai/flux/dev/requests/{request_id}",
                    headers={"Authorization": f"Key {fal_key}"},
                )
                image_url = result_res.json()["images"][0]["url"]
                break
            time.sleep(2)
        else:
            raise TimeoutError("Flux 이미지 생성 시간 초과")
    else:
        image_url = res.json()["images"][0]["url"]

    if output_path is None:
        output_path = str(OUTPUT_DIR / f"flux_{int(time.time())}.png")

    img_data = requests.get(image_url).content
    with open(output_path, "wb") as f:
        f.write(img_data)

    return output_path


# ─── 스톡 미디어 (Pexels) ────────────────────────────────

def search_pexels_videos(
    query: str,
    per_page: int = 5,
    orientation: str = "landscape",
    min_duration: int = 5,
    max_duration: int = 30,
) -> list:
    """
    Pexels에서 스톡 비디오 검색

    Returns:
        [{url, width, height, duration, video_files: [...]}]
    """
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY 환경변수를 설정해주세요.")

    res = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={
            "query": query,
            "per_page": per_page,
            "orientation": orientation,
            "size": "medium",
        },
    )
    res.raise_for_status()
    videos = res.json().get("videos", [])

    results = []
    for v in videos:
        if min_duration <= v.get("duration", 0) <= max_duration:
            # HD 파일 선택
            hd_file = None
            for vf in v.get("video_files", []):
                if vf.get("height", 0) >= 720:
                    hd_file = vf
                    break
            if not hd_file and v.get("video_files"):
                hd_file = v["video_files"][0]

            results.append({
                "id": v["id"],
                "url": v.get("url"),
                "duration": v.get("duration"),
                "width": hd_file.get("width") if hd_file else 0,
                "height": hd_file.get("height") if hd_file else 0,
                "download_url": hd_file.get("link") if hd_file else None,
            })

    return results


def search_pexels_images(
    query: str,
    per_page: int = 5,
    orientation: str = "landscape",
) -> list:
    """Pexels에서 스톡 이미지 검색"""
    if not PEXELS_API_KEY:
        raise ValueError("PEXELS_API_KEY 환경변수를 설정해주세요.")

    res = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={
            "query": query,
            "per_page": per_page,
            "orientation": orientation,
        },
    )
    res.raise_for_status()
    photos = res.json().get("photos", [])

    return [{
        "id": p["id"],
        "url": p.get("url"),
        "width": p.get("width"),
        "height": p.get("height"),
        "download_url": p["src"].get("large2x") or p["src"].get("original"),
        "photographer": p.get("photographer"),
    } for p in photos]


def download_media(url: str, output_path: str) -> str:
    """미디어 파일 다운로드"""
    res = requests.get(url, stream=True)
    res.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path


# ─── 배치 생성 (스크립트 전체) ─────────────────────────────

def generate_from_script(
    script: dict,
    output_dir: str = None,
    image_provider: str = "dalle",  # "dalle" | "flux"
) -> dict:
    """
    Video Notation JSON의 모든 scene visual을 생성/수집

    Args:
        script: Video Notation Schema JSON
        output_dir: 출력 디렉토리
        image_provider: AI 이미지 제공자

    Returns:
        scene별 미디어 파일 경로 매핑
    """
    scenes = script.get("scenes", [])
    if not scenes:
        raise ValueError("스크립트에 scenes가 없습니다.")

    if output_dir is None:
        title = script.get("metadata", {}).get("title", "untitled")
        safe = "".join(c for c in title if c.isalnum() or c in " -_")[:30].strip()
        output_dir = str(OUTPUT_DIR / f"media_{safe}")

    os.makedirs(output_dir, exist_ok=True)
    results = {"files": [], "scenes": {}, "errors": []}

    for scene in scenes:
        sid = scene.get("scene_id", 0)
        visual = scene.get("visual", {})
        vtype = visual.get("type", "")

        print(f"  🎨 Scene {sid} ({vtype})...")

        try:
            if vtype == "ai_image":
                prompt = visual.get("image_prompt", visual.get("description", ""))
                if not prompt:
                    results["errors"].append(f"Scene {sid}: image_prompt 없음")
                    continue

                path = os.path.join(output_dir, f"scene_{sid:02d}_ai.png")
                if image_provider == "flux":
                    generate_flux_image(prompt, output_path=path)
                else:
                    generate_dalle_image(prompt, output_path=path)
                results["files"].append(path)
                results["scenes"][sid] = {"file": path, "type": "ai_image"}

            elif vtype in ("stock_video", "stock_image"):
                query = visual.get("stock_query", visual.get("description", ""))
                if not query:
                    continue

                if vtype == "stock_video":
                    items = search_pexels_videos(query, per_page=1)
                else:
                    items = search_pexels_images(query, per_page=1)

                if items and items[0].get("download_url"):
                    ext = "mp4" if vtype == "stock_video" else "jpg"
                    path = os.path.join(output_dir, f"scene_{sid:02d}_stock.{ext}")
                    download_media(items[0]["download_url"], path)
                    results["files"].append(path)
                    results["scenes"][sid] = {"file": path, "type": vtype, "source": "pexels"}

            elif vtype == "product_shot":
                # 제품 사진은 AI로 생성하거나 기존 에셋 사용
                prompt = visual.get("image_prompt", f"product photo of {visual.get('description', 'tech product')}")
                path = os.path.join(output_dir, f"scene_{sid:02d}_product.png")
                if image_provider == "flux":
                    generate_flux_image(prompt, output_path=path)
                else:
                    generate_dalle_image(prompt, output_path=path)
                results["files"].append(path)
                results["scenes"][sid] = {"file": path, "type": "product_shot"}

            elif vtype == "text_overlay":
                # 텍스트 오버레이는 영상 합성 단계에서 처리
                results["scenes"][sid] = {"type": "text_overlay", "text": visual.get("description", "")}

            elif vtype == "existing_footage":
                # 기존 영상 재활용 - 나중에 다운로드/추출
                results["scenes"][sid] = {
                    "type": "existing_footage",
                    "video_id": visual.get("existing_video_id", ""),
                    "timestamp": visual.get("existing_timestamp", ""),
                }

            time.sleep(1)  # API rate limit 대응

        except Exception as e:
            print(f"  ❌ Scene {sid} 실패: {e}")
            results["errors"].append(f"Scene {sid}: {str(e)}")

    print(f"\n✅ 미디어 생성 완료! {len(results['files'])}개 파일, {len(results['errors'])}개 오류")
    return results


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar 미디어 생성기")
    sub = parser.add_subparsers(dest="command")

    # search 명령
    search_p = sub.add_parser("search", help="Pexels 검색")
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--type", choices=["video", "image"], default="video")

    # generate 명령
    gen_p = sub.add_parser("generate", help="스크립트 미디어 생성")
    gen_p.add_argument("--script", required=True, help="스크립트 JSON 경로")
    gen_p.add_argument("--provider", choices=["dalle", "flux"], default="dalle")

    # dalle 명령
    dalle_p = sub.add_parser("dalle", help="DALL-E 단일 이미지")
    dalle_p.add_argument("--prompt", required=True)
    dalle_p.add_argument("--output", default=None)

    args = parser.parse_args()

    if args.command == "search":
        if args.type == "video":
            results = search_pexels_videos(args.query)
        else:
            results = search_pexels_images(args.query)
        for r in results:
            print(json.dumps(r, indent=2))
    elif args.command == "generate":
        with open(args.script) as f:
            script = json.load(f)
        generate_from_script(script, image_provider=args.provider)
    elif args.command == "dalle":
        path = generate_dalle_image(args.prompt, output_path=args.output)
        print(f"✅ 이미지 저장: {path}")
    else:
        parser.print_help()
