"""
视频/图片下载引擎 —— 基于 yt-dlp 封装。
粘贴链接即可下载，无需额外操作。
"""

import os
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

import yt_dlp

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_AGE = 3600  # 1 小时后自动清理

# ─── 任务管理 ────────────────────────────────────────

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _find_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    return None


def cleanup_old_files():
    now = time.time()
    if not DOWNLOAD_DIR.exists():
        return
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > MAX_FILE_AGE:
            try:
                f.unlink()
            except OSError:
                pass


def _base_opts() -> dict:
    """所有 yt-dlp 调用的公共选项：浏览器伪装 + ffmpeg。"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "windowsfilenames": True,
        "extractor_retries": 2,
    }
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    return opts


# ─── 信息提取 ──────────────────────────────────────────


def _extract_info(opts: dict, url: str) -> dict:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def get_info(url: str) -> dict:
    """解析链接，返回视频/图片信息。Instagram 图片帖自动用 /media/ 端点。"""
    opts = _base_opts()
    opts["extract_flat"] = False

    urls_to_try = [url]

    # Instagram: 如果直链失败，自动尝试 embed 链接
    is_instagram = "instagram.com" in url.lower()
    ig_post_id = None
    if is_instagram:
        import re
        match = re.search(r'instagram\.com/(?:p|reel|tv)/([^/?]+)', url)
        if match:
            ig_post_id = match.group(1)
            urls_to_try.append(f"https://www.instagram.com/p/{ig_post_id}/embed/")

    last_error = None
    for try_url in urls_to_try:
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_extract_info, opts, try_url)
                info = future.result(timeout=20)
                return _sanitize_info(info)
        except FutureTimeoutError:
            last_error = DownloaderError("解析超时，请检查链接后重试", code="TIMEOUT")
        except yt_dlp.utils.DownloadError as e:
            msg = str(e).lower()
            # Instagram 纯图片帖：自动切换到 /media/ 端点
            if "no video" in msg and ig_post_id:
                return _get_instagram_image(ig_post_id)
            # Twitter/X 纯图片帖：自动使用 fxtwitter API
            if "no video" in msg and ("twitter" in url.lower() or "x.com" in url.lower()):
                tweet_info = _get_twitter_image(url)
                if tweet_info:
                    return tweet_info
            last_error = _map_error(e)
        except Exception as e:
            last_error = DownloaderError(f"解析失败：{e}", code="NETWORK_ERROR")

    raise last_error


def _get_instagram_image(post_id: str) -> dict:
    """通过 Instagram /media/ 端点获取图片 + 页面 meta 标签提取文案（无需登录）。"""
    import requests as req
    import re

    # 1. 下载图片（模拟手机端 User-Agent，绕过风控）
    img_url = f"https://www.instagram.com/p/{post_id}/media/?size=l"
    img_data = None
    ua_list = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]
    last_error = None
    for ua in ua_list:
        try:
            resp = req.get(img_url, timeout=15, headers={"User-Agent": ua})
            if resp.status_code == 200 and "image" in resp.headers.get("Content-Type", ""):
                img_data = resp.content
                break
        except Exception as e:
            last_error = e
            continue

    if img_data is None:
        raise DownloaderError(
            f"无法获取该 Instagram 图片（{last_error or '帖子可能不存在或为私密'}）",
            code="NOT_FOUND"
        )

    img_filename = f"ig_{post_id}.jpg"
    img_path = DOWNLOAD_DIR / img_filename
    img_path.write_bytes(img_data)
    thumbnail = f"/api/preview/{img_filename}"  # 本地预览 URL，绕过 CDN 防盗链

    # 2. 从页面 meta 标签提取文案（尽力而为，失败不影响图片下载）
    caption = ""
    uploader = ""
    try:
        page_url = f"https://www.instagram.com/p/{post_id}/"
        page_resp = req.get(page_url, timeout=10, headers={
            "User-Agent": ua_list[0],  # 用手机端 UA
        })
        html = page_resp.text

        # og:image 仅用于调试，实际预览用本地路径绕过防盗链
        og_img = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if og_img:
            pass  # 已使用本地 /api/preview/ URL，不需要 CDN 地址

        # og:description 格式: "X likes, Y comments - username on date: \"caption\""
        og_desc = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
        if og_desc:
            desc = og_desc.group(1)
            import html as html_mod
            desc = html_mod.unescape(desc)
            parts = desc.split(": ", 1)
            if len(parts) > 1:
                caption = parts[1].strip('"').rstrip('."').strip()
            og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            if og_title:
                title_text = html_mod.unescape(og_title.group(1))
                user_match = re.match(r'(.+?)\s+on Instagram', title_text)
                if user_match:
                    uploader = user_match.group(1)
    except Exception:
        pass  # 文案获取失败不影响图片下载

    # 3. 保存文案
    _save_description(img_path, {
        "title": caption or f"Instagram 图片 - {post_id}",
        "uploader": uploader,
        "description": caption,
        "webpage_url": f"https://www.instagram.com/p/{post_id}/",
    })

    return {
        "id": post_id,
        "title": caption or f"Instagram 图片 - {post_id}",
        "thumbnail": thumbnail,
        "duration": 0,
        "duration_str": "",
        "uploader": uploader,
        "platform": "Instagram",
        "webpage_url": f"https://www.instagram.com/p/{post_id}/",
        "description": caption,
        "formats": [{
            "format_id": "original",
            "ext": "jpg",
            "resolution": "原图",
            "filesize": len(img_data),
            "filesize_str": _format_size(len(img_data)),
            "note": "图片",
            "has_video": True,
            "has_audio": False,
            "type_label": "图片",
        }],
        "_is_image": True,
        "_image_path": str(img_path),
    }


def _get_twitter_image(url: str) -> dict | None:
    """通过 fxtwitter API 获取 X/Twitter 图片帖（无需登录）。"""
    import requests as req
    import re

    # 从 URL 提取用户名和 tweet ID
    match = re.search(r'(?:twitter\.com|x\.com)/(\w+)/status/(\d+)', url)
    if not match:
        return None
    screen_name, tweet_id = match.group(1), match.group(2)

    api_url = f"https://api.fxtwitter.com/{screen_name}/status/{tweet_id}"
    try:
        resp = req.get(api_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        if resp.status_code != 200:
            return None
        data = resp.json()
        tweet = data.get("tweet", {})
        photos = tweet.get("media", {}).get("photos", []) if tweet.get("media") else []
        if not photos:
            return None

        # 下载第一张图片
        img_url = photos[0].get("url", "")
        if not img_url:
            return None

        img_resp = req.get(img_url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        if img_resp.status_code != 200:
            return None

        img_data = img_resp.content
        ext = img_url.split(".")[-1].split("?")[0] or "jpg"
        img_filename = f"tw_{tweet_id}.{ext}"
        img_path = DOWNLOAD_DIR / img_filename
        img_path.write_bytes(img_data)
        thumbnail = f"/api/preview/{img_filename}"  # 本地预览
        tweet_text = tweet.get("text", "")
        _save_description(img_path, {
            "title": tweet_text[:100] if tweet_text else f"X 图片 - {tweet_id}",
            "uploader": screen_name,
            "description": tweet_text,
            "webpage_url": url,
        })

        return {
            "id": tweet_id,
            "title": tweet.get("text", f"X 图片 - {tweet_id}")[:100],
            "thumbnail": thumbnail,  # 本地预览 URL，绕过 CDN 防盗链
            "duration": 0,
            "duration_str": "",
            "uploader": screen_name,
            "platform": "Twitter/X",
            "webpage_url": url,
            "formats": [{
                "format_id": "original",
                "ext": ext,
                "resolution": "原图",
                "filesize": len(img_data),
                "filesize_str": _format_size(len(img_data)),
                "note": "图片",
                "has_video": True,
                "has_audio": False,
                "type_label": "图片",
            }],
            "_is_image": True,
            "_image_path": str(img_path),
        }
    except Exception:
        return None


# ─── 异步下载 ──────────────────────────────────────────


def start_download(url: str, format_id: str = "best", image_path: str = "") -> str:
    """启动后台下载任务，立即返回 task_id。图片帖直接返回已保存的文件。"""
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "status": "starting",
        "progress": 0.0,
        "speed": "",
        "eta": "",
        "downloaded": "",
        "total": "",
        "filename": "",
        "filepath": "",
        "error": "",
        "created_at": time.time(),
    }
    with _tasks_lock:
        _tasks[task_id] = task

    if image_path and os.path.exists(image_path):
        # 图片帖：文件已在 get_info 阶段下载好了，直接标记完成
        task["status"] = "done"
        task["progress"] = 100.0
        task["filepath"] = image_path
        task["filename"] = Path(image_path).name
    else:
        thread = threading.Thread(target=_run_download, args=(task_id, url, format_id), daemon=True)
        thread.start()
    return task_id


def get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def _run_download(task_id: str, url: str, format_id: str):
    task = _tasks[task_id]
    cleanup_old_files()

    has_ffmpeg = _find_ffmpeg() is not None
    default_fmt = (
        "bv[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
    ) if has_ffmpeg else "b[ext=mp4]/b"

    def progress_hook(d):
        status = d.get("status", "")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total > 0 else 0
            task["status"] = "downloading"
            task["progress"] = round(pct, 1)
            task["speed"] = d.get("_speed_str", "")
            task["eta"] = d.get("_eta_str", "")
            task["downloaded"] = _format_size(downloaded) if downloaded else ""
            task["total"] = _format_size(total) if total else ""
        elif status == "finished":
            task["status"] = "merging"
            task["progress"] = 95.0

    opts = _base_opts()
    opts.update({
        "outtmpl": str(DOWNLOAD_DIR / "%(title).100s_%(id)s.%(ext)s"),
        "format": format_id if format_id != "best" else default_fmt,
        "merge_output_format": "mp4",
        "progress_hooks": [progress_hook],
        "socket_timeout": 120,
        "retries": 3,
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            # 保存配套文案
            _save_description(filepath, info)
            task["status"] = "done"
            task["progress"] = 100.0
            task["filepath"] = str(filepath)
            task["filename"] = Path(filepath).name
    except yt_dlp.utils.DownloadError as e:
        task["status"] = "error"
        task["error"] = _map_error(e).user_message
    except Exception as e:
        task["status"] = "error"
        task["error"] = f"下载失败：{e}"


# ─── 错误映射 ──────────────────────────────────────────


def _map_error(e: yt_dlp.utils.DownloadError) -> "DownloaderError":
    msg = str(e).lower()
    if "private" in msg or "unavailable" in msg or "deleted" in msg:
        return DownloaderError("视频不存在或已被删除", code="NOT_FOUND")
    if "georestrict" in msg or "country" in msg:
        return DownloaderError("该内容在您所在地区不可用", code="GEO_RESTRICTED")
    if "unsupported" in msg or "not supported" in msg:
        return DownloaderError("暂不支持该平台", code="UNSUPPORTED")
    # Instagram 图片帖回退：用 /media/ 端点（无需登录）
    if "login" in msg or "cookie" in msg or "dpapi" in msg:
        return DownloaderError("该平台需要登录才能访问。YouTube/B站/Reddit 等无需登录", code="LOGIN_REQUIRED")
    if "signature" in msg or "verify" in msg or "captcha" in msg:
        return DownloaderError("平台风控拦截，请稍后重试", code="ANTI_BOT")
    return DownloaderError(f"解析失败：{e}", code="PARSE_ERROR")


def _save_description(filepath, info: dict):
    """下载完成后，在同目录保存一份文案 txt 文件。"""
    if isinstance(filepath, str):
        filepath = Path(filepath)

    title = info.get("title", "")
    uploader = info.get("uploader", "") or info.get("channel", "") or ""
    description = (
        info.get("description") or
        info.get("full_text") or
        info.get("caption") or
        ""
    )
    webpage_url = info.get("webpage_url", "")

    if not title and not description:
        return

    txt_path = filepath.with_suffix(".txt")
    lines = []
    if title:
        lines.append(title)
    if uploader:
        lines.append(f"作者：{uploader}")
    if description:
        lines.append("")
        lines.append(description)
    if webpage_url:
        lines.append("")
        lines.append(f"来源：{webpage_url}")

    try:
        txt_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass  # 文案保存失败不影响主流程


# ─── 格式清洗 ──────────────────────────────────────────


def _sanitize_info(info: dict) -> dict:
    formats = []
    seen = set()
    for fmt in info.get("formats", []) or []:
        fid = fmt.get("format_id", "")
        if fid in seen:
            continue
        seen.add(fid)
        ext = fmt.get("ext", "")
        if ext in ("mhtml", "m3u8", ""):
            continue
        has_video = bool(fmt.get("vcodec") and fmt.get("vcodec") != "none")
        has_audio = bool(fmt.get("acodec") and fmt.get("acodec") != "none")
        resolution = fmt.get("resolution") or fmt.get("format_note") or ""
        filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        type_label = ""
        if has_video and has_audio:
            type_label = "视频+音频"
        elif has_video:
            type_label = "仅视频"
        elif has_audio:
            type_label = "仅音频"
        formats.append({
            "format_id": fid, "ext": ext, "resolution": resolution,
            "filesize": filesize,
            "filesize_str": _format_size(filesize) if filesize else "未知大小",
            "note": fmt.get("format_note", ""),
            "has_video": has_video, "has_audio": has_audio, "type_label": type_label,
        })

    video_formats = [f for f in formats if f["has_video"]]
    video_formats.sort(key=lambda f: f["filesize"], reverse=True)

    if video_formats:
        video_formats.insert(0, {
            "format_id": "best", "ext": "mp4", "resolution": "最佳画质（自动）",
            "filesize": 0, "filesize_str": "自动选择", "note": "推荐",
            "has_video": True, "has_audio": True, "type_label": "智能",
        })
    else:
        video_formats.append({
            "format_id": "best", "ext": "mp4", "resolution": "默认画质",
            "filesize": 0, "filesize_str": "未知大小", "note": "默认",
            "has_video": True, "has_audio": True, "type_label": "",
        })

    description = (
        info.get("description") or
        info.get("full_text") or
        info.get("caption") or
        ""
    )

    return {
        "id": info.get("id", ""),
        "title": info.get("title", "未知标题"),
        "thumbnail": info.get("thumbnail", ""),
        "duration": int(info.get("duration", 0) or 0),
        "duration_str": _format_duration(int(info.get("duration", 0) or 0)),
        "uploader": info.get("uploader", "") or info.get("channel", "") or "",
        "platform": info.get("extractor_key", ""),
        "webpage_url": info.get("webpage_url", ""),
        "description": description,
        "formats": video_formats,
    }


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "00:00"
    h, m = divmod(int(seconds), 3600)
    m, s = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class DownloaderError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN"):
        super().__init__(message)
        self.code = code
        self.user_message = message
