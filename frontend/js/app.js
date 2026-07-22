/**
 * MediaDown — 前端交互逻辑
 * 纯原生 JavaScript，零依赖。
 */

(function () {
    "use strict";

    // ─── DOM 元素 ──────────────────────────────────────
    const urlInput = document.getElementById("urlInput");
    const pasteBtn = document.getElementById("pasteBtn");
    const parseBtn = document.getElementById("parseBtn");
    const loadingState = document.getElementById("loadingState");
    const errorState = document.getElementById("errorState");
    const errorMessage = document.getElementById("errorMessage");
    const previewCard = document.getElementById("previewCard");
    const cardThumbnail = document.getElementById("cardThumbnail");
    const cardTitle = document.getElementById("cardTitle");
    const cardPlatform = document.getElementById("cardPlatform");
    const cardDuration = document.getElementById("cardDuration");
    const cardSize = document.getElementById("cardSize");
    const cardUploader = document.getElementById("cardUploader");
    const formatSelector = document.getElementById("formatSelector");
    const formatList = document.getElementById("formatList");
    const downloadBtn = document.getElementById("downloadBtn");
    const toastContainer = document.getElementById("toastContainer");

    // ─── 状态 ──────────────────────────────────────────
    let currentInfo = null;      // 当前解析结果
    let selectedFormatId = "best";
    let currentImagePath = "";   // Instagram 图片帖的文件路径
    let isParsing = false;
    let isDownloading = false;

    // 下载进度相关 DOM
    var downloadProgress = document.getElementById("downloadProgress");
    var progressDetail = document.getElementById("progressDetail");
    var loginToggle = document.getElementById("loginToggle");
    var progressBar = document.getElementById("progressBar");
    var progressPercent = document.getElementById("progressPercent");
    var progressTimer = document.getElementById("progressTimer");
    var timerInterval = null;

    /** 带超时的 fetch */
    function fetchWithTimeout(resource, options, timeoutMs) {
        timeoutMs = timeoutMs || 30000;
        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, timeoutMs);
        options = options || {};
        options.signal = controller.signal;
        return fetch(resource, options).finally(function () {
            clearTimeout(timeoutId);
        });
    }

    // ─── 工具函数 ──────────────────────────────────────

    /** 显示/隐藏加载状态 */
    function setLoading(show) {
        loadingState.style.display = show ? "flex" : "none";
        errorState.style.display = "none";
        if (show) previewCard.style.display = "none";
        isParsing = show;
        parseBtn.disabled = show;
    }

    /** 显示错误 */
    function showError(msg) {
        errorMessage.textContent = msg;
        errorState.style.display = "block";
        previewCard.style.display = "none";
        loadingState.style.display = "none";
        isParsing = false;
        parseBtn.disabled = false;
    }

    /** 显示预览卡片 */
    function showPreview(data) {
        currentInfo = data;
        currentImagePath = data._image_path || "";
        stopTimer();
        showProgress(false);
        previewCard.style.display = "block";
        errorState.style.display = "none";
        loadingState.style.display = "none";
        isParsing = false;
        parseBtn.disabled = false;

        // 图片帖：切换为完整显示模式
        var thumbnailWrapper = document.querySelector(".card-thumbnail-wrapper");
        if (data._is_image) {
            thumbnailWrapper.classList.add("image-mode");
        } else {
            thumbnailWrapper.classList.remove("image-mode");
        }

        // 缩略图
        if (data.thumbnail) {
            cardThumbnail.src = data.thumbnail;
            cardThumbnail.style.display = "block";
            cardThumbnail.nextElementSibling.style.display = "none";
        } else {
            cardThumbnail.style.display = "none";
            cardThumbnail.nextElementSibling.style.display = "flex";
        }

        // 标题
        cardTitle.textContent = data.title || "未知标题";

        // 平台
        cardPlatform.textContent = data.platform || "未知平台";

        // 时长
        cardDuration.textContent = data.duration_str ? `⏱ ${data.duration_str}` : "⏱ --";

        // 大小（取最佳画质的大小）
        const bestFormat = data.formats && data.formats.length > 0 ? data.formats[0] : null;
        cardSize.textContent = bestFormat && bestFormat.filesize_str ? `📦 ${bestFormat.filesize_str}` : "📦 --";

        // 上传者
        cardUploader.textContent = data.uploader ? `👤 ${data.uploader}` : "👤 --";

        // 画质选择
        renderFormatList(data.formats || []);

        // 重置下载按钮
        downloadBtn.disabled = false;
        downloadBtn.querySelector(".btn-text").textContent = "⬇ 下载原画质";
    }

    /** 渲染画质列表 */
    function renderFormatList(formats) {
        formatList.innerHTML = "";
        if (formats.length <= 1) {
            formatSelector.style.display = "none";
            selectedFormatId = formats.length === 1 ? formats[0].format_id : "best";
            return;
        }

        formatSelector.style.display = "flex";
        formats.forEach(function (fmt, index) {
            var btn = document.createElement("button");
            btn.className = "format-option";

            // 构建显示文本
            var label = "";
            if (fmt.note === "推荐" || fmt.resolution === "最佳画质（自动）") {
                label = "⭐ 最佳画质";
            } else if (fmt.resolution) {
                label = fmt.resolution;
            } else {
                label = fmt.note || fmt.ext;
            }

            // 添加文件大小
            if (fmt.filesize_str && fmt.filesize_str !== "未知大小" && fmt.filesize_str !== "自动选择") {
                label += " · " + fmt.filesize_str;
            }

            // 类型标签
            if (fmt.type_label && fmt.type_label !== "智能") {
                label += " [" + fmt.type_label + "]";
            }

            btn.textContent = label;
            btn.dataset.formatId = fmt.format_id;

            // 默认选中第一个（推荐）
            if (index === 0) {
                btn.classList.add("selected");
                selectedFormatId = fmt.format_id;
            }

            btn.addEventListener("click", function () {
                formatList.querySelectorAll(".format-option").forEach(function (b) {
                    b.classList.remove("selected");
                });
                btn.classList.add("selected");
                selectedFormatId = fmt.format_id;
            });

            formatList.appendChild(btn);
        });
    }

    /** Toast 通知 */
    function showToast(message, type) {
        type = type || "info";
        var toast = document.createElement("div");
        toast.className = "toast toast-" + type;

        var icon = type === "success" ? "✅" : type === "error" ? "❌" : "ℹ️";
        toast.innerHTML = "<span>" + icon + "</span><span>" + message + "</span>";

        toastContainer.appendChild(toast);

        // 3 秒后自动消失
        setTimeout(function () {
            toast.classList.add("toast-removing");
            setTimeout(function () {
                if (toast.parentNode) {
                    toastContainer.removeChild(toast);
                }
            }, 300);
        }, 3000);
    }

    // ─── 核心功能 ──────────────────────────────────────

    /** 解析链接 */
    function parseLink() {
        var url = urlInput.value.trim();

        if (!url) {
            showError("请先粘贴视频或图片链接");
            return;
        }

        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            showError("链接格式不正确，请复制完整链接");
            return;
        }

        setLoading(true);

        fetchWithTimeout("/api/info", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url }),
        }, 25000)
            .then(function (res) { return res.json(); })
            .then(function (result) {
                if (result.success) {
                    showPreview(result.data);
                } else {
                    showError(result.error || "解析失败，请重试");
                }
            })
            .catch(function (err) {
                if (err.name === "AbortError") {
                    showError("解析超时，该平台可能需要登录。请尝试上传 Cookie 文件后重试");
                } else {
                    showError("网络请求失败，请确认服务已启动：" + err.message);
                }
            });
    }

    /** 开始计时器 */
    function startTimer(secondsElapsed) {
        var startTime = Date.now() - (secondsElapsed || 0) * 1000;
        timerInterval = setInterval(function () {
            var elapsed = Math.floor((Date.now() - startTime) / 1000);
            var min = Math.floor(elapsed / 60);
            var sec = elapsed % 60;
            progressTimer.textContent = String(min).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
        }, 1000);
    }

    /** 停止计时器 */
    function stopTimer() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    }

    /** 显示下载进度 */
    function showProgress(show) {
        downloadProgress.style.display = show ? "flex" : "none";
        if (show) {
            progressBar.style.width = "0%";
            progressPercent.textContent = "0%";
            progressTimer.textContent = "00:00";
        }
    }

    /** 下载媒体 — 异步任务 + 轮询进度 */
    var pollingTimer = null;

    function stopPolling() {
        if (pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
        }
    }

    function downloadMedia() {
        if (!currentInfo) {
            showToast("请先解析视频链接", "error");
            return;
        }

        if (isDownloading) return;

        isDownloading = true;
        stopPolling();
        downloadBtn.disabled = true;
        downloadBtn.querySelector(".btn-text").textContent = "⏳ 启动下载...";
        showProgress(true);
        startTimer(0);

        var url = currentInfo.webpage_url || urlInput.value.trim();

        // Step 1: 启动异步下载任务
        fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url, format_id: selectedFormatId, image_path: currentImagePath }),
        })
            .then(function (res) { return res.json(); })
            .then(function (result) {
                if (!result.success) {
                    throw new Error(result.error || "启动下载失败");
                }
                // Step 2: 轮询进度
                pollProgress(result.task_id);
            })
            .catch(function (err) {
                showToast("❌ " + (err.message || "启动下载失败"), "error");
                resetDownloadUI();
            });
    }

    function pollProgress(taskId) {
        downloadBtn.querySelector(".btn-text").textContent = "⏳ 下载中...";

        pollingTimer = setInterval(function () {
            fetch("/api/progress/" + taskId)
                .then(function (res) { return res.json(); })
                .then(function (result) {
                    if (!result.success) {
                        clearInterval(pollingTimer);
                        showToast("❌ " + (result.error || "查询进度失败"), "error");
                        resetDownloadUI();
                        return;
                    }

                    var task = result.task;

                    // 更新进度条
                    progressBar.style.width = task.progress + "%";
                    progressPercent.textContent = task.progress + "%";

                    // 更新速度/ETA/大小详情
                    var infoParts = [];
                    if (task.speed) infoParts.push("⚡ " + task.speed);
                    if (task.eta) infoParts.push("⏱ 剩余 " + task.eta);
                    if (task.downloaded) infoParts.push("📦 " + task.downloaded + (task.total ? " / " + task.total : ""));
                    progressPercent.textContent = task.progress + "%";
                    progressDetail.textContent = infoParts.join("  ·  ");

                    // 状态处理
                    if (task.status === "done") {
                        // 下载完成，获取文件
                        stopPolling();
                        progressBar.style.width = "100%";
                        progressPercent.textContent = "100% — 正在保存...";
                        downloadBtn.querySelector(".btn-text").textContent = "💾 保存中...";
                        fetchFile(taskId);
                    } else if (task.status === "error") {
                        stopPolling();
                        showToast("❌ " + (task.error || "下载失败"), "error");
                        resetDownloadUI();
                    } else if (task.status === "merging") {
                        progressPercent.textContent = "正在合并音视频...";
                        progressBar.style.width = "95%";
                    }
                })
                .catch(function () {
                    // 网络错误，继续轮询
                });
        }, 1000);
    }

    function fetchFile(taskId) {
        fetch("/api/file/" + taskId)
            .then(function (res) {
                if (!res.ok) {
                    return res.json().then(function (err) {
                        throw new Error(err.error || "获取文件失败");
                    });
                }
                return res.blob().then(function (blob) {
                    // 从 Content-Disposition 提取文件名
                    var disposition = res.headers.get("Content-Disposition") || "";
                    var filename = "";
                    var match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                    if (match) filename = match[1].replace(/['"]/g, "");
                    return { blob: blob, filename: filename };
                });
            })
            .then(function (result) {
                var blobUrl = window.URL.createObjectURL(result.blob);
                var a = document.createElement("a");
                a.style.display = "none";
                a.href = blobUrl;
                a.download = result.filename || currentInfo.title + ".mp4";
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(blobUrl);
                document.body.removeChild(a);

                showToast("✅ 下载完成！文件已保存", "success");
            })
            .catch(function (err) {
                showToast("❌ " + (err.message || "保存文件失败"), "error");
            })
            .finally(function () {
                resetDownloadUI();
            });
    }

    function resetDownloadUI() {
        stopPolling();
        stopTimer();
        isDownloading = false;
        downloadBtn.disabled = false;
        downloadBtn.querySelector(".btn-text").textContent = "⬇ 下载原画质";
        setTimeout(function () { showProgress(false); }, 3000);
    }

    /** 从剪贴板读取链接 */
    function pasteFromClipboard() {
        if (navigator.clipboard && navigator.clipboard.readText) {
            navigator.clipboard.readText()
                .then(function (text) {
                    if (text && text.trim()) {
                        urlInput.value = text.trim();
                        showToast("已粘贴剪贴板内容", "info");
                        // 自动解析
                        parseLink();
                    } else {
                        showToast("剪贴板为空", "info");
                    }
                })
                .catch(function () {
                    // 降级：聚焦输入框让用户手动粘贴
                    urlInput.focus();
                    showToast("无法读取剪贴板，请手动 Ctrl+V 粘贴", "error");
                });
        } else {
            urlInput.focus();
            showToast("浏览器不支持剪贴板读取，请手动 Ctrl+V 粘贴", "info");
        }
    }

    // ─── 事件绑定 ──────────────────────────────────────

    // 解析按钮
    parseBtn.addEventListener("click", function () {
        if (!isParsing) parseLink();
    });

    // Enter 键解析
    urlInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !isParsing) {
            e.preventDefault();
            parseLink();
        }
    });

    // 粘贴按钮
    pasteBtn.addEventListener("click", function () {
        pasteFromClipboard();
    });

    // 下载按钮
    downloadBtn.addEventListener("click", function () {
        if (!isDownloading) downloadMedia();
    });

    // 页面加载时自动读取剪贴板（仅尝试）
    window.addEventListener("load", function () {
        // 聚焦输入框引导用户
        urlInput.focus();

        // 尝试自动读取剪贴板
        if (navigator.clipboard && navigator.clipboard.readText) {
            navigator.clipboard.readText()
                .then(function (text) {
                    if (text && text.trim() && (text.startsWith("http://") || text.startsWith("https://"))) {
                        urlInput.value = text.trim();
                        // 不自动解析，等用户确认
                    }
                })
                .catch(function () {
                    // 静默忽略
                });
        }
    });

})();
