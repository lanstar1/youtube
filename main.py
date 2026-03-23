"""
LANstar YouTube 콘텐츠 자동화 파이프라인 - FastAPI 웹 서버
Render 배포용 진입점
"""

import os
import json
import time
import uuid
import threading
import traceback
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

# ─── 환경변수에서 config 동적 설정 ─────────────────────────
import config
config.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
config.YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
config.ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
config.PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
config.JSON2VIDEO_API_KEY = os.environ.get("JSON2VIDEO_API_KEY", "")
config.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

from modules.script_generator import generate_script, validate_script, save_script, generate_from_remake_candidate
from modules.seo_optimizer import optimize_seo, analyze_competition
from modules.tts_engine import generate_from_script as tts_generate
from modules.media_generator import generate_from_script as media_generate
from modules.video_composer import compose_video, create_video_recipe
from modules.publisher import create_upload_schedule, auto_detect_shorts_segments, upload_from_script

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ─── Lifespan ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 LANstar YouTube Automation Pipeline 시작")
    yield
    print("👋 서버 종료")


# ─── FastAPI 앱 ──────────────────────────────────────────

app = FastAPI(
    title="LANstar YouTube Automation",
    description="AI 스토리텔링 기반 페이스리스 콘텐츠 자동화 파이프라인",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
static_dir = BASE_DIR / "frontend" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ─── Pydantic 모델 ──────────────────────────────────────

class ScriptRequest(BaseModel):
    product_name: str = Field(..., description="제품명")
    product_model: str = Field("", description="모델명")
    product_features: list[str] = Field(default=[], description="제품 특징")
    category: str = Field("네트워크/서버", description="카테고리")
    target_persona: str = Field("", description="타겟 페르소나")
    pain_point: str = Field("", description="고통점")
    additional_context: str = Field("", description="추가 맥락")
    is_remake: bool = Field(False, description="리메이크 여부")
    original_video_id: str = Field("", description="원본 영상 ID")


class RemakeRequest(BaseModel):
    rank: int = Field(1, description="리메이크 순위 (1~30)", ge=1, le=30)


class CompetitionRequest(BaseModel):
    keyword: str = Field(..., description="분석할 키워드")


class ScheduleRequest(BaseModel):
    script_ids: list[str] = Field(default=[], description="스크립트 파일명 리스트")
    uploads_per_week: int = Field(3, description="주당 업로드 횟수")
    preferred_days: list[int] = Field(default=[1, 3, 5], description="선호 요일 (0=월~6=일)")
    preferred_time: str = Field("18:00", description="업로드 시간")
    start_date: str = Field("", description="시작일 (YYYY-MM-DD)")


class PipelineRequest(BaseModel):
    script_filename: str = Field(..., description="스크립트 파일명")
    voice_id: str = Field("", description="ElevenLabs 보이스 ID")
    image_provider: str = Field("dalle", description="이미지 제공자 (dalle/flux)")
    skip_tts: bool = Field(False, description="TTS 건너뛰기")
    skip_media: bool = Field(False, description="미디어 건너뛰기")
    skip_compose: bool = Field(False, description="영상합성 건너뛰기")


class TTSRequest(BaseModel):
    script_filename: str = Field(..., description="스크립트 파일명")
    voice_id: str = Field("", description="ElevenLabs 보이스 ID")


class MediaRequest(BaseModel):
    script_filename: str = Field(..., description="스크립트 파일명")
    image_provider: str = Field("dalle", description="이미지 제공자 (dalle/flux)")


class ComposeRequest(BaseModel):
    script_filename: str = Field(..., description="스크립트 파일명")
    tts_dir: str = Field("", description="TTS 결과 디렉토리")
    media_dir: str = Field("", description="미디어 결과 디렉토리")


# ─── 파이프라인 잡 추적 ──────────────────────────────────
# 인메모리 잡 상태 (서버 재시작 시 초기화)
pipeline_jobs: dict = {}


def update_job(job_id: str, **kwargs):
    """잡 상태 업데이트 (thread-safe)"""
    if job_id in pipeline_jobs:
        pipeline_jobs[job_id].update(kwargs)
        pipeline_jobs[job_id]["updated_at"] = datetime.now().isoformat()


# ─── 유틸 ────────────────────────────────────────────────

def load_channel_data() -> dict:
    path = BASE_DIR / "lanstar_data.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def list_scripts() -> list:
    """output 디렉토리의 스크립트 목록"""
    scripts = []
    for f in sorted(OUTPUT_DIR.iterdir()):
        if f.name.startswith("script_") and f.name.endswith(".json"):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                scripts.append({
                    "filename": f.name,
                    "title": data.get("headline", {}).get("main_title", ""),
                    "category": data.get("metadata", {}).get("category", ""),
                    "scenes": len(data.get("scenes", [])),
                    "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                })
            except Exception:
                pass
    return scripts


# ─── API 엔드포인트 ──────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """프론트엔드 메인 페이지"""
    frontend = BASE_DIR / "frontend" / "index.html"
    if frontend.exists():
        return FileResponse(str(frontend))
    return HTMLResponse("<h1>LANstar YouTube Automation API</h1><p><a href='/docs'>API 문서</a></p>")


@app.get("/api/health")
async def health():
    """헬스체크"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "api_keys": {
            "anthropic": bool(config.ANTHROPIC_API_KEY),
            "youtube": bool(config.YOUTUBE_API_KEY),
            "elevenlabs": bool(config.ELEVENLABS_API_KEY),
            "pexels": bool(config.PEXELS_API_KEY),
            "json2video": bool(config.JSON2VIDEO_API_KEY),
            "openai": bool(config.OPENAI_API_KEY),
        },
    }


# ── 채널 분석 ──

@app.get("/api/channel/stats")
async def channel_stats():
    """채널 기본 통계"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 분석 데이터가 없습니다. youtube_analyzer.py를 먼저 실행하세요.")
    return {
        "channelName": data.get("channelName"),
        "subscriberCount": data.get("subscriberCount"),
        "totalVideos": data.get("totalVideos"),
        "totalViews": data.get("totalViews"),
        "avgViews": data.get("avgViews"),
        "avgEngagement": data.get("avgEngagement"),
        "categoryStats": data.get("categoryStats"),
        "dayStats": data.get("dayStats"),
    }


@app.get("/api/channel/top-videos")
async def top_videos(sort: str = "views", limit: int = 20):
    """TOP 영상 목록"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 데이터 없음")

    key_map = {"views": "topByViews", "engagement": "topByEngagement", "likes": "topByLikes"}
    key = key_map.get(sort, "topByViews")
    return data.get(key, [])[:limit]


@app.get("/api/channel/remake-candidates")
async def remake_candidates(limit: int = 30):
    """리메이크 후보 목록"""
    data = load_channel_data()
    if not data:
        raise HTTPException(404, "채널 데이터 없음")
    return data.get("remakeCandidates", [])[:limit]


@app.get("/api/channel/dashboard")
async def dashboard():
    """분석 대시보드 HTML"""
    path = BASE_DIR / "lanstar_dashboard.html"
    if path.exists():
        return FileResponse(str(path), media_type="text/html")
    raise HTTPException(404, "대시보드 파일 없음")


# ── 스크립트 생성 ──

@app.post("/api/script/generate")
async def api_generate_script(req: ScriptRequest):
    """AI 스크립트 생성 (Claude API)"""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    try:
        script = generate_script(
            product_name=req.product_name,
            product_model=req.product_model,
            product_features=req.product_features or None,
            category=req.category,
            target_persona=req.target_persona,
            pain_point=req.pain_point,
            additional_context=req.additional_context,
            is_remake=req.is_remake,
            original_video_id=req.original_video_id,
        )

        errors = validate_script(script)
        channel_data = load_channel_data()
        seo_result = optimize_seo(script, channel_data)
        script["seo"] = seo_result["seo"]

        path = save_script(script)

        return {
            "success": True,
            "filename": Path(path).name,
            "title": script.get("headline", {}).get("main_title", ""),
            "scenes": len(script.get("scenes", [])),
            "seo_score": seo_result["score"],
            "validation_errors": errors,
            "script": script,
        }
    except Exception as e:
        raise HTTPException(500, f"스크립트 생성 실패: {str(e)}")


@app.post("/api/script/remake")
async def api_remake_script(req: RemakeRequest):
    """리메이크 후보 기반 스크립트 생성"""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY가 설정되지 않았습니다.")

    data = load_channel_data()
    candidates = data.get("remakeCandidates", [])
    if req.rank > len(candidates):
        raise HTTPException(400, f"리메이크 후보 {req.rank}순위가 없습니다.")

    try:
        candidate = candidates[req.rank - 1]
        script = generate_from_remake_candidate(candidate, data)

        errors = validate_script(script)
        seo_result = optimize_seo(script, data)
        script["seo"] = seo_result["seo"]

        path = save_script(script)

        return {
            "success": True,
            "filename": Path(path).name,
            "original_title": candidate["title"],
            "original_views": candidate["viewCount"],
            "new_title": script.get("headline", {}).get("main_title", ""),
            "scenes": len(script.get("scenes", [])),
            "seo_score": seo_result["score"],
            "script": script,
        }
    except Exception as e:
        raise HTTPException(500, f"리메이크 스크립트 생성 실패: {str(e)}")


@app.get("/api/scripts")
async def api_list_scripts():
    """생성된 스크립트 목록"""
    return list_scripts()


@app.get("/api/scripts/{filename}")
async def api_get_script(filename: str):
    """스크립트 상세 조회"""
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "스크립트를 찾을 수 없습니다.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── SEO & 경쟁분석 ──

@app.post("/api/seo/competition")
async def api_competition(req: CompetitionRequest):
    """키워드 경쟁 분석"""
    data = load_channel_data()
    return analyze_competition(req.keyword, data)


# ── 스케줄 ──

@app.post("/api/schedule/create")
async def api_create_schedule(req: ScheduleRequest):
    """업로드 스케줄 생성"""
    scripts = []
    for sid in req.script_ids:
        path = OUTPUT_DIR / sid
        if path.exists():
            with open(path, encoding="utf-8") as f:
                scripts.append(json.load(f))

    if not scripts:
        raise HTTPException(400, "유효한 스크립트가 없습니다.")

    schedule = create_upload_schedule(
        scripts,
        start_date=req.start_date or None,
        uploads_per_week=req.uploads_per_week,
        preferred_days=req.preferred_days,
        preferred_time=req.preferred_time,
    )
    return schedule


# ── 파이프라인 실행 (단계별) ──

@app.post("/api/pipeline/tts")
async def api_pipeline_tts(req: TTSRequest, background_tasks: BackgroundTasks):
    """Stage 3-A: TTS 음성 생성"""
    script_path = OUTPUT_DIR / req.script_filename
    if not script_path.exists():
        raise HTTPException(404, "스크립트 파일을 찾을 수 없습니다.")

    if not config.ELEVENLABS_API_KEY or config.ELEVENLABS_API_KEY.startswith("placeholder"):
        raise HTTPException(400, "ELEVENLABS_API_KEY가 설정되지 않았습니다. Render 환경변수에서 실제 키를 입력해주세요.")

    job_id = str(uuid.uuid4())[:8]
    pipeline_jobs[job_id] = {
        "id": job_id, "type": "tts", "status": "running",
        "script": req.script_filename, "created_at": datetime.now().isoformat(),
        "progress": 0, "message": "TTS 생성 시작...", "result": None
    }

    def run_tts():
        try:
            with open(script_path, encoding="utf-8") as f:
                script = json.load(f)
            scenes = script.get("scenes", [])
            total = len([s for s in scenes if s.get("narration", {}).get("text")])

            update_job(job_id, message=f"0/{total} 장면 처리 중...")
            result = tts_generate(script, voice_id=req.voice_id or None)

            update_job(job_id, status="completed", progress=100,
                       message=f"TTS 완료! {len(result.get('files', []))}개 파일 생성",
                       result={"files_count": len(result.get("files", [])),
                               "total_chars": result.get("total_chars", 0),
                               "output_dir": str(Path(result["files"][0]).parent) if result.get("files") else ""})
        except Exception as e:
            update_job(job_id, status="failed", message=f"TTS 실패: {str(e)}")

    background_tasks.add_task(run_tts)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/pipeline/media")
async def api_pipeline_media(req: MediaRequest, background_tasks: BackgroundTasks):
    """Stage 3-B: AI 이미지 + 스톡 미디어 생성"""
    script_path = OUTPUT_DIR / req.script_filename
    if not script_path.exists():
        raise HTTPException(404, "스크립트 파일을 찾을 수 없습니다.")

    has_key = (req.image_provider == "dalle" and config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("placeholder")) or \
              (req.image_provider == "flux" and os.environ.get("FAL_KEY"))
    if not has_key and not (config.PEXELS_API_KEY and not config.PEXELS_API_KEY.startswith("placeholder")):
        raise HTTPException(400, f"이미지 생성 API 키가 설정되지 않았습니다. ({req.image_provider.upper()} 또는 PEXELS)")

    job_id = str(uuid.uuid4())[:8]
    pipeline_jobs[job_id] = {
        "id": job_id, "type": "media", "status": "running",
        "script": req.script_filename, "created_at": datetime.now().isoformat(),
        "progress": 0, "message": "미디어 생성 시작...", "result": None
    }

    def run_media():
        try:
            with open(script_path, encoding="utf-8") as f:
                script = json.load(f)
            result = media_generate(script, image_provider=req.image_provider)
            update_job(job_id, status="completed", progress=100,
                       message=f"미디어 완료! {len(result.get('files', []))}개 파일, {len(result.get('errors', []))}개 오류",
                       result={"files_count": len(result.get("files", [])),
                               "errors": result.get("errors", []),
                               "output_dir": str(Path(result["files"][0]).parent) if result.get("files") else "",
                               "scenes": {str(k): v for k, v in result.get("scenes", {}).items()}})
        except Exception as e:
            update_job(job_id, status="failed", message=f"미디어 생성 실패: {str(e)}")

    background_tasks.add_task(run_media)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/pipeline/compose")
async def api_pipeline_compose(req: ComposeRequest, background_tasks: BackgroundTasks):
    """Stage 4: JSON2Video 영상 합성"""
    script_path = OUTPUT_DIR / req.script_filename
    if not script_path.exists():
        raise HTTPException(404, "스크립트 파일을 찾을 수 없습니다.")

    job_id = str(uuid.uuid4())[:8]
    pipeline_jobs[job_id] = {
        "id": job_id, "type": "compose", "status": "running",
        "script": req.script_filename, "created_at": datetime.now().isoformat(),
        "progress": 0, "message": "영상 합성 시작...", "result": None
    }

    def run_compose():
        try:
            with open(script_path, encoding="utf-8") as f:
                script = json.load(f)

            # TTS/미디어 결과 로드 (디렉토리에서)
            tts_result = None
            media_result = None
            if req.tts_dir and os.path.isdir(req.tts_dir):
                tts_result = _load_stage_result(req.tts_dir, "tts")
            if req.media_dir and os.path.isdir(req.media_dir):
                media_result = _load_stage_result(req.media_dir, "media")

            update_job(job_id, message="레시피 생성 중...")
            video_path = compose_video(script, tts_result=tts_result, media_result=media_result)

            update_job(job_id, status="completed", progress=100,
                       message=f"영상 합성 완료!",
                       result={"video_path": video_path,
                               "filename": os.path.basename(video_path)})
        except Exception as e:
            update_job(job_id, status="failed", message=f"영상 합성 실패: {str(e)}")

    background_tasks.add_task(run_compose)
    return {"job_id": job_id, "status": "started"}


@app.post("/api/pipeline/run")
async def api_pipeline_full(req: PipelineRequest, background_tasks: BackgroundTasks):
    """전체 파이프라인 실행 (스크립트 → TTS → 미디어 → 합성)"""
    script_path = OUTPUT_DIR / req.script_filename
    if not script_path.exists():
        raise HTTPException(404, "스크립트 파일을 찾을 수 없습니다.")

    job_id = str(uuid.uuid4())[:8]
    pipeline_jobs[job_id] = {
        "id": job_id, "type": "full_pipeline", "status": "running",
        "script": req.script_filename, "created_at": datetime.now().isoformat(),
        "progress": 0, "current_stage": "init", "stages": {},
        "message": "파이프라인 시작...", "result": None
    }

    def run_pipeline():
        try:
            with open(script_path, encoding="utf-8") as f:
                script = json.load(f)

            stages_done = {}

            # Stage TTS
            if not req.skip_tts:
                update_job(job_id, current_stage="tts", progress=10,
                           message="🎤 TTS 음성 생성 중...")
                try:
                    tts_result = tts_generate(script, voice_id=req.voice_id or None)
                    stages_done["tts"] = {
                        "status": "completed",
                        "files_count": len(tts_result.get("files", [])),
                        "total_chars": tts_result.get("total_chars", 0),
                        "output_dir": str(Path(tts_result["files"][0]).parent) if tts_result.get("files") else ""
                    }
                    update_job(job_id, progress=33, stages=stages_done,
                               message=f"TTS 완료 ({len(tts_result.get('files', []))}개)")
                except Exception as e:
                    stages_done["tts"] = {"status": "failed", "error": str(e)}
                    update_job(job_id, stages=stages_done)
                    tts_result = None
            else:
                tts_result = None
                stages_done["tts"] = {"status": "skipped"}

            # Stage Media
            if not req.skip_media:
                update_job(job_id, current_stage="media", progress=40,
                           message="🎨 미디어 소스 생성 중...")
                try:
                    media_result = media_generate(script, image_provider=req.image_provider)
                    stages_done["media"] = {
                        "status": "completed",
                        "files_count": len(media_result.get("files", [])),
                        "errors": media_result.get("errors", []),
                        "output_dir": str(Path(media_result["files"][0]).parent) if media_result.get("files") else ""
                    }
                    update_job(job_id, progress=66, stages=stages_done,
                               message=f"미디어 완료 ({len(media_result.get('files', []))}개)")
                except Exception as e:
                    stages_done["media"] = {"status": "failed", "error": str(e)}
                    update_job(job_id, stages=stages_done)
                    media_result = None
            else:
                media_result = None
                stages_done["media"] = {"status": "skipped"}

            # Stage Compose
            if not req.skip_compose:
                update_job(job_id, current_stage="compose", progress=75,
                           message="🎬 영상 합성 중...")
                try:
                    video_path = compose_video(script, tts_result=tts_result, media_result=media_result)
                    stages_done["compose"] = {
                        "status": "completed",
                        "video_path": video_path,
                        "filename": os.path.basename(video_path)
                    }
                    update_job(job_id, progress=95, stages=stages_done,
                               message="영상 합성 완료!")
                except Exception as e:
                    stages_done["compose"] = {"status": "failed", "error": str(e)}
                    update_job(job_id, stages=stages_done)
                    video_path = None
            else:
                video_path = None
                stages_done["compose"] = {"status": "skipped"}

            # 완료
            update_job(job_id, status="completed", progress=100,
                       current_stage="done", stages=stages_done,
                       message="✅ 파이프라인 완료!",
                       result={
                           "stages": stages_done,
                           "video_path": video_path if video_path else None,
                       })

            # 파이프라인 리포트 저장
            report = {
                "timestamp": datetime.now().isoformat(),
                "script": req.script_filename,
                "stages": stages_done,
                "elapsed_seconds": round(time.time() - time.mktime(
                    datetime.fromisoformat(pipeline_jobs[job_id]["created_at"]).timetuple()), 1),
            }
            report_path = OUTPUT_DIR / f"pipeline_report_{job_id}.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

        except Exception as e:
            update_job(job_id, status="failed",
                       message=f"파이프라인 실패: {str(e)}\n{traceback.format_exc()}")

    background_tasks.add_task(run_pipeline)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/pipeline/status/{job_id}")
async def api_pipeline_status(job_id: str):
    """파이프라인 잡 상태 조회"""
    job = pipeline_jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"잡 {job_id}를 찾을 수 없습니다.")
    return job


@app.get("/api/pipeline/jobs")
async def api_pipeline_jobs():
    """모든 파이프라인 잡 목록"""
    return sorted(pipeline_jobs.values(), key=lambda x: x.get("created_at", ""), reverse=True)


@app.get("/api/pipeline/preview/{filename:path}")
async def api_pipeline_preview(filename: str):
    """생성된 파일 미리보기/다운로드"""
    # output 디렉토리 내 파일만 허용
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        # 절대 경로 시도
        file_path = Path(filename)
    if not file_path.exists():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")

    # 보안: output 디렉토리 내 파일인지 확인
    try:
        file_path.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        raise HTTPException(403, "접근이 허용되지 않는 경로입니다.")

    return FileResponse(str(file_path))


def _load_stage_result(dir_path: str, stage_type: str) -> dict:
    """디렉토리에서 이전 단계 결과를 재구성"""
    result = {"files": [], "scenes": {}}
    dir_p = Path(dir_path)
    if not dir_p.exists():
        return result

    for f in sorted(dir_p.iterdir()):
        if f.is_file():
            result["files"].append(str(f))
            # scene_01_xxx.ext 패턴에서 scene ID 추출
            name = f.stem
            if name.startswith("scene_"):
                try:
                    sid = int(name.split("_")[1])
                    result["scenes"][sid] = {"file": str(f), "type": stage_type}
                except (IndexError, ValueError):
                    pass
    return result


# ── 파이프라인 보고서 ──

@app.get("/api/reports")
async def api_list_reports():
    """파이프라인 실행 보고서 목록"""
    reports = []
    for f in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if f.name.startswith("pipeline_report_") and f.name.endswith(".json"):
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            reports.append({
                "filename": f.name,
                "timestamp": data.get("timestamp", ""),
                "elapsed": data.get("elapsed_seconds", 0),
            })
    return reports


# ─── 프론트엔드 SPA ──────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """채널 분석 대시보드"""
    path = BASE_DIR / "lanstar_dashboard.html"
    if path.exists():
        return FileResponse(str(path), media_type="text/html")
    raise HTTPException(404)


# ─── 실행 ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
