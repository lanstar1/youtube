"""
Stage 4: Video Composition
- 기본: FFmpeg 로컬 합성 (이미지 + TTS → 영상)
- 선택: JSON2Video API (원격 렌더링, URL 기반 에셋 필요)
- FFmpeg 보조: 인트로/아웃트로, 워터마크, 숏폼 크롭
"""

import os
import sys
import json
import time
import subprocess
import requests
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import JSON2VIDEO_API_KEY, OUTPUT_DIR, VIDEO_SETTINGS

J2V_BASE = "https://api.json2video.com/v2"


# ═══════════════════════════════════════════════════════════
# FFmpeg 로컬 영상 합성 (PRIMARY)
# ═══════════════════════════════════════════════════════════

def compose_with_ffmpeg(
    script: dict,
    tts_result: dict = None,
    media_result: dict = None,
    output_path: str = None,
) -> str:
    """
    FFmpeg를 이용한 로컬 영상 합성

    각 scene의 이미지 + TTS 오디오를 합쳐 영상 클립을 만들고,
    모든 클립을 이어붙여 최종 MP4를 생성합니다.

    Args:
        script: Video Notation Schema JSON
        tts_result: TTS 결과 {"scenes": {scene_id: {"file": path}}}
        media_result: 미디어 결과 {"scenes": {scene_id: {"file": path}}}
        output_path: 최종 영상 출력 경로

    Returns:
        최종 영상 파일 경로
    """
    scenes = script.get("scenes", [])
    metadata = script.get("metadata", {})
    title = metadata.get("title", "untitled")
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:30].strip()

    # 작업 디렉토리
    work_dir = OUTPUT_DIR / f"compose_{safe_title}"
    work_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = str(OUTPUT_DIR / f"final_{safe_title}.mp4")

    scene_clips = []
    concat_list_path = work_dir / "concat_list.txt"

    print(f"🎬 FFmpeg 로컬 합성 시작 ({len(scenes)}개 장면)")

    for scene in scenes:
        sid = scene.get("scene_id", 0)
        narration = scene.get("narration", {})
        subtitle_data = scene.get("subtitle", {})
        duration_str = scene.get("duration", "5초")
        duration = _parse_duration(duration_str)

        # 미디어 파일 (이미지/비디오)
        media_info = media_result.get("scenes", {}).get(sid, {}) if media_result else {}
        media_file = media_info.get("file")

        # TTS 오디오
        tts_info = tts_result.get("scenes", {}).get(sid, {}) if tts_result else {}
        tts_file = tts_info.get("file")

        clip_path = str(work_dir / f"clip_{sid:03d}.mp4")

        print(f"  🔨 Scene {sid}: media={'✓' if media_file and os.path.exists(str(media_file)) else '✗'}, "
              f"tts={'✓' if tts_file and os.path.exists(str(tts_file)) else '✗'}")

        try:
            if media_file and os.path.exists(str(media_file)):
                media_file = str(media_file)

                if tts_file and os.path.exists(str(tts_file)):
                    tts_file = str(tts_file)
                    # 이미지 + 오디오 → 비디오 (오디오 길이만큼)
                    if media_file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        _create_clip_image_audio(media_file, tts_file, clip_path, scene, duration)
                    else:
                        # 비디오 소스 + 오디오
                        _create_clip_video_audio(media_file, tts_file, clip_path, duration)
                else:
                    # 이미지만 (오디오 없음) → 정적 영상
                    if media_file.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        _create_clip_image_only(media_file, clip_path, duration)
                    else:
                        _create_clip_video_only(media_file, clip_path, duration)
            elif tts_file and os.path.exists(str(tts_file)):
                tts_file = str(tts_file)
                # 오디오만 (미디어 없음) → 검은 배경 + 자막
                sub_text = subtitle_data.get("text") or narration.get("text", "")
                _create_clip_audio_only(tts_file, clip_path, sub_text, duration)
            else:
                # 아무것도 없음 → 스킵
                print(f"  ⚠️ Scene {sid}: 미디어/오디오 없음 - 건너뜀")
                continue

            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                scene_clips.append(clip_path)
            else:
                print(f"  ⚠️ Scene {sid}: 클립 생성 실패")

        except subprocess.CalledProcessError as e:
            print(f"  ❌ Scene {sid} FFmpeg 오류: {e.stderr.decode() if e.stderr else str(e)}")
        except Exception as e:
            print(f"  ❌ Scene {sid} 오류: {e}")

    if not scene_clips:
        raise RuntimeError("합성 가능한 장면이 없습니다.")

    # 모든 클립 concat
    print(f"\n📎 {len(scene_clips)}개 클립 결합 중...")
    with open(concat_list_path, "w") as f:
        for clip in scene_clips:
            f.write(f"file '{clip}'\n")

    # 전체 연결 + 최종 인코딩
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        print(f"  ❌ Concat 오류: {result.stderr.decode()[:500]}")
        raise RuntimeError(f"FFmpeg concat 실패: {result.stderr.decode()[:300]}")

    file_size = os.path.getsize(output_path)
    print(f"\n✅ 최종 영상 생성 완료!")
    print(f"  📁 경로: {output_path}")
    print(f"  📊 크기: {file_size / 1024 / 1024:.1f} MB")

    return output_path


