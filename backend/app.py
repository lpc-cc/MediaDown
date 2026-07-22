"""
MediaDown — 视频/图片下载器
粘贴链接 → 下载原画质。无需登录，无需 Cookie。
"""

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_file

sys.path.insert(0, str(Path(__file__).parent))

from downloader import DownloaderError, cleanup_old_files, get_info, start_download, get_task

app = Flask(__name__, static_folder="../frontend", static_url_path="")


@app.route("/")
def index():
    html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "index.html not found", 500


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(silent=True)
    if not data or not data.get("url"):
        return _error("请输入视频或图片链接", "EMPTY_URL", 400)
    url = data["url"].strip()
    if not url.startswith(("http://", "https://")):
        return _error("链接格式不正确", "INVALID_URL", 400)
    try:
        info = get_info(url)
        return jsonify({"success": True, "data": info})
    except DownloaderError as e:
        return _error(e.user_message, e.code, 400)
    except Exception as e:
        return _error(f"解析失败：{e}", "SERVER_ERROR", 500)


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(silent=True)
    if not data or not data.get("url"):
        return _error("请提供下载链接", "EMPTY_URL", 400)
    url = data["url"].strip()
    format_id = data.get("format_id", "best")
    image_path = data.get("image_path", "")
    try:
        task_id = start_download(url, format_id, image_path=image_path)
        return jsonify({"success": True, "task_id": task_id})
    except Exception as e:
        return _error(f"启动下载失败：{e}", "SERVER_ERROR", 500)


@app.route("/api/progress/<task_id>", methods=["GET"])
def api_progress(task_id):
    task = get_task(task_id)
    if not task:
        return _error("任务不存在或已过期", "TASK_NOT_FOUND", 404)
    return jsonify({
        "success": True,
        "task": {
            "id": task["id"], "status": task["status"], "progress": task["progress"],
            "speed": task["speed"], "eta": task["eta"],
            "downloaded": task["downloaded"], "total": task["total"],
            "filename": task["filename"], "error": task["error"],
        },
    })


@app.route("/api/preview/<path:filename>", methods=["GET"])
def api_preview(filename):
    """提供本地预览图片（绕过 Instagram CDN 防盗链）。"""
    filepath = Path(__file__).parent / "downloads" / filename
    if filepath.exists():
        return send_file(filepath, mimetype="image/jpeg")
    return _error("预览不可用", "NOT_FOUND", 404)


@app.route("/api/file/<task_id>", methods=["GET"])
def api_file(task_id):
    task = get_task(task_id)
    if not task:
        return _error("任务不存在或已过期", "TASK_NOT_FOUND", 404)
    if task["status"] == "error":
        return _error(task["error"] or "下载失败", "DOWNLOAD_ERROR", 400)
    if task["status"] != "done":
        return _error("文件尚未下载完成", "NOT_READY", 400)
    filepath = Path(task["filepath"])
    if not filepath.exists():
        return _error("文件已被清理", "FILE_GONE", 404)
    return send_file(filepath, as_attachment=True, download_name=task["filename"] or filepath.name,
                     mimetype="application/octet-stream")


def _error(message: str, code: str = "UNKNOWN", http_status: int = 400):
    return jsonify({"success": False, "error": message, "code": code}), http_status


if __name__ == "__main__":
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print("=" * 50)
    print("  [MediaDown] 视频/图片下载器")
    print("  http://localhost:5000")
    print("=" * 50)
    cleanup_old_files()
    app.run(host="127.0.0.1", port=5000, debug=False)
