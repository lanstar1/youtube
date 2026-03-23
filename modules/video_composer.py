"""
Stage 4: Video Composition - JSON2Video API 연동
Video Notation JSON → JSON2Video '비디오 레시피' 변환 → 영상 합성
+ FFmpeg 보조 (인트로/아웃트로, 트랜지션, 워터마크)
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import JSON2VIDEO_API_KEY, OUTPUT_DIR, VIDEO_SETTINGS

J2V_BASE = "https://api.json2video.com/v2"


# ─── JSON2Video API 클라이언트 ────────────────────────────

def create_video_recipe(
    script: dict,
    tts_files: dict = None,
    media_files: dict = None,
) -> dict:
    """
    Video Notation JSON → JSON2Video 레시피 변환

    Args:
        script: Video Notation Schema JSON
        tts_files: TTS 엔진 결과 (scene별 음성 파일)
        media_files: 미디어 생성기 결과 (scene별 이미지/비디오)

    Returns:
        JSON2Video API용 레시피 dict
    """
    scenes = script.get("scenes", [])
    metadata = script.get("metadata", {})

    # JSON2Video 레시피 기본 구조
    recipe = {
        "resolution": VIDEO_SETTINGS["resolution"],
        "quality": "high",
        "scenes": [],
        "settings": {
            "framerate": VIDEO_SETTINGS["fps"],
        },
    }

    for scene in scenes:
        sid = scene.get("scene_id", 0)
        visual = scene.get("visual", {})
        narration = scene.get("narration", {})
        subtitle = scene.get("subtitle", {})
        transition = scene.get("transition", "cut")
        bgm = scene.get("bgm", {})
        duration_str = scene.get("duration", "5초")

        # 초 단위 변환
        duration = _parse_duration(duration_str)

        # 장면 구성
        j2v_scene = {
            "duration": duration,
            "transition": {
                "type": _map_transition(transition),
                "duration": 0.5,
            },
            "elements": [],
        }

        # 1. 배경 미디어 (이미지 또는 비디오)
        media_info = media_files.get("scenes", {}).get(sid, {}) if media_files else {}
        media_file = media_info.get("file")

        if media_file and os.path.exists(media_file):
            if media_file.endswith((".mp4", ".mov", ".avi")):
                j2v_scene["elements"].append({
                    "type": "video",
                    "src": media_file,
                    "start": 0,
                    "duration": duration,
                    "animation": _get_camera_animation(visual.get("camera", {})),
                })
            else:
                j2v_scene["elements"].append({
                    "type": "image",
                    "src": media_file,
                    "start": 0,
                    "duration": duration,
                    "animation": _get_camera_animation(visual.get("camera", {})),
                })
        else:
            # 미디어 파일 없으면 설명 텍스트로 플레이스홀더
            j2v_scene["elements"].append({
                "type": "text",
                "text": visual.get("description", ""),
                "style": {
                    "fontSize": 24,
                    "color": "#FFFFFF",
                    "backgroundColor": "#1a1b2e",
                    "textAlign": "center",
                },
                "start": 0,
                "duration": duration,
            })

        # 2. TTS 오디오
        tts_info = tts_files.get("scenes", {}).get(sid, {}) if tts_files else {}
        tts_file = tts_info.get("file")
        if tts_file and os.path.exists(tts_file):
            j2v_scene["elements"].append({
                "type": "audio",
                "src": tts_file,
                "start": 0,
                "volume": 1.0,
            })

        # 3. 자막
        sub_text = subtitle.get("text") or narration.get("text", "")
        if sub_text:
            emphasis = narration.get("emphasis_words", [])
            sub_style = _get_subtitle_style(subtitle.get("style", "default"))

            j2v_scene["elements"].append({
                "type": "subtitle",
                "text": sub_text,
                "style": sub_style,
                "position": subtitle.get("position", "bottom"),
                "start": 0,
                "duration": duration,
                "highlight_words": emphasis,
            })

        # 4. BGM
        if bgm.get("action") in ("change", "fade-in"):
            j2v_scene["elements"].append({
                "type": "audio",
                "src": f"bgm_{bgm.get('mood', 'neutral')}.mp3",  # BGM 라이브러리 참조
                "volume": bgm.get("volume", 0.15),
                "loop": True,
                "fadeIn": 2 if bgm.get("action") == "fade-in" else 0,
            })

        recipe["scenes"].append(j2v_scene)

    return recipe


def submit_video(recipe: dict) -> str:
    """
    JSON2Video API에 레시피 제출

    Returns:
        project_id (렌더링 추적용)
    """
    if not JSON2VIDEO_API_KEY:
        raise ValueError("JSON2VIDEO_API_KEY 환경변수를 설정해주세요.")

    res = requests.post(
        f"{J2V_BASE}/movies",
        headers={
            "x-api-key": JSON2VIDEO_API_KEY,
            "Content-Type": "application/json",
        },
        json=recipe,
    )
    res.raise_for_status()
    data = res.json()
    project_id = data.get("project", "")
    print(f"📤 영상 렌더링 제출 완료! project_id: {project_id}")
    return project_id


def check_status(project_id: str) -> dict:
    """렌더링 상태 확인"""
    res = requests.get(
        f"{J2V_BASE}/movies",
        headers={"x-api-key": JSON2VIDEO_API_KEY},
        params={"project": project_id},
    )
    res.raise_for_status()
    return res.json()


def wait_and_download(project_id: str, output_path: str = None, timeout: int = 600) -> str:
    """
    렌더링 완료 대기 후 다운로드

    Args:
        project_id: 프로젝트 ID
        output_path: 저장 경로
        timeout: 최대 대기 시간 (초)
    """
    start = time.time()
    while time.time() - start < timeout:
        status = check_status(project_id)
        state = status.get("status", "")

        if state == "done":
            url = status.get("url", "")
            if not url:
                raise ValueError("렌더링 완료 but URL 없음")

            if output_path is None:
                output_path = str(OUTPUT_DIR / f"video_{project_id}.mp4")

            res = requests.get(url, stream=True)
            with open(output_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ 영상 다운로드 완료: {output_path}")
            return output_path

        elif state == "error":
            raise RuntimeError(f"렌더링 실패: {status.get('message', '')}")

        print(f"  ⏳ 렌더링 중... ({state}) {int(time.time()-start)}초 경과")
        time.sleep(10)

    raise TimeoutError(f"렌더링 타임아웃 ({timeout}초)")


# ─── FFmpeg 보조 기능 ─────────────────────────────────────

def add_intro_outro(
    video_path: str,
    intro_path: str = None,
    outro_path: str = None,
    output_path: str = None,
) -> str:
    """인트로/아웃트로 추가 (FFmpeg)"""
    import subprocess

    parts = []
    filter_parts = []
    idx = 0

    if intro_path:
        parts.extend(["-i", intro_path])
        filter_parts.append(f"[{idx}:v:0][{idx}:a:0]")
        idx += 1

    parts.extend(["-i", video_path])
    filter_parts.append(f"[{idx}:v:0][{idx}:a:0]")
    idx += 1

    if outro_path:
        parts.extend(["-i", outro_path])
        filter_parts.append(f"[{idx}:v:0][{idx}:a:0]")
        idx += 1

    if output_path is None:
        output_path = str(OUTPUT_DIR / "video_with_intro_outro.mp4")

    filter_str = "".join(filter_parts) + f"concat=n={idx}:v=1:a=1[outv][outa]"

    cmd = [
        "ffmpeg", "-y",
        *parts,
        "-filter_complex", filter_str,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ 인트로/아웃트로 추가: {output_path}")
    return output_path


def add_watermark(
    video_path: str,
    watermark_path: str,
    position: str = "bottom-right",
    opacity: float = 0.3,
    output_path: str = None,
) -> str:
    """워터마크 추가 (FFmpeg)"""
    import subprocess

    pos_map = {
        "top-left": "10:10",
        "top-right": "main_w-overlay_w-10:10",
        "bottom-left": "10:main_h-overlay_h-10",
        "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    }

    if output_path is None:
        output_path = str(OUTPUT_DIR / "video_watermarked.mp4")

    overlay_pos = pos_map.get(position, pos_map["bottom-right"])
    filter_str = f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];[0:v][wm]overlay={overlay_pos}"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", watermark_path,
        "-filter_complex", filter_str,
        "-c:v", "libx264", "-preset", "medium",
        "-c:a", "copy",
        output_path,
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ 워터마크 추가: {output_path}")
    return output_path


def create_shorts_clip(
    video_path: str,
    start_time: str,
    duration: int = 60,
    output_path: str = None,
) -> str:
    """숏폼 클립 추출 + 9:16 크롭 (FFmpeg)"""
    import subprocess

    if output_path is None:
        output_path = str(OUTPUT_DIR / "shorts_clip.mp4")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", start_time,
        "-t", str(duration),
        "-vf", "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
        "-c:v", "libx264", "-preset", "medium",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ 숏폼 클립 생성: {output_path}")
    return output_path


# ─── 유틸리티 ────────────────────────────────────────────

def _parse_duration(duration_str: str) -> float:
    """'5초', '1분 30초', '2:30' 형태를 초 단위로 변환"""
    import re
    # "5초" 형태
    m = re.match(r'(\d+)\s*초', duration_str)
    if m:
        return float(m.group(1))
    # "1분 30초" 형태
    m = re.match(r'(\d+)\s*분\s*(\d+)?\s*초?', duration_str)
    if m:
        mins = int(m.group(1))
        secs = int(m.group(2) or 0)
        return mins * 60 + secs
    # "2:30" 형태
    m = re.match(r'(\d+):(\d+)', duration_str)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # 숫자만
    m = re.match(r'(\d+\.?\d*)', duration_str)
    if m:
        return float(m.group(1))
    return 5.0  # 기본값


def _map_transition(transition: str) -> str:
    """Video Notation 트랜지션 → JSON2Video 트랜지션 매핑"""
    mapping = {
        "cut": "cut",
        "fade": "fade",
        "dissolve": "crossfade",
        "slide-left": "slideLeft",
        "slide-right": "slideRight",
        "zoom": "zoomIn",
        "none": "none",
    }
    return mapping.get(transition, "cut")


def _get_camera_animation(camera: dict) -> dict:
    """카메라 노테이션 → JSON2Video 애니메이션"""
    movement = camera.get("movement", "static")
    animation_map = {
        "static": {"type": "none"},
        "zoom-in": {"type": "zoomIn", "easing": "easeInOut"},
        "zoom-out": {"type": "zoomOut", "easing": "easeInOut"},
        "pan-left": {"type": "panLeft", "easing": "linear"},
        "pan-right": {"type": "panRight", "easing": "linear"},
        "tilt-up": {"type": "panUp", "easing": "linear"},
        "tilt-down": {"type": "panDown", "easing": "linear"},
        "dolly": {"type": "zoomIn", "easing": "easeInOut"},
        "tracking": {"type": "panRight", "easing": "linear"},
    }
    return animation_map.get(movement, {"type": "kenBurns"})  # 기본: Ken Burns 효과


def _get_subtitle_style(style: str) -> dict:
    """자막 스타일 매핑"""
    styles = {
        "default": {
            "fontSize": 36,
            "fontFamily": "NanumGothicBold",
            "color": "#FFFFFF",
            "backgroundColor": "rgba(0,0,0,0.6)",
            "padding": "8px 16px",
            "borderRadius": "8px",
        },
        "highlight": {
            "fontSize": 42,
            "fontFamily": "NanumGothicExtraBold",
            "color": "#FFD700",
            "backgroundColor": "rgba(0,0,0,0.8)",
            "padding": "10px 20px",
            "borderRadius": "8px",
        },
        "large": {
            "fontSize": 56,
            "fontFamily": "NanumGothicExtraBold",
            "color": "#FFFFFF",
            "textShadow": "2px 2px 4px rgba(0,0,0,0.8)",
        },
        "animated": {
            "fontSize": 40,
            "fontFamily": "NanumGothicBold",
            "color": "#FFFFFF",
            "animation": "fadeIn",
        },
    }
    return styles.get(style, styles["default"])


# ─── 전체 파이프라인 ──────────────────────────────────────

def compose_video(
    script: dict,
    tts_result: dict = None,
    media_result: dict = None,
    use_json2video: bool = True,
    output_path: str = None,
) -> str:
    """
    최종 영상 합성 통합 함수

    Args:
        script: Video Notation JSON
        tts_result: TTS 엔진 결과
        media_result: 미디어 생성기 결과
        use_json2video: True=JSON2Video API, False=FFmpeg only
        output_path: 출력 경로
    """
    print("🎬 영상 합성 시작...")

    # 1. JSON2Video 레시피 생성
    recipe = create_video_recipe(script, tts_result, media_result)

    # 레시피 저장 (디버깅/재사용용)
    recipe_path = OUTPUT_DIR / "last_recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    print(f"  📋 레시피 저장: {recipe_path}")

    if use_json2video and JSON2VIDEO_API_KEY:
        # 2. JSON2Video 제출
        project_id = submit_video(recipe)

        # 3. 완료 대기 및 다운로드
        video_path = wait_and_download(project_id, output_path)
        return video_path
    else:
        print("  ℹ️ JSON2Video API 키 없음 - 레시피만 저장됨")
        print(f"  📋 나중에 API 키 설정 후 수동 제출 가능")
        return str(recipe_path)


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar 영상 합성기")
    parser.add_argument("--script", required=True, help="스크립트 JSON 경로")
    parser.add_argument("--tts-dir", help="TTS 결과 디렉토리")
    parser.add_argument("--media-dir", help="미디어 결과 디렉토리")
    parser.add_argument("--no-j2v", action="store_true", help="JSON2Video 사용 안함")
    parser.add_argument("--output", help="출력 경로")

    args = parser.parse_args()

    with open(args.script) as f:
        script = json.load(f)

    compose_video(
        script,
        use_json2video=not args.no_j2v,
        output_path=args.output,
    )
