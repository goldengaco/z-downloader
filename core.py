from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


ProgressCallback = Callable[[dict[str, Any]], None]
LogCallback = Callable[[str], None]


class YoutubeEngineError(Exception):
    """Base exception for the download engine."""


class InvalidURLError(YoutubeEngineError):
    """Raised when the provided URL is invalid."""


class VideoAccessError(YoutubeEngineError):
    """Raised when yt-dlp cannot access the video."""

    def __init__(self, message: str, blocked_items: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.blocked_items = blocked_items or []


class DuplicateVideoError(YoutubeEngineError):
    """Raised when the video already exists locally."""


class NoFormatsAvailableError(YoutubeEngineError):
    """Raised when no matching formats are available."""


@dataclass(frozen=True)
class DownloadMode:
    STANDARD: str = "standard"
    KAIOKEN: str = "kaioken"
    PODCAST: str = "podcast"


@dataclass(frozen=True)
class PodcastFormat:
    MP3: str = "mp3"
    WAV: str = "wav"
    BOTH: str = "both"


RESETTABLE_DUPLICATE_IDS = {"b1aLqKHFGRw"}


class _CallbackLogger:
    def __init__(
        self,
        log_callback: LogCallback | None,
        entry_title_lookup: dict[str, str] | None = None,
    ) -> None:
        self.log_callback = log_callback
        self.seen_messages: set[str] = set()
        self.entry_title_lookup = entry_title_lookup or {}
        self.blocked_items: list[dict[str, Any]] = []
        self.seen_blocked: set[tuple[str, str]] = set()

    def debug(self, message: str) -> None:
        text = (message or "").strip()
        if not text or text.startswith("[debug]"):
            return

    def warning(self, message: str) -> None:
        self._capture_blocked_item(message)
        self._emit(message, prefix="Aviso")

    def error(self, message: str) -> None:
        self._capture_blocked_item(message)
        self._emit(message, prefix="Error")

    def _emit(self, message: str, prefix: str) -> None:
        if self.log_callback is None:
            return

        normalized = self._normalize_message(message)
        if not normalized or normalized in self.seen_messages:
            return

        self.seen_messages.add(normalized)
        self.log_callback(f"{prefix}: {normalized}")

    @staticmethod
    def _normalize_message(message: str) -> str:
        text = re.sub(r"\x1b\[[0-9;]*m", "", (message or "")).strip()
        if not text:
            return ""

        if "GVS PO Token" in text:
            return (
                "YouTube exigio un PO Token para algunos clientes y omitio esos formatos. "
                "La app seguira con los formatos accesibles del cliente seguro actual."
            )

        if "No supported JavaScript runtime could be found" in text:
            return (
                "yt-dlp no detecta un runtime JavaScript compatible. "
                "YouTube puede ocultar algunas calidades y la lista de formatos puede verse incompleta."
            )

        if "formats have been skipped" in text:
            return (
                "YouTube oculto algunos formatos del cliente actual. "
                "Por eso puede haber menos calidades aqui que en la pagina web."
            )

        if "Sign in to confirm your age" in text:
            return (
                "YouTube marco este contenido como restringido por edad. "
                "No se descargara sin cookies de una sesion autenticada."
            )

        return text

    def _capture_blocked_item(self, message: str) -> None:
        reason = self._classify_blocked_reason(message)
        if not reason:
            return

        video_id = self._extract_video_id(message)
        title = self.entry_title_lookup.get(video_id or "", video_id or "Video bloqueado")
        detail = self._normalize_message(message)
        blocked_key = (video_id or title, reason)
        if blocked_key in self.seen_blocked:
            return

        self.seen_blocked.add(blocked_key)
        url = None
        if video_id:
            url = f"https://www.tiktok.com/@e/video/{video_id}" if video_id.isdigit() else f"https://www.youtube.com/watch?v={video_id}"
        self.blocked_items.append(
            {
                "video_id": video_id,
                "title": title,
                "reason": reason,
                "detail": detail,
                "url": url,
            }
        )

    @staticmethod
    def _extract_video_id(message: str) -> str | None:
        text = re.sub(r"\x1b\[[0-9;]*m", "", (message or "")).strip()
        match = re.search(r"\[(?:youtube|tiktok)\]\s+([A-Za-z0-9_-]+)\s*:", text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _classify_blocked_reason(message: str) -> str | None:
        text = re.sub(r"\x1b\[[0-9;]*m", "", (message or "")).strip().lower()
        if not text:
            return None
        if "sign in to confirm your age" in text:
            return "Restriccion de edad"
        if "private video" in text or "this video is private" in text:
            return "Video privado"
        if "members-only" in text or "members only" in text:
            return "Solo para miembros"
        if "unavailable" in text or "not available" in text:
            return "No disponible"
        return None


class YoutubeEngine:
    def __init__(self, download_dir: str = "./Descargas_Z", app_data_dir: str = "./Z-Data") -> None:
        self.download_dir = Path(download_dir).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.app_data_dir = Path(app_data_dir).resolve()
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir = self.app_data_dir / "metadatos"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.app_data_dir / "_temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            import static_ffmpeg
            static_ffmpeg.add_paths()
        except ImportError:
            raise YoutubeEngineError("Falta la dependencia 'static-ffmpeg'. Instálalo con pip install static-ffmpeg.")

    def inspect(
        self,
        url: str,
        log_callback: LogCallback | None = None,
        download_playlist: bool = False,
        cookies_browser: str | None = None,
        file_organization: str = "Sin subcarpetas",
    ) -> dict[str, Any]:
        normalized_url = self._normalize_url(url)
        info = self._extract_info(
            normalized_url,
            log_callback=log_callback,
            download_playlist=download_playlist,
            cookies_browser=cookies_browser,
            extract_flat=download_playlist,
        )
        reference_info = self._primary_entry_info(info)
        reference_info = self._enrich_reference_info(info, reference_info, cookies_browser, log_callback)
        return {
            "video_info": self._build_video_info(info, reference_info, normalized_url),
            "quality_options": self._quality_options_from_info(reference_info),
        }

    def get_video_info(
        self,
        url: str,
        log_callback: LogCallback | None = None,
        download_playlist: bool = False,
        cookies_browser: str | None = None,
        file_organization: str = "Sin subcarpetas",
    ) -> dict[str, Any]:
        return self.inspect(
            url,
            log_callback=log_callback,
            download_playlist=download_playlist,
            cookies_browser=cookies_browser,
            file_organization=file_organization,
        )["video_info"]

    def get_progressive_formats(
        self,
        url: str,
        log_callback: LogCallback | None = None,
        download_playlist: bool = False,
        cookies_browser: str | None = None,
        file_organization: str = "Sin subcarpetas",
    ) -> list[dict[str, Any]]:
        return self.inspect(
            url,
            log_callback=log_callback,
            download_playlist=download_playlist,
            cookies_browser=cookies_browser,
            file_organization=file_organization,
        )["quality_options"]

    def download(
        self,
        url: str,
        mode: str,
        format_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
        log_callback: LogCallback | None = None,
        allow_redownload: bool = False,
        podcast_format: str = PodcastFormat.MP3,
        download_playlist: bool = False,
        cookies_browser: str | None = None,
        file_organization: str = "Sin subcarpetas",
        embed_subtitles: bool = False,
    ) -> dict[str, Any]:
        start_time = time.time()
        normalized_url = self._normalize_url(url)
        info = self._extract_info(
            normalized_url,
            log_callback=log_callback,
            download_playlist=download_playlist,
            cookies_browser=cookies_browser,
            extract_flat=download_playlist,
        )
        reference_info = self._primary_entry_info(info)
        reference_info = self._enrich_reference_info(info, reference_info, cookies_browser, log_callback)

        selected_format_expression, selected_format = self._resolve_format(
            reference_info,
            mode,
            format_id,
            podcast_format=podcast_format,
        )
        artifact_keys = self._artifact_keys_for_selection(mode, selected_format, podcast_format)
        self._ensure_not_duplicate(
            info,
            artifact_keys=artifact_keys,
            allow_redownload=allow_redownload,
        )
        self._log(
            log_callback,
            f"Formato seleccionado: {selected_format.get('display_label', selected_format_expression)}",
        )

        hooks = [self._build_progress_hook(progress_callback, log_callback)]
        entry_title_lookup = self._entry_title_lookup(info)
        logger = _CallbackLogger(log_callback, entry_title_lookup=entry_title_lookup)
        ydl_options = self._build_download_options(
            selected_format_expression=selected_format_expression,
            mode=mode,
            logger=logger,
            hooks=hooks,
            allow_redownload=allow_redownload or self._should_ignore_duplicate(reference_info.get("id")),
            podcast_format=podcast_format,
            download_playlist=download_playlist,
            cookies_browser=cookies_browser,
            file_organization=file_organization,
            embed_subtitles=embed_subtitles,
        )

        try:
            download_start_time = time.time()
            with YoutubeDL(ydl_options) as ydl:
                final_info = ydl.extract_info(normalized_url, download=True)
                final_info = ydl.sanitize_info(final_info)
            download_time = time.time() - download_start_time
        except DownloadError as exc:
            blocked_items = logger.blocked_items or self._blocked_items_from_message(
                str(exc),
                entry_title_lookup=entry_title_lookup,
                fallback_url=normalized_url,
            )
            raise VideoAccessError(f"No se pudo completar la descarga: {exc}", blocked_items=blocked_items) from exc

        downloaded_entries = self._downloaded_entries(final_info)
        if not downloaded_entries:
            blocked_items = logger.blocked_items
            raise VideoAccessError(
                "yt-dlp no devolvio elementos descargados para procesar.",
                blocked_items=blocked_items,
            )

        processing_start_time = time.time()
        items: list[dict[str, Any]] = []
        
        # Usar ThreadPoolExecutor para un "pipeline suave" de conversiones
        # max_workers=2 asegura solapamiento interno sin sobrecargar el disco/RAM
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for entry_index, entry_info in enumerate(downloaded_entries, start=1):
                future = executor.submit(
                    self._finalize_entry_download,
                    entry_info,
                    mode=mode,
                    format_id=selected_format_expression,
                    selected_format=selected_format,
                    podcast_format=podcast_format,
                    allow_redownload=allow_redownload,
                    log_callback=None,  # Evita errores de ScriptRunContext de Streamlit en hilos paralelos
                )
                futures.append((entry_index, entry_info, future))

            for entry_index, entry_info, future in futures:
                entry_label = entry_info.get("title") or entry_info.get("id") or f"Elemento {entry_index}"
                if len(downloaded_entries) > 1:
                    self._log(log_callback, f"Procesando conversión: {entry_label}...")

                entry_results = future.result()
                items.extend(entry_results)
                
                total_entry_size = sum(
                    int(item["metadata"].get("filesize") or 0)
                    for item in entry_results
                )
                self._emit_progress(
                    progress_callback,
                    {
                        "status": "completed",
                        "percent": 100.0,
                        "downloaded_bytes": total_entry_size or None,
                        "total_bytes": total_entry_size or None,
                        "speed": None,
                        "eta": 0,
                        "filename": entry_results[-1]["metadata"]["filepath"],
                        "item_index": entry_index,
                        "item_count": len(downloaded_entries),
                        "item_label": entry_label,
                        "generated_files": len(entry_results),
                    },
                )
                if len(downloaded_entries) > 1:
                    self._log(
                        log_callback,
                        f"Elemento {entry_index}/{len(downloaded_entries)} completado: {entry_label}",
                    )
        
        processing_time = time.time() - processing_start_time
        total_time = time.time() - start_time

        last_item = items[-1]
        last_metadata = last_item["metadata"]

        self._emit_progress(
            progress_callback,
            {
                "status": "finished",
                "percent": 100.0,
                "downloaded_bytes": last_metadata.get("filesize"),
                "total_bytes": last_metadata.get("filesize"),
                "speed": None,
                "eta": 0,
                "filename": last_metadata["filepath"],
                "item_index": len(downloaded_entries),
                "item_count": len(downloaded_entries),
                "item_label": last_metadata.get("title"),
            },
        )
        self._log(log_callback, "Descarga completada y metadatos guardados.")
        self._log(
            log_callback, 
            f"Tiempos - Descarga: {int(download_time)}s | Procesamiento/Conversion: {int(processing_time)}s | Total: {int(total_time)}s"
        )

        is_playlist_result = self._is_playlist_result(final_info) or len(downloaded_entries) > 1
        blocked_items = logger.blocked_items
        if is_playlist_result:
            message = (
                "Playlist completada correctamente. "
                f"Se procesaron {len(downloaded_entries)} videos y se generaron {len(items)} archivos."
            )
            if blocked_items:
                message += f" Se omitieron {len(blocked_items)} elemento(s) bloqueados."
        elif len(items) > 1:
            message = f"Descarga completada correctamente. Se generaron {len(items)} archivos."
        else:
            message = "Descarga completada correctamente."

        return {
            "success": True,
            "message": message,
            "metadata": last_metadata,
            "metadata_path": last_item["metadata_path"],
            "items": items,
            "entry_count": len(downloaded_entries),
            "is_playlist": is_playlist_result,
            "blocked_items": blocked_items,
            "download_time": download_time,
            "processing_time": processing_time,
            "total_time": total_time,
        }



    def _normalize_url(self, url: str) -> str:
        cleaned = (url or "").strip()
        if not cleaned:
            raise InvalidURLError("Ingresa una URL de YouTube o TikTok.")

        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidURLError("La URL debe iniciar con http:// o https://")

        valid_hosts = (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "music.youtube.com",
            "tiktok.com",
            "www.tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com",
        )
        if parsed.netloc.lower() not in valid_hosts:
            raise InvalidURLError("Solo se admiten URLs de YouTube o TikTok.")

        return cleaned

    def _extract_info(
        self,
        url: str,
        log_callback: LogCallback | None = None,
        download_playlist: bool = False,
        cookies_browser: str | None = None,
        extract_flat: bool = False,
    ) -> dict[str, Any]:
        logger = _CallbackLogger(log_callback)
        options = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": not download_playlist,
            "logger": logger,
            "impersonate": "chrome",
        }
        if extract_flat:
            options["extract_flat"] = "in_playlist"
        if cookies_browser:
            options["cookiesfrombrowser"] = (cookies_browser,)
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
                return ydl.sanitize_info(info)
        except DownloadError as exc:
            blocked_items = logger.blocked_items or self._blocked_items_from_message(
                str(exc),
                fallback_url=url,
            )
            raise VideoAccessError(f"No se pudo acceder al video: {exc}", blocked_items=blocked_items) from exc

    def _downloaded_entries(self, info: dict[str, Any]) -> list[dict[str, Any]]:
        if self._is_playlist_result(info):
            entries = []
            for entry in info.get("entries") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    entries.append(entry)
            return entries
        return [info] if info.get("id") else []

    def _entry_title_lookup(self, info: dict[str, Any]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for entry in self._downloaded_entries(info):
            video_id = entry.get("id")
            title = entry.get("title")
            if video_id and title:
                lookup[str(video_id)] = str(title)
        return lookup

    def _blocked_items_from_message(
        self,
        message: str,
        entry_title_lookup: dict[str, str] | None = None,
        fallback_url: str | None = None,
    ) -> list[dict[str, Any]]:
        reason = _CallbackLogger._classify_blocked_reason(message)
        if not reason:
            return []

        video_id = _CallbackLogger._extract_video_id(message) or self._extract_video_id_from_url(fallback_url)
        lookup = entry_title_lookup or {}
        title = lookup.get(video_id or "", video_id or fallback_url or "Video bloqueado")
        
        url_fallback = None
        if fallback_url:
            url_fallback = fallback_url
        elif video_id:
            url_fallback = f"https://www.tiktok.com/@e/video/{video_id}" if video_id.isdigit() else f"https://www.youtube.com/watch?v={video_id}"

        return [
            {
                "video_id": video_id,
                "title": title,
                "reason": reason,
                "detail": _CallbackLogger._normalize_message(message),
                "url": url_fallback,
            }
        ]

    def _extract_video_id_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        text = url.strip()
        match_yt = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", text)
        if match_yt:
            return match_yt.group(1)
        match_tk = re.search(r"tiktok\.com/.*/video/(\d+)", text)
        if match_tk:
            return match_tk.group(1)
        return None

    def _primary_entry_info(self, info: dict[str, Any]) -> dict[str, Any]:
        entries = self._downloaded_entries(info)
        if entries:
            return entries[0]
        if info.get("id"):
            return info
        raise VideoAccessError("No se encontro un video compatible dentro de la URL proporcionada.")

    def _enrich_reference_info(
        self,
        info: dict[str, Any],
        reference_info: dict[str, Any],
        cookies_browser: str | None,
        log_callback: LogCallback | None = None,
    ) -> dict[str, Any]:
        if self._is_playlist_result(info) and not reference_info.get("formats"):
            entries = self._downloaded_entries(info)
            for entry in entries:
                vid_url = entry.get("url") or entry.get("webpage_url")
                if not vid_url and entry.get("id"):
                    vid_url = f"https://www.tiktok.com/@e/video/{entry['id']}" if str(entry['id']).isdigit() else f"https://www.youtube.com/watch?v={entry['id']}"
                
                if vid_url:
                    self._log(log_callback, f"Consultando calidades base del video: {entry.get('title') or entry.get('id')}...")
                    try:
                        detailed_ref = self._extract_info(
                            vid_url,
                            log_callback=None,
                            download_playlist=False,
                            cookies_browser=cookies_browser,
                            extract_flat=False,
                        )
                        return self._primary_entry_info(detailed_ref)
                    except VideoAccessError:
                        self._log(log_callback, f"Aviso: Video {entry.get('id')} no accesible. Intentando con el siguiente...")
                        continue
            raise VideoAccessError("No se pudo acceder a ningun video publico de la playlist para obtener calidades.")
        return reference_info

    def _is_playlist_result(self, info: dict[str, Any]) -> bool:
        return (info.get("_type") or "").lower() == "playlist"

    def _build_video_info(
        self,
        info: dict[str, Any],
        reference_info: dict[str, Any],
        normalized_url: str,
    ) -> dict[str, Any]:
        video_id = reference_info.get("id")
        existing_artifacts = self._existing_artifacts(video_id) if video_id else []
        duplicate_ignored = self._should_ignore_duplicate(video_id)
        best_audio_source = self._safe_best_audio_source(reference_info)
        is_playlist = self._is_playlist_result(info)
        playlist_entries = self._downloaded_entries(info)
        playlist_count = info.get("playlist_count")
        if not playlist_count and is_playlist:
            playlist_count = len(playlist_entries)
        return {
            "id": video_id,
            "title": reference_info.get("title") or "Sin titulo",
            "webpage_url": reference_info.get("webpage_url") or normalized_url,
            "uploader": reference_info.get("uploader") or "Desconocido",
            "duration": reference_info.get("duration"),
            "thumbnail": reference_info.get("thumbnail"),
            "thumbnail_url": self._best_thumbnail(reference_info),
            "is_duplicate": bool(existing_artifacts and not duplicate_ignored),
            "duplicate_ignored": bool(existing_artifacts and duplicate_ignored),
            "metadata_path": existing_artifacts[0]["metadata_path"] if existing_artifacts else None,
            "existing_artifacts": existing_artifacts,
            "has_legacy_video_record": any(item.get("is_legacy") for item in existing_artifacts),
            "best_audio_source": best_audio_source,
            "is_playlist": is_playlist,
            "playlist_title": info.get("title") if is_playlist else None,
            "playlist_count": playlist_count if is_playlist else 1,
        }

    def _build_download_options(
        self,
        selected_format_expression: str,
        mode: str,
        logger: _CallbackLogger,
        hooks: list[Callable[[dict[str, Any]], None]],
        allow_redownload: bool,
        podcast_format: str,
        download_playlist: bool,
        cookies_browser: str | None = None,
        file_organization: str = "Sin subcarpetas",
        embed_subtitles: bool = False,
    ) -> dict[str, Any]:
        if file_organization == "Agrupar por Canal":
            outtmpl = "%(uploader)s/%(title).200B.%(ext)s"
        elif file_organization == "Agrupar por Playlist":
            outtmpl = "%(playlist_title)s/%(title).200B.%(ext)s"
        else:
            outtmpl = "%(title).200B.%(ext)s"
            
        options: dict[str, Any] = {
            "format": selected_format_expression,
            "outtmpl": outtmpl,
            "quiet": True,
            "noprogress": True,
            "logger": logger,
            "impersonate": "chrome",
            "progress_hooks": hooks,
            "restrictfilenames": False,
            "noplaylist": not download_playlist,
            "continuedl": not allow_redownload,
            "ignoreerrors": "only_download" if download_playlist else False,
            "retries": 10,
            "fragment_retries": 20,
            "file_access_retries": 5,
            "socket_timeout": 30,
            "paths": {
                "home": str(self.download_dir),
                "temp": str(self.temp_dir),
            },
        }
        
        if cookies_browser:
            options["cookiesfrombrowser"] = (cookies_browser,)

        if allow_redownload:
            options["overwrites"] = True

        normalized_mode = (mode or "").strip().lower()
        if normalized_mode == DownloadMode.KAIOKEN:
            options.update(
                {
                    "concurrent_fragment_downloads": 8,
                    "buffersize": 16 << 20,
                    "http_chunk_size": 10 << 20,
                    "merge_output_format": "mkv",
                }
            )
        elif normalized_mode == DownloadMode.PODCAST:
            options.update(
                {
                    "concurrent_fragment_downloads": 4,
                }
            )
        elif normalized_mode == DownloadMode.STANDARD:
            options["merge_output_format"] = "mkv"

        return options

    def _quality_options_from_info(self, info: dict[str, Any]) -> list[dict[str, Any]]:
        seen: dict[tuple[int, int, str], dict[str, Any]] = {}
        best_audio_size = self._best_audio_size(info)

        for fmt in info.get("formats", []):
            if not self._is_video_format(fmt):
                continue

            height = fmt.get("height") or 0
            fps = fmt.get("fps") or 0
            tbr = fmt.get("tbr") or 0
            ext = fmt.get("ext") or "desconocido"
            vcodec = fmt.get("vcodec") or "video"
            note = fmt.get("format_note") or ""
            is_progressive = fmt.get("acodec") not in (None, "none")
            merge_required = not is_progressive

            label = f"{height}p"
            if fps:
                label += f" {fps}fps"
            label += f" - {ext}"
            if note:
                label += f" - {note}"
            if is_progressive:
                label += " - audio integrado"
            else:
                label += " - requiere fusion"

            item = {
                "format_id": fmt["format_id"],
                "ext": ext,
                "height": height,
                "width": fmt.get("width") or 0,
                "fps": fps,
                "tbr": tbr,
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx") or 0,
                "estimated_total_size": (fmt.get("filesize") or fmt.get("filesize_approx") or 0)
                + (best_audio_size if merge_required else 0),
                "display_label": label,
                "is_progressive": is_progressive,
                "merge_required": merge_required,
                "vcodec": vcodec,
                "raw": fmt,
            }
            key = (height, fps, ext)
            current = seen.get(key)
            if current is None or self._quality_sort_key(item) > self._quality_sort_key(current):
                seen[key] = item

        candidates = sorted(seen.values(), key=self._quality_sort_key, reverse=True)
        if not candidates:
            raise NoFormatsAvailableError(
                "No se encontraron formatos de video compatibles para este contenido."
            )
        return candidates

    def _resolve_format(
        self,
        info: dict[str, Any],
        mode: str,
        format_id: str | None,
        podcast_format: str = PodcastFormat.MP3,
    ) -> tuple[str, dict[str, Any]]:
        normalized_mode = (mode or "").strip().lower()
        if normalized_mode == DownloadMode.PODCAST:
            audio_format = self._select_best_audio_format(info, podcast_format)
            return audio_format["format_id"], audio_format

        quality_options = self._quality_options_from_info(info)
        if normalized_mode == DownloadMode.KAIOKEN:
            selected = quality_options[0]
            return self._build_video_audio_expression(selected), selected

        if normalized_mode != DownloadMode.STANDARD:
            raise YoutubeEngineError(f"Modo de descarga no soportado: {mode}")

        if not format_id:
            raise NoFormatsAvailableError("Selecciona una calidad antes de iniciar la descarga.")

        for fmt in quality_options:
            if fmt["format_id"] == format_id:
                return self._build_video_audio_expression(fmt), fmt

        raise NoFormatsAvailableError(
            "La calidad seleccionada ya no esta disponible para este video."
        )

    def _build_video_audio_expression(self, selected_format: dict[str, Any]) -> str:
        video_format_id = selected_format["format_id"]
        if not selected_format.get("merge_required"):
            return video_format_id
        return f"{video_format_id}+bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"

    def _select_best_audio_format(
        self,
        info: dict[str, Any],
        podcast_format: str = PodcastFormat.MP3,
    ) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for fmt in info.get("formats", []):
            acodec = fmt.get("acodec")
            if acodec in (None, "none"):
                continue

            vcodec = fmt.get("vcodec")
            if vcodec not in (None, "none"):
                continue

            abr = fmt.get("abr") or 0
            tbr = fmt.get("tbr") or 0
            filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            ext = fmt.get("ext") or "desconocido"
            candidates.append(
                {
                    "format_id": fmt["format_id"],
                    "ext": ext,
                    "abr": abr,
                    "tbr": tbr,
                    "filesize": filesize,
                    "display_label": f"Audio fuente {ext} -> {self._podcast_label(podcast_format)}",
                    "raw": fmt,
                }
            )

        if not candidates:
            raise NoFormatsAvailableError(
                "No se encontro un formato de audio directo compatible para modo Podcast."
            )

        candidates.sort(
            key=lambda item: (
                item.get("abr", 0),
                item.get("tbr", 0),
                item.get("filesize", 0),
            ),
            reverse=True,
        )
        return candidates[0]

    def _safe_best_audio_source(self, info: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._select_best_audio_format(info, PodcastFormat.MP3)
        except NoFormatsAvailableError:
            return None

    def _best_audio_size(self, info: dict[str, Any]) -> int:
        audio = self._safe_best_audio_source(info)
        if not audio:
            return 0
        return int(audio.get("filesize") or 0)

    def _ensure_not_duplicate(
        self,
        info: dict[str, Any],
        artifact_keys: list[str],
        allow_redownload: bool = False,
    ) -> None:
        if allow_redownload:
            return

        duplicates: list[tuple[str, list[str]]] = []
        for entry in self._downloaded_entries(info):
            video_id = entry.get("id")
            if not video_id:
                continue
            if self._should_ignore_duplicate(video_id):
                continue

            existing_keys: set[str] = set()
            for metadata in self._load_existing_metadata(video_id):
                artifact_key = metadata.get("artifact_key")
                if not artifact_key:
                    is_podcast = metadata.get("mode") == DownloadMode.PODCAST
                    artifact_key = "podcast_legacy" if is_podcast else "video_legacy"
                existing_keys.add(artifact_key)

            colliding = sorted(set(artifact_keys) & existing_keys)
            if colliding:
                duplicates.append((entry.get("title") or video_id, colliding))

        if not duplicates:
            return

        if len(duplicates) == 1:
            title, colliding = duplicates[0]
            joined = ", ".join(colliding)
            raise DuplicateVideoError(
                f"Ya existe una descarga registrada para {title} ({joined})."
            )

        preview = "; ".join(
            f"{title} ({', '.join(colliding)})"
            for title, colliding in duplicates[:3]
        )
        if len(duplicates) > 3:
            preview += " ..."
        raise DuplicateVideoError(
            f"Se encontraron {len(duplicates)} elementos de la playlist ya registrados: {preview}"
        )

    def _should_ignore_duplicate(self, video_id: str | None) -> bool:
        return bool(video_id and video_id in RESETTABLE_DUPLICATE_IDS)

    def _best_thumbnail(self, info: dict[str, Any]) -> str | None:
        thumbnails = info.get("thumbnails") or []
        if thumbnails:
            best = max(
                thumbnails,
                key=lambda item: (
                    item.get("width") or 0,
                    item.get("height") or 0,
                ),
            )
            return best.get("url")
        return info.get("thumbnail")

    def _metadata_path(self, video_id: str, artifact_key: str | None = None) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", video_id)
        if artifact_key:
            safe_artifact = re.sub(r"[^A-Za-z0-9_-]", "_", artifact_key)
            return self.metadata_dir / f"{safe_id}__{safe_artifact}.json"
        return self.metadata_dir / f"{safe_id}.json"

    def _build_metadata(
        self,
        info: dict[str, Any],
        mode: str,
        format_id: str,
        filepath: Path,
        artifact_key: str,
        selected_format: dict[str, Any],
    ) -> dict[str, Any]:
        requested = info.get("requested_downloads") or []
        selected = requested[0] if requested else {}
        estimated_filesize = (
            selected.get("filesize")
            or selected.get("filesize_approx")
            or info.get("filesize")
            or info.get("filesize_approx")
        )
        actual_size = filepath.stat().st_size if filepath.exists() else estimated_filesize
        probe = self._probe_media(filepath)
        format_probe = probe.get("format") or {}
        audio_probe = probe.get("audio") or {}
        video_probe = probe.get("video") or {}

        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "webpage_url": info.get("webpage_url"),
            "mode": mode,
            "format_id": format_id,
            "artifact_key": artifact_key,
            "ext": filepath.suffix.lstrip(".") or info.get("ext") or selected.get("ext"),
            "source_ext": selected_format.get("ext") or selected.get("ext"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail_url": self._best_thumbnail(info),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "filepath": str(filepath),
            "filesize": actual_size,
            "estimated_filesize": estimated_filesize,
            "quality_label": selected_format.get("display_label"),
            "height": selected_format.get("height"),
            "fps": selected_format.get("fps"),
            "container_bitrate": self._safe_int(format_probe.get("bit_rate")),
            "final_duration": self._safe_float(format_probe.get("duration")) or info.get("duration"),
            "audio_codec": audio_probe.get("codec_name"),
            "audio_bitrate": self._safe_int(audio_probe.get("bit_rate")),
            "audio_sample_rate": self._safe_int(audio_probe.get("sample_rate")),
            "audio_channels": self._safe_int(audio_probe.get("channels")),
            "video_codec": video_probe.get("codec_name"),
            "video_bitrate": self._safe_int(video_probe.get("bit_rate")),
            "video_width": self._safe_int(video_probe.get("width")),
            "video_height": self._safe_int(video_probe.get("height")),
            "video_fps": self._parse_fps(video_probe.get("avg_frame_rate") or video_probe.get("r_frame_rate")),
        }

    def _build_artifact_key(
        self,
        mode: str,
        selected_format: dict[str, Any],
        podcast_format: str,
    ) -> str:
        return self._artifact_keys_for_selection(mode, selected_format, podcast_format)[0]

    def _artifact_keys_for_selection(
        self,
        mode: str,
        selected_format: dict[str, Any],
        podcast_format: str,
    ) -> list[str]:
        normalized_mode = (mode or "").strip().lower()
        if normalized_mode == DownloadMode.PODCAST:
            return [f"podcast_{target}" for target in self._podcast_target_formats(podcast_format)]

        height = selected_format.get("height") or 0
        fps = selected_format.get("fps") or 0
        ext = (selected_format.get("ext") or "bin").lower()
        quality_bits = [f"{height}p" if height else "video"]
        if fps:
            quality_bits.append(f"{fps}fps")
        quality_bits.append(ext)
        return ["video_" + "_".join(quality_bits)]

    def _load_existing_metadata(self, video_id: str | None) -> list[dict[str, Any]]:
        if not video_id:
            return []

        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", video_id)
        metadata_entries: list[dict[str, Any]] = []
        seen_paths: set[Path] = set()
        for directory in (self.metadata_dir, self.download_dir):
            for metadata_path in sorted(directory.glob(f"{safe_id}*.json")):
                resolved_path = metadata_path.resolve()
                if resolved_path in seen_paths:
                    continue
                seen_paths.add(resolved_path)

                try:
                    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                
                filepath_str = raw.get("filepath")
                if filepath_str:
                    target_file = Path(filepath_str)
                    if not target_file.exists():
                        try:
                            metadata_path.unlink()
                        except OSError:
                            pass
                        continue

                raw["_metadata_path"] = str(metadata_path)
                raw["_is_legacy"] = metadata_path.parent != self.metadata_dir
                metadata_entries.append(raw)

        return metadata_entries

    def _existing_artifacts(self, video_id: str | None) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for metadata in self._load_existing_metadata(video_id):
            artifact_key = metadata.get("artifact_key")
            if not artifact_key:
                is_podcast = metadata.get("mode") == DownloadMode.PODCAST
                artifact_key = "podcast_legacy" if is_podcast else "video_legacy"

            label = metadata.get("quality_label")
            if not label:
                if artifact_key.startswith("podcast_"):
                    label = f"Podcast {artifact_key.split('_', 1)[-1].upper()}"
                else:
                    ext = metadata.get("ext") or "desconocido"
                    label = f"Video legado ({ext})"

            artifacts.append(
                {
                    "artifact_key": artifact_key,
                    "label": label,
                    "mode": metadata.get("mode"),
                    "filepath": metadata.get("filepath"),
                    "metadata_path": metadata.get("_metadata_path"),
                    "downloaded_at": metadata.get("downloaded_at"),
                    "is_legacy": bool(metadata.get("_is_legacy")),
                }
            )

        return artifacts

    def _prepare_filepath(self, info: dict[str, Any]) -> Path:
        filepath = info.get("filepath")
        if filepath:
            return Path(filepath).resolve()

        requested = info.get("requested_downloads") or []
        if requested:
            filepath = requested[-1].get("filepath")
            if filepath:
                return Path(filepath).resolve()

        filename = info.get("_filename")
        if filename:
            return Path(filename).resolve()

        title = info.get("title") or "video"
        ext = info.get("ext") or "bin"
        fallback_name = f"{title}.{ext}"
        return (self.download_dir / fallback_name).resolve()

    def _finalize_entry_download(
        self,
        info: dict[str, Any],
        mode: str,
        format_id: str,
        selected_format: dict[str, Any],
        podcast_format: str,
        allow_redownload: bool,
        log_callback: LogCallback | None = None,
    ) -> list[dict[str, Any]]:
        source_path = self._prepare_filepath(info)
        output_items: list[dict[str, Any]]

        if (mode or "").strip().lower() == DownloadMode.PODCAST:
            output_items = self._process_podcast_outputs(
                source_path,
                podcast_format=podcast_format,
                allow_redownload=allow_redownload,
                log_callback=log_callback,
            )
        else:
            output_items = [
                {
                    "artifact_key": self._build_artifact_key(mode, selected_format, podcast_format),
                    "filepath": source_path,
                }
            ]

        results: list[dict[str, Any]] = []
        for output_item in output_items:
            metadata = self._build_metadata(
                info,
                mode,
                format_id,
                output_item["filepath"],
                artifact_key=output_item["artifact_key"],
                selected_format=selected_format,
            )
            metadata_path = self._metadata_path(metadata["id"], artifact_key=output_item["artifact_key"])
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append(
                {
                    "metadata": metadata,
                    "metadata_path": str(metadata_path),
                }
            )

        self._cleanup_temp_files(info.get("id"))
        return results

    def _process_podcast_outputs(
        self,
        source_path: Path,
        podcast_format: str,
        allow_redownload: bool,
        log_callback: LogCallback | None = None,
    ) -> list[dict[str, Any]]:
        target_formats = self._podcast_target_formats(podcast_format)
        source_ext = source_path.suffix.lstrip(".").lower()
        output_items: list[dict[str, Any]] = []

        for target_format in target_formats:
            output_path = source_path.with_suffix(f".{target_format}")
            if source_ext != target_format:
                self._convert_audio_file(
                    source_path,
                    output_path,
                    allow_redownload=allow_redownload,
                    log_callback=log_callback,
                )
            output_items.append(
                {
                    "artifact_key": f"podcast_{target_format}",
                    "filepath": output_path if source_ext != target_format else source_path,
                }
            )

        if source_path.exists() and source_ext not in target_formats:
            try:
                source_path.unlink()
            except OSError:
                pass

        return output_items

    def _convert_audio_file(
        self,
        source_path: Path,
        output_path: Path,
        allow_redownload: bool,
        log_callback: LogCallback | None = None,
    ) -> None:
        if not source_path.exists():
            raise YoutubeEngineError(f"No se encontro el archivo fuente para convertir: {source_path}")

        ext = output_path.suffix.lower()
        command = [
            "ffmpeg",
            "-y" if allow_redownload else "-n",
            "-i",
            str(source_path),
            "-vn",
            "-threads", "0",
        ]
        if ext == ".mp3":
            command.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
        elif ext == ".wav":
            command.extend(["-c:a", "pcm_s16le"])
        else:
            raise YoutubeEngineError(f"Formato de salida no soportado para podcast: {output_path.suffix}")
        command.append(str(output_path))

        self._log(log_callback, f"Convirtiendo audio a {output_path.suffix.lower().lstrip('.').upper()}...")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise YoutubeEngineError(f"No se pudo convertir el audio con FFmpeg: {exc}") from exc

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip()
            raise YoutubeEngineError(
                f"FFmpeg no pudo generar {output_path.name}: {error_text or 'sin detalle adicional'}"
            )

    def _podcast_target_formats(self, podcast_format: str) -> list[str]:
        normalized = (podcast_format or "").strip().lower()
        if normalized == PodcastFormat.BOTH:
            return [PodcastFormat.MP3, PodcastFormat.WAV]
        if normalized in {PodcastFormat.MP3, PodcastFormat.WAV}:
            return [normalized]
        raise YoutubeEngineError(f"Formato de podcast no soportado: {podcast_format}")

    def _podcast_label(self, podcast_format: str) -> str:
        normalized = (podcast_format or "").strip().lower()
        if normalized == PodcastFormat.BOTH:
            return "MP3 y WAV"
        return normalized.upper()

    def _probe_media(self, filepath: Path) -> dict[str, Any]:
        if not filepath.exists():
            return {}

        command = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(filepath),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {}

        if result.returncode != 0:
            return {}

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return {}

        streams = payload.get("streams") or []
        return {
            "format": payload.get("format") or {},
            "video": next((stream for stream in streams if stream.get("codec_type") == "video"), {}),
            "audio": next((stream for stream in streams if stream.get("codec_type") == "audio"), {}),
        }

    def _safe_int(self, value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_fps(self, value: Any) -> float | None:
        if not value or value == "0/0":
            return None
        try:
            return round(float(Fraction(str(value))), 2)
        except (ValueError, ZeroDivisionError):
            return None

    def _cleanup_temp_files(self, video_id: str | None) -> None:
        if not video_id or not self.temp_dir.exists():
            return

        patterns = [
            f"*{video_id}*.part",
            f"*{video_id}*.ytdl",
            f"*{video_id}*.f*",
        ]
        for pattern in patterns:
            for temp_file in self.temp_dir.glob(pattern):
                try:
                    temp_file.unlink()
                except OSError:
                    continue

    def _build_progress_hook(
        self,
        progress_callback: ProgressCallback | None,
        log_callback: LogCallback | None,
    ) -> Callable[[dict[str, Any]], None]:
        state: dict[str, Any] = {
            "last_status": None,
            "last_logged_percent": -10,
            "last_filename": None,
        }

        def hook(update: dict[str, Any]) -> None:
            status = update.get("status")
            percent = self._extract_percent(update)
            total_bytes = update.get("total_bytes") or update.get("total_bytes_estimate")
            downloaded_bytes = update.get("downloaded_bytes") or 0
            filename = update.get("filename")
            info_dict = update.get("info_dict") or {}
            item_index = self._safe_int(info_dict.get("playlist_index"))
            item_count = self._safe_int(info_dict.get("n_entries") or info_dict.get("playlist_count"))
            item_label = info_dict.get("title")

            if filename and filename != state["last_filename"]:
                state["last_filename"] = filename
                state["last_status"] = None
                state["last_logged_percent"] = -10
                readable_label = item_label or Path(filename).stem
                if item_count and item_count > 1 and item_index:
                    self._log(
                        log_callback,
                        f"Procesando elemento {item_index}/{item_count}: {readable_label}",
                    )
                elif readable_label:
                    self._log(log_callback, f"Procesando: {readable_label}")

            payload = {
                "status": status,
                "percent": percent,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": total_bytes,
                "speed": update.get("speed"),
                "eta": update.get("eta"),
                "filename": filename,
                "item_index": item_index,
                "item_count": item_count,
                "item_label": item_label or (Path(filename).stem if filename else None),
            }
            self._emit_progress(progress_callback, payload)

            if status != state["last_status"]:
                state["last_status"] = status
                readable_status = {
                    "downloading": "Descargando...",
                    "finished": "Fusionando y finalizando archivo...",
                }.get(status, f"Estado: {status}")
                self._log(log_callback, readable_status)

            if status == "downloading" and percent >= state["last_logged_percent"] + 10:
                state["last_logged_percent"] = int(percent // 10) * 10
                self._log(log_callback, f"Avance aproximado: {percent:.1f}%")

        return hook

    def _extract_percent(self, update: dict[str, Any]) -> float:
        total_bytes = update.get("total_bytes") or update.get("total_bytes_estimate")
        downloaded_bytes = update.get("downloaded_bytes") or 0
        if total_bytes:
            return round(downloaded_bytes / total_bytes * 100, 2)

        percent_str = (update.get("_percent_str") or "").strip()
        if percent_str.endswith("%"):
            try:
                return float(percent_str[:-1].strip())
            except ValueError:
                return 0.0

        if update.get("status") == "finished":
            return 100.0
        return 0.0

    def _is_video_format(self, fmt: dict[str, Any]) -> bool:
        vcodec = fmt.get("vcodec")
        height = fmt.get("height") or 0
        protocol = (fmt.get("protocol") or "").lower()
        if vcodec in (None, "none"):
            return False
        if height <= 0:
            return False
        if protocol.startswith("m3u8"):
            return False
        return True

    def _quality_sort_key(self, fmt: dict[str, Any]) -> tuple[Any, ...]:
        return (
            fmt.get("height") or 0,
            fmt.get("fps") or 0,
            1 if fmt.get("merge_required") else 0,
            fmt.get("tbr") or 0,
            fmt.get("filesize") or 0,
        )

    def _emit_progress(self, progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
        if progress_callback is not None:
            progress_callback(payload)

    def _log(self, log_callback: LogCallback | None, message: str) -> None:
        if log_callback is not None:
            log_callback(message)
