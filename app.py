from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from core import (
    DownloadMode,
    DuplicateVideoError,
    InvalidURLError,
    NoFormatsAvailableError,
    VideoAccessError,
    YoutubeEngine,
    YoutubeEngineError,
)


st.set_page_config(
    page_title="Z-Downloader",
    page_icon="Z",
    layout="centered",
)


ROOT_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = str(ROOT_DIR / "Descargas_Z")
APP_DATA_DIR = ROOT_DIR / "Z-Data"
METADATA_DIR = str(APP_DATA_DIR / "metadatos")
LOG_DIR = APP_DATA_DIR / "logs"
APP_LOG_FILE = LOG_DIR / "zdownloader.log"
MODE_LABELS = {
    "Estandar": DownloadMode.STANDARD,
    "Kaioken": DownloadMode.KAIOKEN,
    "Podcast": DownloadMode.PODCAST,
}
PODCAST_FORMATS = {
    "mp3": "MP3 320 kbps",
    "wav": "WAV sin perdida",
    "both": "MP3 y WAV",
}
FILE_ORGANIZATION_OPTIONS = [
    "Sin subcarpetas",
    "Agrupar por Canal",
    "Agrupar por Playlist",
]


def ensure_state() -> None:
    defaults = {
        "logs": [],
        "progress": 0.0,
        "progress_text": "Esperando una descarga...",
        "video_info": None,
        "formats": [],
        "result": None,
        "inspected_url": "",
        "last_error": None,
        "allow_redownload": False,
        "podcast_format": "mp3",
        "download_playlist": False,
        "queue_input": "",
        "queue_items": [],
        "queue_results": [],
        "playlist_items": [],
        "blocked_items": [],
        "active_download_label": "",
        "file_organization": FILE_ORGANIZATION_OPTIONS[0],
        "embed_subtitles": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_runtime_state(keep_video_data: bool = True) -> None:
    st.session_state.logs = []
    st.session_state.progress = 0.0
    st.session_state.progress_text = "Preparando descarga..."
    st.session_state.result = None
    st.session_state.last_error = None
    st.session_state.playlist_items = []
    st.session_state.blocked_items = []
    st.session_state.active_download_label = ""
    if not keep_video_data:
        st.session_state.video_info = None
        st.session_state.formats = []
        st.session_state.inspected_url = ""
        st.session_state.allow_redownload = False


def format_bytes(size: float | int | None) -> str:
    if not size:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.1f} {units[unit_index]}"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "Desconocida"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_bitrate(bits_per_second: int | None) -> str:
    if not bits_per_second:
        return "Desconocido"
    return f"{bits_per_second / 1000:.0f} kbps"


def normalize_blocked_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items or []:
        title = str(item.get("title") or item.get("video_id") or item.get("url") or "Video bloqueado")
        reason = str(item.get("reason") or "No descargable")
        detail = str(item.get("detail") or reason)
        video_id = item.get("video_id")
        url = item.get("url")
        key = (str(video_id or title), reason)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "title": title,
                "video_id": video_id,
                "reason": reason,
                "detail": detail,
                "url": url,
            }
        )
    return normalized


def append_blocked_items(items: list[dict[str, Any]] | None) -> None:
    merged = list(st.session_state.blocked_items)
    merged.extend(normalize_blocked_items(items))
    st.session_state.blocked_items = normalize_blocked_items(merged)


def blocked_items_from_exception(exc: Exception, fallback_url: str | None = None) -> list[dict[str, Any]]:
    blocked = getattr(exc, "blocked_items", None)
    if blocked:
        return normalize_blocked_items(blocked)

    message = str(exc)
    lowered = message.lower()
    reason = None
    if "restrict" in lowered and "edad" in lowered:
        reason = "Restriccion de edad"
    elif "sign in to confirm your age" in lowered:
        reason = "Restriccion de edad"
    elif "private" in lowered:
        reason = "Video privado"
    elif "members-only" in lowered or "members only" in lowered:
        reason = "Solo para miembros"
    elif "unavailable" in lowered or "not available" in lowered:
        reason = "No disponible"

    if not reason:
        return []

    return normalize_blocked_items(
        [
            {
                "title": fallback_url or "Video bloqueado",
                "video_id": None,
                "reason": reason,
                "detail": message,
                "url": fallback_url,
            }
        ]
    )


def append_log(message: str, log_placeholder: Any | None = None) -> None:
    st.session_state.logs.append(message)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with APP_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")
    if log_placeholder is not None:
        render_logs(log_placeholder)