def _create_clip_image_audio(image_path: str, audio_path: str, output_path: str,
                             scene: dict, fallback_duration: float):
    """이미지 + 오디오 → 비디오 클립 (Ken Burns 효과 포함)"""
    # 오디오 길이 측정
    audio_dur = _get_audio_duration(audio_path)
    if audio_dur <= 0:
        audio_dur = fallback_duration

    # Ken Burns (줌인) 효과 - 자연스러운 움직임
    camera = scene.get("visual", {}).get("camera", {})
    movement = camera.get("movement", "zoom-in")
    zoom_filter = _get_ffmpeg_zoom_filter(movement, audio_dur)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-i", audio_path,
        "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,"
               f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,"
               f"{zoom_filter}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-t", str(audio_dur + 0.5),  # 약간의 여유
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True, timeout=120)


def _create_clip_image_only(image_path: str, output_path: str, duration: float):
    """이미지만 → 정적 비디오 (무음)"""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


def _create_clip_video_audio(video_path: str, audio_path: str, output_path: str,
                              duration: float):
    """비디오 소스 + TTS 오디오 → 클립"""
    audio_dur = _get_audio_duration(audio_path)
    if audio_dur <= 0:
        audio_dur = duration

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-t", str(audio_dur + 0.5),
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True, timeout=120)


def _create_clip_video_only(video_path: str, output_path: str, duration: float):
    """비디오만 (오디오는 원본 유지)"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


def _create_clip_audio_only(audio_path: str, output_path: str,
                             subtitle_text: str, duration: float):
    """오디오만 → 검은 배경 + 텍스트 오버레이"""
    audio_dur = _get_audio_duration(audio_path)
    if audio_dur <= 0:
        audio_dur = duration

    # 자막 텍스트 이스케이프
    safe_text = subtitle_text.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
    if len(safe_text) > 80:
        # 줄바꿈 삽입
        mid = len(safe_text) // 2
        space_idx = safe_text.find(" ", mid)
        if space_idx > 0:
            safe_text = safe_text[:space_idx] + "\\n" + safe_text[space_idx+1:]

    vf = (f"scale=1920:1080,"
          f"drawtext=text='{safe_text}':"
          f"fontsize=42:fontcolor=white:"
          f"x=(w-text_w)/2:y=(h-text_h)/2:"
          f"borderw=3:bordercolor=black")

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x1a1b2e:s=1920x1080:d={audio_dur + 0.5}:r=30",
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True, timeout=60)


def _get_audio_duration(audio_path: str) -> float:
    """ffprobe로 오디오 길이 측정"""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _get_ffmpeg_zoom_filter(movement: str, duration: float) -> str:
    """카메라 움직임 → FFmpeg zoompan 필터"""
    frames = int(duration * 30)  # 30fps

    if movement in ("zoom-in", "dolly"):
        # 1.0 → 1.15 줌인
        return (f"zoompan=z='min(zoom+0.0005,1.15)':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s=1920x1080:fps=30")
    elif movement == "zoom-out":
        return (f"zoompan=z='if(eq(on,1),1.15,max(zoom-0.0005,1.0))':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s=1920x1080:fps=30")
    elif movement == "pan-left":
        return (f"zoompan=z='1.1':"
                f"x='iw/2-(iw/zoom/2)-on*2':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s=1920x1080:fps=30")
    elif movement == "pan-right":
        return (f"zoompan=z='1.1':"
                f"x='iw/2-(iw/zoom/2)+on*2':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s=1920x1080:fps=30")
    else:
        # 기본: 약한 줌인 (Ken Burns)
        return (f"zoompan=z='min(zoom+0.0003,1.08)':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s=1920x1080:fps=30")


# ═══════════════════════════════════════════════════════════
# JSON2Video API (OPTIONAL - URL 기반 에셋 필요)
# ═══════════════════════════════════════════════════════════

def create_video_recipe(
    script: dict,
    tts_files: dict = None,
    media_files: dict = None,
) -> dict:
    """
    Video Notation JSON → JSON2Video 레시피 변환
    """
    scenes = script.get("scenes", [])
    metadata = script.get("metadata", {})

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
        duration = _parse_duration(duration_str)

        j2v_scene = {
            "duration": duration,
            "transition": {"type": _map_transition(transition), "duration": 0.5},
            "elements": [],
        }

        media_info = media_files.get("scenes", {}).get(sid, {}) if media_files else {}
        media_file = media_info.get("file")

        if media_file and os.path.exists(media_file):
            if media_file.endswith((".mp4", ".mov", ".avi")):
                j2v_scene["elements"].append({
                    "type": "video", "src": media_file,
                    "start": 0, "duration": duration,
                    "animation": _get_camera_animation(visual.get("camera", {})),
                })
            else:
                j2v_scene["elements"].append({
                    "type": "image", "src": media_file,
                    "start": 0, "duration": duration,
                    "animation": _get_camera_animation(visual.get("camera", {})),
                })
        else:
            j2v_scene["elements"].append({
                "type": "text", "text": visual.get("description", ""),
                "style": {"fontSize": 24, "color": "#FFFFFF",
                          "backgroundColor": "#1a1b2e", "textAlign": "center"},
                "start": 0, "duration": duration,
            })

        tts_info = tts_files.get("scenes", {}).get(sid, {}) if tts_files else {}
        tts_file = tts_info.get("file")
        if tts_file and os.path.exists(tts_file):
            j2v_scene["elements"].append({
                "type": "audio", "src": tts_file, "start": 0, "volume": 1.0,
            })

        sub_text = subtitle.get("text") or narration.get("text", "")
        if sub_text:
            j2v_scene["elements"].append({
                "type": "subtitle", "text": sub_text,
                "style": _get_subtitle_style(subtitle.get("style", "default")),
                "position": subtitle.get("position", "bottom"),
                "start": 0, "duration": duration,
            })

        recipe["scenes"].append(j2v_scene)

    return recipe


def submit_video(recipe: dict) -> str:
    """JSON2Video API에 레시피 제출"""
    if not JSON2VIDEO_API_KEY:
        raise ValueError("JSON2VIDEO_API_KEY 환경변수를 설정해주세요.")

    res = requests.post(
        f"{J2V_BASE}/movies",
        headers={"x-api-key": JSON2VIDEO_API_KEY, "Content-Type": "application/json"},
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
    """렌더링 완료 대기 후 다운로드"""
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


# ═══════════════════════════════════════════════════════════
# FFmpeg 보조 기능
# ═══════════════════════════════════════════════════════════

def add_intro_outro(
    video_path: str,
    intro_path: str = None,
    outro_path: str = None,
    output_path: str = None,
) -> str:
    """인트로/아웃트로 추가 (FFmpeg)"""
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


# ═══════════════════════════════════════════════════════════
# 유틸리티
# ═══════════════════════════════════════════════════════════

def _parse_duration(duration_str: str) -> float:
    """'5초', '1분 30초', '2:30' 형태를 초 단위로 변환"""
    import re
    m = re.match(r'(\d+)\s*초', duration_str)
    if m:
        return float(m.group(1))
    m = re.match(r'(\d+)\s*분\s*(\d+)?\s*초?', duration_str)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    m = re.match(r'(\d+):(\d+)', duration_str)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r'(\d+\.?\d*)', duration_str)
    if m:
        return float(m.group(1))
    return 5.0


def _map_transition(transition: str) -> str:
    """Video Notation 트랜지션 → JSON2Video 매핑"""
    mapping = {
        "cut": "cut", "fade": "fade", "dissolve": "crossfade",
        "slide-left": "slideLeft", "slide-right": "slideRight",
        "zoom": "zoomIn", "none": "none",
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
    return animation_map.get(movement, {"type": "kenBurns"})


def _get_subtitle_style(style: str) -> dict:
    """자막 스타일 매핑"""
    styles = {
        "default": {
            "fontSize": 36, "fontFamily": "NanumGothicBold",
            "color": "#FFFFFF", "backgroundColor": "rgba(0,0,0,0.6)",
            "padding": "8px 16px", "borderRadius": "8px",
        },
        "highlight": {
            "fontSize": 42, "fontFamily": "NanumGothicExtraBold",
            "color": "#FFD700", "backgroundColor": "rgba(0,0,0,0.8)",
            "padding": "10px 20px", "borderRadius": "8px",
        },
        "large": {
            "fontSize": 56, "fontFamily": "NanumGothicExtraBold",
            "color": "#FFFFFF", "textShadow": "2px 2px 4px rgba(0,0,0,0.8)",
        },
        "animated": {
            "fontSize": 40, "fontFamily": "NanumGothicBold",
            "color": "#FFFFFF", "animation": "fadeIn",
        },
    }
    return styles.get(style, styles["default"])


# ═══════════════════════════════════════════════════════════
# 통합 compose 함수
# ═══════════════════════════════════════════════════════════

def compose_video(
    script: dict,
    tts_result: dict = None,
    media_result: dict = None,
    use_json2video: bool = False,  # 기본값 FFmpeg
    output_path: str = None,
) -> str:
    """
    최종 영상 합성 통합 함수

    기본: FFmpeg 로컬 합성 (안정적, 빠름)
    선택: JSON2Video API (URL 기반 에셋 필요)
    """
    print("🎬 영상 합성 시작...")

    # 레시피 저장 (참고용)
    recipe = create_video_recipe(script, tts_result, media_result)
    recipe_path = OUTPUT_DIR / "last_recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    print(f"  📋 레시피 저장: {recipe_path}")

    if use_json2video and JSON2VIDEO_API_KEY:
        # JSON2Video API (URL 기반 에셋이 있을 때만 유효)
        project_id = submit_video(recipe)
        video_path = wait_and_download(project_id, output_path)
        return video_path
    else:
        # FFmpeg 로컬 합성 (기본)
        print("  🔧 FFmpeg 로컬 합성 모드")
        video_path = compose_with_ffmpeg(script, tts_result, media_result, output_path)
        return video_path


# ─── CLI ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LANstar 영상 합성기")
    parser.add_argument("--script", required=True, help="스크립트 JSON 경로")
    parser.add_argument("--tts-dir", help="TTS 결과 디렉토리")
    parser.add_argument("--media-dir", help="미디어 결과 디렉토리")
    parser.add_argument("--use-j2v", action="store_true", help="JSON2Video 사용")
    parser.add_argument("--output", help="출력 경로")

    args = parser.parse_args()

    with open(args.script) as f:
        script = json.load(f)

    compose_video(
        script,
        use_json2video=args.use_j2v,
        output_path=args.output,
    )