def parse_queue_urls(raw_text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for line in (raw_text or "").splitlines():
        candidate = line.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def shorten_text(value: str, limit: int = 72) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def status_label(status: str) -> str:
    return {
        "pending": "Pendiente",
        "running": "Procesando",
        "downloading": "Descargando",
        "finished": "Finalizando",
        "completed": "Completado",
        "success": "Completado",
        "error": "Error",
    }.get((status or "").strip().lower(), "Procesando")


def queue_status_label(status: str) -> str:
    return {
        "pending": "Pendiente",
        "running": "Procesando",
        "success": "Completado",
        "blocked": "Bloqueado",
        "error": "Error",
    }.get((status or "").strip().lower(), "Pendiente")


def init_queue_items(urls: list[str]) -> None:
    st.session_state.queue_items = [
        {
            "index": index,
            "url": url,
            "status": "pending",
            "detail": "En espera",
        }
        for index, url in enumerate(urls, start=1)
    ]
    st.session_state.queue_results = []


def update_queue_item(index: int, status: str, detail: str) -> None:
    items = st.session_state.queue_items
    if index < 1 or index > len(items):
        return
    items[index - 1]["status"] = status
    items[index - 1]["detail"] = detail


def clear_queue_runtime() -> None:
    st.session_state.queue_items = []
    st.session_state.queue_results = []


def update_playlist_state(payload: dict[str, Any]) -> None:
    item_count = payload.get("item_count")
    item_index = payload.get("item_index")
    if not item_count or not item_index or int(item_count) <= 1:
        return

    total_items = int(item_count)
    current_index = int(item_index)
    if current_index < 1 or current_index > total_items:
        return

    if len(st.session_state.playlist_items) != total_items:
        st.session_state.playlist_items = [
            {
                "index": index,
                "title": f"Elemento {index}",
                "status": "pending",
                "progress": "0.0%",
            }
            for index in range(1, total_items + 1)
        ]

    row = st.session_state.playlist_items[current_index - 1]
    if payload.get("item_label"):
        row["title"] = str(payload["item_label"])
    row["status"] = payload.get("status") or row["status"]
    percent = float(payload.get("percent") or 0.0)
    if row["status"] == "completed":
        percent = 100.0
    row["progress"] = f"{percent:.1f}%"


def render_markdown_table(
    title: str,
    rows: list[dict[str, str]],
    placeholder: Any | None = None,
) -> None:
    if not rows:
        if placeholder is not None:
            placeholder.empty()
        return

    lines = [
        f"**{title}**",
        "",
        "| # | Elemento | Estado | Detalle |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['index']} | {row['name']} | {row['status']} | {row['detail']} |"
        )

    content = "\n".join(lines)
    if placeholder is None:
        st.markdown(content)
    else:
        placeholder.markdown(content)


def render_queue_tracker(queue_placeholder: Any | None = None) -> None:
    rows = [
        {
            "index": str(item["index"]),
            "name": shorten_text(item["url"], limit=58),
            "status": queue_status_label(item["status"]),
            "detail": shorten_text(item["detail"], limit=46),
        }
        for item in st.session_state.queue_items
    ]
    render_markdown_table("Estado De La Cola", rows, queue_placeholder)


def render_playlist_tracker(playlist_placeholder: Any | None = None) -> None:
    rows = [
        {
            "index": str(item["index"]),
            "name": shorten_text(item["title"], limit=46),
            "status": status_label(item["status"]),
            "detail": item["progress"],
        }
        for item in st.session_state.playlist_items
    ]
    render_markdown_table("Estado De La Playlist", rows, playlist_placeholder)


def build_target_quality_profile(selected_format_id: str | None) -> dict[str, Any] | None:
    selected = selected_format_details(selected_format_id)
    if not selected:
        return None
    return {
        "height": selected.get("height") or 0,
        "fps": selected.get("fps") or 0,
        "ext": (selected.get("ext") or "bin").lower(),
    }


def select_matching_queue_format(
    quality_options: list[dict[str, Any]],
    target_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not quality_options:
        return None
    if not target_profile:
        return quality_options[0]

    target_height = int(target_profile.get("height") or 0)
    target_fps = int(target_profile.get("fps") or 0)
    target_ext = str(target_profile.get("ext") or "bin").lower()

    def score(candidate: dict[str, Any]) -> tuple[int, int, int, int, int, int, int]:
        height = int(candidate.get("height") or 0)
        fps = int(candidate.get("fps") or 0)
        ext = str(candidate.get("ext") or "bin").lower()
        height_band = 0 if height == target_height else 1 if 0 < height <= target_height else 2
        fps_band = 0 if fps == target_fps else 1
        ext_band = 0 if ext == target_ext else 1
        return (
            height_band,
            abs(target_height - height),
            fps_band,
            abs(target_fps - fps),
            ext_band,
            -int(candidate.get("tbr") or 0),
            -int(candidate.get("filesize") or 0),
        )

    return min(quality_options, key=score)


def resolve_queue_format_id(
    engine: YoutubeEngine,
    url: str,
    mode: str,
    selected_format_id: str | None,
    download_playlist: bool,
    file_organization: str,
    log_callback: Callable[[str], None],
) -> str | None:
    if mode != DownloadMode.STANDARD:
        return selected_format_id

    target_profile = build_target_quality_profile(selected_format_id)
    if not target_profile:
        raise NoFormatsAvailableError("Inspecciona un video y selecciona una calidad antes de usar la cola.")

    inspection = engine.inspect(
        url,
        log_callback=log_callback,
        download_playlist=download_playlist,
        file_organization=file_organization,
    )
    matched_format = select_matching_queue_format(inspection["quality_options"], target_profile)
    if not matched_format:
        raise NoFormatsAvailableError("No se encontro una calidad compatible para esta URL de la cola.")

    selected_label = matched_format.get("display_label", matched_format.get("format_id", "desconocido"))
    log_callback(f"Calidad aplicada en cola: {selected_label}")
    return matched_format["format_id"]


def open_folder(target: Path) -> str:
    target.mkdir(parents=True, exist_ok=True)
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            subprocess.Popen(["explorer", str(target)])
    except OSError as exc:
        raise YoutubeEngineError(f"No se pudo abrir la carpeta: {exc}") from exc
    return f"Abriendo `{target}`"


def update_progress_state(payload: dict[str, Any]) -> None:
    percent = float(payload.get("percent") or 0.0)
    status = payload.get("status") or "pending"
    speed = payload.get("speed")
    eta = payload.get("eta")
    item_index = payload.get("item_index")
    item_count = payload.get("item_count")
    item_label = payload.get("item_label")

    details = []
    if st.session_state.active_download_label:
        details.append(st.session_state.active_download_label)
    if item_count and item_count > 1 and item_index:
        details.append(f"Elemento {int(item_index)}/{int(item_count)}")
    if item_label:
        details.append(str(item_label))
    if speed:
        details.append(f"Velocidad: {format_bytes(speed)}/s")
    if eta is not None:
        details.append(f"ETA: {int(eta)}s")

    st.session_state.progress = max(0.0, min(percent, 100.0))
    suffix = " | ".join(details)
    st.session_state.progress_text = (
        f"{status_label(status)}... {st.session_state.progress:.1f}%"
        + (f" | {suffix}" if suffix else "")
    )
    update_playlist_state(payload)


def render_progress_widgets(
    progress_placeholder: Any | None = None,
    status_placeholder: Any | None = None,
) -> None:
    progress_value = max(0.0, min(st.session_state.progress / 100.0, 1.0))
    if progress_placeholder is None:
        st.progress(progress_value)
    else:
        progress_placeholder.progress(progress_value)

    if status_placeholder is None:
        st.caption(st.session_state.progress_text)
    else:
        status_placeholder.caption(st.session_state.progress_text)


def render_logs(log_placeholder: Any | None = None) -> None:
    logs = st.session_state.logs or ["Aun no hay eventos."]
    log_text = "\n".join(f"- {line}" for line in logs)
    if log_placeholder is None:
        st.code(log_text, language="text")
    else:
        log_placeholder.code(log_text, language="text")


def build_live_callbacks(
    progress_placeholder: Any,
    status_placeholder: Any,
    log_placeholder: Any,
    playlist_placeholder: Any,
) -> tuple[Callable[[dict[str, Any]], None], Callable[[str], None]]:
    def on_progress(payload: dict[str, Any]) -> None:
        update_progress_state(payload)
        render_progress_widgets(progress_placeholder, status_placeholder)
        render_playlist_tracker(playlist_placeholder)

    def on_log(message: str) -> None:
        append_log(message, log_placeholder)

    return on_progress, on_log


def inspect_video(
    engine: YoutubeEngine,
    url: str,
    download_playlist: bool,
    file_organization: str,
) -> None:
    reset_runtime_state(keep_video_data=False)
    clear_queue_runtime()
    append_log("Validando URL y consultando metadatos...")

    inspection = engine.inspect(
        url,
        log_callback=append_log,
        download_playlist=download_playlist,
        file_organization=file_organization,
    )
    video_info = inspection["video_info"]
    quality_options = inspection["quality_options"]

    st.session_state.video_info = video_info
    st.session_state.formats = quality_options
    st.session_state.inspected_url = url.strip()

    if video_info.get("is_playlist"):
        append_log(
            f"Playlist detectada: {video_info['playlist_title']} ({video_info['playlist_count']} elementos)."
        )
        append_log(f"Vista previa basada en: {video_info['title']}")
    else:
        append_log(f"Video detectado: {video_info['title']}")
    append_log(f"Opciones de calidad encontradas: {len(quality_options)}")
    if video_info.get("duplicate_ignored"):
        append_log("Se ignoro el registro legado de este video para permitir re-descarga HD.")
    elif video_info.get("existing_artifacts"):
        append_log(
            f"Se encontraron {len(video_info['existing_artifacts'])} descargas registradas para este video."
        )


def start_download(
    engine: YoutubeEngine,
    url: str,
    mode: str,
    selected_format_id: str | None,
    progress_callback: Callable[[dict[str, Any]], None],
    log_callback: Callable[[str], None],
    allow_redownload: bool,
    podcast_format: str,
    download_playlist: bool,
    file_organization: str,
    embed_subtitles: bool,
) -> None:
    reset_runtime_state(keep_video_data=True)
    clear_queue_runtime()
    log_callback("Iniciando descarga...")
    st.session_state.active_download_label = "Descarga individual"

    result = engine.download(
        url=url,
        mode=mode,
        format_id=selected_format_id,
        progress_callback=progress_callback,
        log_callback=log_callback,
        allow_redownload=allow_redownload,
        podcast_format=podcast_format,
        download_playlist=download_playlist,
        file_organization=file_organization,
        embed_subtitles=embed_subtitles,
    )
    st.session_state.progress = 100.0
    st.session_state.progress_text = result["message"]
    st.session_state.result = result
    append_blocked_items(result.get("blocked_items"))
    st.session_state.active_download_label = ""


def start_queue_downloads(
    engine: YoutubeEngine,
    urls: list[str],
    mode: str,
    selected_format_id: str | None,
    progress_callback: Callable[[dict[str, Any]], None],
    log_callback: Callable[[str], None],
    allow_redownload: bool,
    podcast_format: str,
    download_playlist: bool,
    file_organization: str,
    embed_subtitles: bool,
    queue_placeholder: Any,
    playlist_placeholder: Any,
) -> None:
    queue_start_time = time.time()
    reset_runtime_state(keep_video_data=True)
    st.session_state.result = None
    init_queue_items(urls)
    render_queue_tracker(queue_placeholder)
    render_playlist_tracker(playlist_placeholder)
    log_callback(f"Cola iniciada con {len(urls)} URL(s).")

    successes = 0
    blocked = 0
    failures = 0
    last_success_result: dict[str, Any] | None = None

    for index, queue_url in enumerate(urls, start=1):
        st.session_state.active_download_label = f"URL {index}/{len(urls)}"
        st.session_state.playlist_items = []
        update_queue_item(index, "running", "Preparando descarga")
        render_queue_tracker(queue_placeholder)
        render_playlist_tracker(playlist_placeholder)
        log_callback(f"Procesando URL {index}/{len(urls)}: {queue_url}")

        try:
            queue_format_id = resolve_queue_format_id(
                engine,
                queue_url,
                mode,
                selected_format_id,
                download_playlist,
                file_organization,
                log_callback,
            )
            result = engine.download(
                url=queue_url,
                mode=mode,
                format_id=queue_format_id,
                progress_callback=progress_callback,
                log_callback=log_callback,
                allow_redownload=allow_redownload,
                podcast_format=podcast_format,
                download_playlist=download_playlist,
                file_organization=file_organization,
                embed_subtitles=embed_subtitles,
            )
            last_success_result = result
            successes += 1
            blocked_items = normalize_blocked_items(result.get("blocked_items"))
            append_blocked_items(blocked_items)
            blocked += len(blocked_items)
            generated_files = len(result.get("items") or [])
            detail = f"{generated_files} archivo(s) generados"
            if blocked_items:
                detail += f" | {len(blocked_items)} bloqueado(s)"
            update_queue_item(index, "success", detail)
            st.session_state.queue_results.append(
                {
                    "index": index,
                    "url": queue_url,
                    "status": "success",
                    "message": result["message"],
                    "generated_files": generated_files,
                    "entry_count": result.get("entry_count", 1),
                    "blocked_items": blocked_items,
                }
            )
            log_callback(f"URL {index}/{len(urls)} completada.")
        except (
            InvalidURLError,
            DuplicateVideoError,
            VideoAccessError,
            NoFormatsAvailableError,
            YoutubeEngineError,
        ) as exc:
            blocked_items = blocked_items_from_exception(exc, fallback_url=queue_url)
            if blocked_items:
                blocked += len(blocked_items)
                append_blocked_items(blocked_items)
            else:
                failures += 1
            error_message = str(exc)
            queue_status = "blocked" if blocked_items else "error"
            queue_detail = blocked_items[0]["reason"] if blocked_items else shorten_text(error_message, limit=54)
            update_queue_item(index, queue_status, shorten_text(queue_detail, limit=54))
            st.session_state.queue_results.append(
                {
                    "index": index,
                    "url": queue_url,
                    "status": queue_status,
                    "message": error_message,
                    "generated_files": 0,
                    "entry_count": 0,
                    "blocked_items": blocked_items,
                }
            )
            if blocked_items:
                log_callback(
                    f"URL {index}/{len(urls)} omitida por bloqueo: "
                    f"{blocked_items[0]['title']} | {blocked_items[0]['reason']}"
                )
            else:
                log_callback(f"Error en URL {index}/{len(urls)}: {error_message}")
        finally:
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)

    queue_total_time = time.time() - queue_start_time
    st.session_state.active_download_label = ""
    st.session_state.progress = 100.0
    st.session_state.progress_text = (
        f"Cola finalizada en {format_duration(queue_total_time)}. Exitos: {successes} | Bloqueados: {blocked} | Fallos: {failures}"
    )
    if last_success_result is not None:
        st.session_state.result = last_success_result
    if failures and not successes:
        st.session_state.last_error = "La cola termino sin descargas exitosas."


def render_video_info() -> None:
    info = st.session_state.video_info
    if not info:
        return

    with st.container(border=True):
        preview_col, details_col = st.columns([1, 2])
        with preview_col:
            if info.get("thumbnail_url"):
                st.image(info["thumbnail_url"], use_container_width=True)
        with details_col:
            st.subheader(info.get("playlist_title") or info["title"])
            col1, col2 = st.columns(2)
            col1.caption(f"Canal: {info['uploader']}")
            col2.caption(f"Duracion: {format_duration(info['duration'])}")
            if info.get("is_playlist"):
                st.caption(f"Playlist: {info['playlist_count']} elementos")
                st.caption(f"Vista previa basada en: {info['title']}")
            else:
                st.caption(f"ID: {info['id']}")

        if info.get("is_playlist"):
            st.info(
                "Se detecto una playlist. La calidad y el modo seleccionados se aplicaran a todos los elementos compatibles."
            )

        if info.get("duplicate_ignored") and not info.get("is_playlist"):
            st.info(
                "Se ignoro el registro anterior del video b1aLqKHFGRw para permitir re-descarga en maxima calidad."
            )
        elif info.get("existing_artifacts") and not info.get("is_playlist"):
            st.warning(
                "Ya existen descargas registradas para este video. La app mostrara mas abajo si la variante actual ya existe."
            )
            artifact_lines = [
                f"{item['label']} | {item['mode']} | {item['artifact_key']}"
                for item in info["existing_artifacts"]
            ]
            st.caption("Descargas registradas: " + " ; ".join(artifact_lines))
            if info.get("has_legacy_video_record"):
                st.caption("Tambien hay registros legacy de la etapa anterior. Ya no bloquearan por si solos una descarga nueva.")

        formats = st.session_state.formats
        if formats:
            best = formats[0]
            st.info(
                f"Mejor calidad detectada: {best['display_label']}. Ahora se usara FFmpeg local para fusionar video y audio cuando haga falta."
            )
            if best.get("merge_required"):
                st.caption("El mejor formato es adaptativo y se fusionara automaticamente con FFmpeg local.")
            elif best.get("height", 0) <= 360:
                st.caption(
                    "Si aqui solo aparece 360p o baja calidad, la plataforma esta limitando los formatos visibles para este contenido en este momento. La app ya no fuerza clientes con PO Token, pero aun puede depender de cookies o un runtime JS para ver mas calidades."
                )


def render_format_selector() -> str | None:
    formats = st.session_state.formats
    if not formats:
        return None

    options = {item["display_label"]: item["format_id"] for item in formats}
    selected_label = st.selectbox(
        "Calidad disponible",
        options=list(options.keys()),
    )
    return options[selected_label]


def selected_format_details(selected_format_id: str | None) -> dict[str, Any] | None:
    if not selected_format_id:
        return None
    for item in st.session_state.formats:
        if item["format_id"] == selected_format_id:
            return item
    return None


def build_artifact_keys_for_selection(
    mode: str,
    selected_format_id: str | None,
    podcast_format: str,
) -> list[str]:
    if mode == DownloadMode.PODCAST:
        if podcast_format == "both":
            return ["podcast_mp3", "podcast_wav"]
        return [f"podcast_{podcast_format.lower()}"]

    selected = selected_format_details(selected_format_id)
    if mode == DownloadMode.KAIOKEN and st.session_state.formats:
        selected = st.session_state.formats[0]

    if not selected:
        return []

    height = selected.get("height") or 0
    fps = selected.get("fps") or 0
    ext = (selected.get("ext") or "bin").lower()
    key_parts = [f"{height}p" if height else "video"]
    if fps:
        key_parts.append(f"{fps}fps")
    key_parts.append(ext)
    return ["video_" + "_".join(key_parts)]


def render_podcast_selector() -> str:
    selected = st.radio(
        "Formato final del podcast",
        options=list(PODCAST_FORMATS.keys()),
        format_func=lambda key: PODCAST_FORMATS[key],
        horizontal=True,
        index=list(PODCAST_FORMATS.keys()).index(st.session_state.podcast_format),
    )
    st.session_state.podcast_format = selected
    st.caption("MP3 prioriza compatibilidad. WAV prioriza fidelidad total. MP3 y WAV genera ambos archivos en una sola descarga.")
    return selected


def render_download_preview(
    mode: str,
    selected_format_id: str | None,
    podcast_format: str,
) -> None:
    info = st.session_state.video_info
    if not info:
        return

    preview: dict[str, Any] | None = None
    if mode == DownloadMode.STANDARD:
        preview = selected_format_details(selected_format_id)
    elif mode == DownloadMode.KAIOKEN and st.session_state.formats:
        preview = st.session_state.formats[0]
    elif mode == DownloadMode.PODCAST:
        preview = info.get("best_audio_source")

    if not preview:
        return

    with st.container(border=True):
        st.caption("Vista previa de la descarga")
        col1, col2, col3 = st.columns(3)
        if mode == DownloadMode.PODCAST:
            col1.metric("Salida", PODCAST_FORMATS[podcast_format])
            col2.metric("Fuente", (preview.get("ext") or "desconocido").upper())
            col3.metric("Duracion", format_duration(info.get("duration")))
            st.caption(
                "Tamano estimado fuente: "
                f"{format_bytes(preview.get('filesize'))} | "
                f"Audio fuente: {format_bitrate(preview.get('abr') * 1000 if preview.get('abr') else None)}"
            )
            if podcast_format == "both":
                st.caption("Se convertira el audio fuente una sola vez para entregar `.mp3` y `.wav`.")
        else:
            col1.metric("Calidad", f"{preview.get('height') or 0}p")
            col2.metric("FPS", str(preview.get("fps") or "N/D"))
            col3.metric("Duracion", format_duration(info.get("duration")))
            st.caption(
                "Tamano estimado: "
                f"{format_bytes(preview.get('estimated_total_size') or preview.get('filesize'))} | "
                f"Contenedor: {(preview.get('ext') or 'desconocido').upper()}"
            )
            if preview.get("merge_required"):
                st.caption("Incluye video adaptativo y el mejor audio disponible para fusion local.")

        if info.get("is_playlist"):
            st.caption(
                f"Esta configuracion se aplicara a los {info['playlist_count']} elementos detectados en la playlist."
            )


def render_redownload_control(
    mode: str,
    selected_format_id: str | None,
    podcast_format: str,
    download_playlist: bool,
) -> None:
    info = st.session_state.video_info
    if not info:
        return

    if download_playlist:
        st.session_state.allow_redownload = st.checkbox(
            "Permitir re-descarga de elementos existentes dentro de la playlist",
            value=st.session_state.allow_redownload,
        )
        st.caption("Si ya existe alguna variante igual dentro de la playlist, esta opcion permitira sobrescribirla.")
        return

    artifact_keys = build_artifact_keys_for_selection(mode, selected_format_id, podcast_format)
    existing_keys = {item["artifact_key"] for item in info.get("existing_artifacts", [])}
    colliding_keys = sorted(set(artifact_keys) & existing_keys)
    exact_duplicate = bool(colliding_keys)

    if not exact_duplicate:
        st.session_state.allow_redownload = False
        return

    st.warning(f"La variante actual ya existe: `{', '.join(colliding_keys)}`")
    st.session_state.allow_redownload = st.checkbox(
        "Permitir re-descarga de esta variante exacta",
        value=st.session_state.allow_redownload,
    )


def render_result() -> None:
    result = st.session_state.result
    if not result:
        return

    items = result.get("items") or [
        {
            "metadata": result["metadata"],
            "metadata_path": result["metadata_path"],
        }
    ]
    metadata = result["metadata"]
    st.success(result["message"])
    with st.container(border=True):
        st.write(f"Archivos generados: `{len(items)}`")
        st.write(f"Videos procesados: `{result.get('entry_count', 1)}`")
        if result.get("blocked_items"):
            st.write(f"Videos bloqueados u omitidos: `{len(result['blocked_items'])}`")
        if "total_time" in result:
            st.write(
                f"⏱️ **Tiempos:** Total `{format_duration(result['total_time'])}` "
                f"(Descarga: `{format_duration(result['download_time'])}` | "
                f"Procesamiento/Conversion: `{format_duration(result['processing_time'])}`)"
            )
        st.write(f"Directorio de metadatos: `{METADATA_DIR}`")

        if len(items) == 1:
            st.write(f"Archivo: `{metadata['filepath']}`")
            st.write(f"Modo: `{metadata['mode']}`")
            st.write(f"Formato: `{metadata['format_id']}`")
            st.write(f"Tamano final: `{format_bytes(metadata.get('filesize'))}`")
            if metadata.get("video_height"):
                fps_value = metadata.get("video_fps")
                fps_text = f" @ {fps_value:.2f}fps" if isinstance(fps_value, float) else ""
                st.write(f"Video final: `{metadata['video_height']}p{fps_text}`")
            if metadata.get("audio_codec"):
                st.write(
                    "Audio final: "
                    f"`{metadata['audio_codec']}` | "
                    f"`{format_bitrate(metadata.get('audio_bitrate'))}`"
                )
            st.write(f"Metadatos: `{result['metadata_path']}`")
            return

        with st.expander("Ver detalle de archivos generados"):
            for item in items:
                file_metadata = item["metadata"]
                st.write(f"Archivo: `{file_metadata['filepath']}`")
                st.write(f"Modo: `{file_metadata['mode']}` | Formato: `{file_metadata['format_id']}`")
                st.write(f"Tamano final: `{format_bytes(file_metadata.get('filesize'))}`")
                if file_metadata.get("video_height"):
                    fps_value = file_metadata.get("video_fps")
                    fps_text = f" @ {fps_value:.2f}fps" if isinstance(fps_value, float) else ""
                    st.write(f"Video final: `{file_metadata['video_height']}p{fps_text}`")
                if file_metadata.get("audio_codec"):
                    st.write(
                        "Audio final: "
                        f"`{file_metadata['audio_codec']}` | "
                        f"`{format_bitrate(file_metadata.get('audio_bitrate'))}`"
                    )
                st.write(f"Metadatos: `{item['metadata_path']}`")
                st.divider()


def render_queue_results() -> None:
    queue_results = st.session_state.queue_results
    if not queue_results:
        return

    success_count = sum(1 for item in queue_results if item["status"] == "success")
    blocked_count = sum(1 for item in queue_results if item["status"] == "blocked")
    error_count = sum(1 for item in queue_results if item["status"] == "error")

    with st.container(border=True):
        st.subheader("Resumen de cola")
        st.write(f"URLs procesadas: `{len(queue_results)}`")
        st.write(f"Exitos: `{success_count}` | Bloqueadas: `{blocked_count}` | Fallos: `{error_count}`")

        with st.expander("Ver detalle de la cola"):
            for item in queue_results:
                st.write(
                    f"{item['index']}. `{item['url']}` | "
                    f"`{queue_status_label(item['status'])}`"
                )
                st.write(f"Detalle: `{item['message']}`")
                if item["status"] == "success":
                    st.write(
                        f"Archivos generados: `{item['generated_files']}` | "
                        f"Videos procesados: `{item['entry_count']}`"
                    )
                    if item.get("blocked_items"):
                        st.write(f"Bloqueados en esta URL: `{len(item['blocked_items'])}`")
                st.divider()


def render_blocked_items() -> None:
    blocked_items = st.session_state.blocked_items
    if not blocked_items:
        return

    with st.container(border=True):
        st.subheader("Videos bloqueados o no descargables")
        st.write(
            "Estos elementos no se descargaran con la configuracion actual. "
            "Asi puedes enfocarte primero en lo que si esta accesible."
        )
        for item in blocked_items:
            title = item.get("title") or item.get("video_id") or "Video bloqueado"
            reason = item.get("reason") or "No descargable"
            detail = item.get("detail") or reason
            st.write(f"`{title}` | `{reason}`")
            st.caption(detail)


def main() -> None:
    ensure_state()
    engine = YoutubeEngine(download_dir=DOWNLOAD_DIR, app_data_dir=str(APP_DATA_DIR))

    st.title("Z-Downloader")
    st.caption(
        "Descarga videos y audio de YouTube y TikTok usando FFmpeg local para obtener la mejor calidad posible sin instalar nada global."
    )

    with st.container(border=True):
        url = st.text_input(
            "URL de YouTube o TikTok",
            placeholder="https://www.youtube.com/watch?v=... o https://vm.tiktok.com/...",
            value=st.session_state.inspected_url,
        )
        download_playlist = st.checkbox(
            "Descargar Playlist completa",
            value=st.session_state.download_playlist,
        )
        st.session_state.download_playlist = download_playlist
        queue_input = st.text_area(
            "Cola de URLs (opcional)",
            placeholder="Pega una URL por linea para procesarlas en secuencia...",
            value=st.session_state.queue_input,
            height=120,
        )
        st.session_state.queue_input = queue_input
        queue_urls = parse_queue_urls(queue_input)
        if queue_urls:
            st.caption(f"Cola detectada: {len(queue_urls)} URL(s) listas para procesarse.")
        mode_label = st.radio(
            "Modo de descarga",
            options=list(MODE_LABELS.keys()),
            horizontal=True,
        )
        mode = MODE_LABELS[mode_label]
        file_organization = st.selectbox(
            "Organizacion de archivos",
            options=FILE_ORGANIZATION_OPTIONS,
            index=FILE_ORGANIZATION_OPTIONS.index(st.session_state.file_organization),
        )
        st.session_state.file_organization = file_organization
        subtitles_disabled = mode == DownloadMode.PODCAST
        embed_subtitles = st.checkbox(
            "Descargar e incrustar subtitulos (si estan disponibles)",
            value=False if subtitles_disabled else st.session_state.embed_subtitles,
            disabled=subtitles_disabled,
        )
        st.session_state.embed_subtitles = False if subtitles_disabled else embed_subtitles
        inspect_clicked = st.button("Inspeccionar URL", use_container_width=True)

    if inspect_clicked:
        try:
            inspect_video(
                engine,
                url,
                download_playlist=download_playlist,
                file_organization=st.session_state.file_organization,
            )
        except (
            InvalidURLError,
            VideoAccessError,
            NoFormatsAvailableError,
            YoutubeEngineError,
        ) as exc:
            st.session_state.last_error = str(exc)
            append_blocked_items(blocked_items_from_exception(exc, fallback_url=url))
            append_log(f"Error: {exc}")
        except Exception as exc:  # pragma: no cover
            st.session_state.last_error = f"Error inesperado: {exc}"
            append_blocked_items(blocked_items_from_exception(exc, fallback_url=url))
            append_log(st.session_state.last_error)

    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    render_video_info()

    selected_format_id = None
    podcast_format = st.session_state.podcast_format
    if mode == DownloadMode.STANDARD and st.session_state.video_info:
        selected_format_id = render_format_selector()
    elif mode == DownloadMode.PODCAST and st.session_state.video_info:
        podcast_format = render_podcast_selector()

    if mode == DownloadMode.KAIOKEN and st.session_state.video_info:
        st.info(
            "Kaioken Extremo descargara la mejor pista de video y el mejor audio disponibles, con perfil agresivo de rendimiento y fusion local."
        )

    if st.session_state.file_organization != FILE_ORGANIZATION_OPTIONS[0]:
        st.caption(f"Organizacion activa: {st.session_state.file_organization}")
    if st.session_state.embed_subtitles and mode != DownloadMode.PODCAST:
        st.caption("Se intentaran descargar e incrustar subtitulos cuando existan para este contenido.")

    render_download_preview(mode, selected_format_id, podcast_format)
    render_redownload_control(
        mode,
        selected_format_id,
        podcast_format,
        st.session_state.download_playlist,
    )

    button_label = {
        DownloadMode.STANDARD: "Descargar en modo Estandar",
        DownloadMode.KAIOKEN: "Descargar en modo Kaioken Extremo",
        DownloadMode.PODCAST: "Descargar en modo Podcast",
    }[mode]
    if st.session_state.download_playlist:
        button_label = {
            DownloadMode.STANDARD: "Descargar playlist en modo Estandar",
            DownloadMode.KAIOKEN: "Descargar playlist en modo Kaioken Extremo",
            DownloadMode.PODCAST: "Descargar playlist en modo Podcast",
        }[mode]

    info = st.session_state.video_info or {}
    current_artifact_keys = build_artifact_keys_for_selection(mode, selected_format_id, podcast_format)
    current_exact_duplicate = bool(
        not st.session_state.download_playlist
        and set(current_artifact_keys) & {item["artifact_key"] for item in info.get("existing_artifacts", [])}
    )
    download_disabled = (
        not url.strip()
        or not st.session_state.video_info
        or (mode == DownloadMode.STANDARD and not selected_format_id)
        or (mode in {DownloadMode.STANDARD, DownloadMode.KAIOKEN} and not st.session_state.formats)
        or (current_exact_duplicate and not st.session_state.allow_redownload)
    )
    queue_disabled = (
        not queue_urls
        or not st.session_state.video_info
        or (mode == DownloadMode.STANDARD and not selected_format_id)
        or (mode in {DownloadMode.STANDARD, DownloadMode.KAIOKEN} and not st.session_state.formats)
    )

    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    queue_placeholder = st.empty()
    playlist_placeholder = st.empty()
    render_progress_widgets(progress_placeholder, status_placeholder)
    render_queue_tracker(queue_placeholder)
    render_playlist_tracker(playlist_placeholder)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Directorio", DOWNLOAD_DIR)
    with col2:
        st.metric("Logs", len(st.session_state.logs))

    folder_feedback = None
    folder_col1, folder_col2, folder_col3 = st.columns(3)
    with folder_col1:
        if st.button("Abrir Descargas", use_container_width=True):
            try:
                folder_feedback = open_folder(Path(DOWNLOAD_DIR))
            except YoutubeEngineError as exc:
                folder_feedback = str(exc)
    with folder_col2:
        if st.button("Abrir Metadatos", use_container_width=True):
            try:
                folder_feedback = open_folder(Path(METADATA_DIR))
            except YoutubeEngineError as exc:
                folder_feedback = str(exc)
    with folder_col3:
        if st.button("Abrir Logs", use_container_width=True):
            try:
                folder_feedback = open_folder(LOG_DIR)
            except YoutubeEngineError as exc:
                folder_feedback = str(exc)

    if folder_feedback:
        st.info(folder_feedback)

    if st.session_state.allow_redownload:
        st.warning("La re-descarga forzada esta activa para esta inspeccion. Si la variante ya existe, podra sobrescribirse.")

    st.caption(f"Log general: `{APP_LOG_FILE}`")
    st.caption("Consola de logs")
    log_placeholder = st.empty()
    render_logs(log_placeholder)

    queue_button_label = f"Procesar cola ({len(queue_urls)})" if queue_urls else "Procesar cola"

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        download_clicked = st.button(
            button_label,
            use_container_width=True,
            disabled=download_disabled,
        )
    with action_col2:
        queue_clicked = st.button(
            queue_button_label,
            use_container_width=True,
            disabled=queue_disabled,
        )

    if download_clicked:
        progress_callback, log_callback = build_live_callbacks(
            progress_placeholder,
            status_placeholder,
            log_placeholder,
            playlist_placeholder,
        )
        try:
            start_download(
                engine,
                url,
                mode,
                selected_format_id,
                progress_callback,
                log_callback,
                allow_redownload=st.session_state.allow_redownload,
                podcast_format=podcast_format,
                download_playlist=st.session_state.download_playlist,
                file_organization=st.session_state.file_organization,
                embed_subtitles=st.session_state.embed_subtitles,
            )
            render_progress_widgets(progress_placeholder, status_placeholder)
            render_logs(log_placeholder)
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)
        except (
            InvalidURLError,
            DuplicateVideoError,
            VideoAccessError,
            NoFormatsAvailableError,
            YoutubeEngineError,
        ) as exc:
            st.session_state.last_error = str(exc)
            st.session_state.active_download_label = ""
            append_blocked_items(blocked_items_from_exception(exc, fallback_url=url))
            append_log(f"Error: {exc}", log_placeholder)
            render_progress_widgets(progress_placeholder, status_placeholder)
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)
        except Exception as exc:  # pragma: no cover
            st.session_state.last_error = f"Error inesperado: {exc}"
            st.session_state.active_download_label = ""
            append_blocked_items(blocked_items_from_exception(exc, fallback_url=url))
            append_log(st.session_state.last_error, log_placeholder)
            render_progress_widgets(progress_placeholder, status_placeholder)
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)

    if queue_clicked:
        progress_callback, log_callback = build_live_callbacks(
            progress_placeholder,
            status_placeholder,
            log_placeholder,
            playlist_placeholder,
        )
        try:
            start_queue_downloads(
                engine,
                queue_urls,
                mode,
                selected_format_id,
                progress_callback,
                log_callback,
                allow_redownload=st.session_state.allow_redownload,
                podcast_format=podcast_format,
                download_playlist=st.session_state.download_playlist,
                file_organization=st.session_state.file_organization,
                embed_subtitles=st.session_state.embed_subtitles,
                queue_placeholder=queue_placeholder,
                playlist_placeholder=playlist_placeholder,
            )
            render_progress_widgets(progress_placeholder, status_placeholder)
            render_logs(log_placeholder)
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)
        except Exception as exc:  # pragma: no cover
            st.session_state.last_error = f"Error inesperado en la cola: {exc}"
            st.session_state.active_download_label = ""
            append_blocked_items(blocked_items_from_exception(exc))
            append_log(st.session_state.last_error, log_placeholder)
            render_progress_widgets(progress_placeholder, status_placeholder)
            render_queue_tracker(queue_placeholder)
            render_playlist_tracker(playlist_placeholder)

    render_queue_results()
    render_blocked_items()
    render_result()


if __name__ == "__main__":
    main()
