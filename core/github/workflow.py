import os
import time
from datetime import datetime
from loguru import logger

from config import BRAND_NAME, SD_ENABLED, GITHUB_FIXED_COVER
from core.github.collector import fetch_one_worthy_project, generate_code_screenshot, get_repo_code_snippet, save_github_history, take_github_readme_screenshot, take_live_ui_screenshot
from core.github.processor import generate_github_article, generate_github_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_cover_image, download_project_image_for_github, reset_image_cache
from core.shared.runtime import check_cancelled


def _publish_draft_github(publisher, title, html_content, thumb_id, digest_text):
    print("\n🚀 正在同步至微信公众号云端草稿箱...")
    result = publisher.add_draft(title, html_content, thumb_id, digest_text)
    if "media_id" not in result:
        print(f"❌ 同步草稿箱失败：{result}")
        return False

    draft_id = result['media_id']
    print(f"\n{'⭐' * 30}")
    print("  🎉 恭喜！发布成功")
    print(f"  📄 标题：{title}")
    print(f"  🆔 草稿：{draft_id}")
    print(f"{'⭐' * 30}")

    try:
        from config import QYWECHAT_WEBHOOK
        from core.shared.publisher import send_to_qywechat
        send_to_qywechat(QYWECHAT_WEBHOOK, f"【{BRAND_NAME}】《{title}》已就绪，请审核发布。")
    except Exception as e:
        logger.debug("  企微通知发送失败（非关键）: {}", e)

    return True


def _download_and_upload_url(url, publisher, prefix="remote"):
    """下载远程图片到临时文件并上传到微信，返回 URL 或 None"""
    import requests as _req
    from utils.http_client import build_api_session
    tmp_path = None
    try:
        session = build_api_session()
        res = session.get(url, timeout=15)
        if res.status_code == 200 and len(res.content) > 5000:
            ext = ".jpg"
            if ".png" in url.lower(): ext = ".png"
            elif ".gif" in url.lower(): ext = ".gif"
            elif ".webp" in url.lower(): ext = ".webp"
            tmp_path = os.path.join("assets", f"{prefix}_{int(time.time()*1000)}{ext}")
            os.makedirs("assets", exist_ok=True)
            with open(tmp_path, 'wb') as f:
                f.write(res.content)
            img_url = publisher.upload_news_image(tmp_path)
            if img_url:
                return img_url
    except Exception as e:
        logger.debug("  下载远程图片失败: {}", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return None


def _ensure_deep_images(projects, publisher):
    """
    确保单项目有 3+ 张深度配图。
    所有图片来源并行执行，集满 3 张后自动停止其余任务。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    for p in projects:
        check_cancelled()

        urls = []
        urls_lock = threading.Lock()
        enough = threading.Event()  # 集满 3 张后置位，通知其他任务提前退出

        def _try_add(make_fn, label):
            """尝试生成并添加一张图片。如果已集满则跳过。"""
            if enough.is_set():
                return None
            check_cancelled()
            try:
                img_url = make_fn()
            except Exception as e:
                logger.debug("  {} 失败: {}", label, e)
                return None
            if img_url:
                with urls_lock:
                    if len(urls) < 3:
                        urls.append(img_url)
                        print(f"  ✅ {label} 已上传")
                        if len(urls) >= 3:
                            enough.set()
            return img_url

        # ---- 构建所有图片来源任务 ----
        tasks = []

        # 0. Social Preview 封面图
        social_url = p.get('social_preview_url')
        if social_url:
            tasks.append(("Social Preview", lambda u=social_url: _download_and_upload_url(u, publisher, "social")))

        # 1. GIF 动画（项目实际运行效果）
        other_images = p.get('other_images', [])
        gif_images = [u for u in other_images if u.lower().endswith('.gif')]
        for gif_url in gif_images[:2]:  # 最多 2 张 GIF
            tasks.append(("GIF 动画", lambda u=gif_url: _download_and_upload_url(u, publisher, "gif")))

        # 2. 在线 Demo UI 截图
        homepage = p.get('homepage')
        if homepage:
            def _make_demo(repo=p['repo'], url=homepage):
                path = take_live_ui_screenshot(repo, url)
                return publisher.upload_news_image(path) if path and os.path.exists(path) else None
            tasks.append(("Demo 截图", _make_demo))

        # 3. README 概览截图
        def _make_readme(repo=p['repo'], fp=p.get('readme_file_path')):
            path = take_github_readme_screenshot(repo, fp)
            return publisher.upload_news_image(path) if path and os.path.exists(path) else None
        tasks.append(("README 截图", _make_readme))

        # 4. SD 艺术配图
        if SD_ENABLED:
            def _make_sd(repo=p['repo'], desc=p.get('desc', ''), lang=p.get('lang', 'Unknown'), topics=p.get('topics', [])):
                path = download_project_image_for_github(repo_name=repo, description=desc, lang=lang, topics=topics)
                return publisher.upload_news_image(path) if path else None
            tasks.append(("SD 配图", _make_sd))

        # 5. 代码截图（快速兜底）
        def _make_code(repo=p['repo'], lang=p.get('lang', 'python')):
            code_text, _ = get_repo_code_snippet(repo)
            if code_text:
                img = generate_code_screenshot(code_text, lang)
                return publisher.upload_news_image(img) if img and os.path.exists(img) else None
            return None
        tasks.append(("代码截图", _make_code))

        # ---- 并行执行所有任务，集满即止 ----
        print(f"  🚀 并行启动 {len(tasks)} 个配图任务...")
        with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
            futures = {pool.submit(_try_add, fn, name): name for name, fn in tasks}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.debug("  配图任务异常: {}", e)
                if enough.is_set():
                    # 集满了，取消还在排队的任务
                    for f in futures:
                        f.cancel()
                    break

        # 6. 兜底：README 中的静态图（不需要下载/上传，直接用远程 URL）
        if len(urls) < 3 and p.get('image_url') and p.get('image_url') not in urls:
            urls.append(p.get('image_url'))
        if len(urls) < 3:
            non_gif = [u for u in other_images if not u.lower().endswith('.gif') and u not in urls]
            for img_url in non_gif:
                if len(urls) >= 3:
                    break
                urls.append(img_url)

        p['image_urls'] = urls
        if urls:
            p['image_url'] = urls[0]


def run_github_workflow(publisher):
    """处理 GitHub 单项目深度推荐抓取和发布流程。"""
    projects = fetch_one_worthy_project()
    check_cancelled()
    if not projects:
        print("📭 今日暂无获取到 GitHub 热门项目。")
        return

    print(f"\n🚀 准备深度解析 GitHub 热门项目: {projects[0]['repo']}")

    reset_image_cache()

    # 确保项目有深度配图
    print("\n🖼️  正在为项目生成深度配图（README/UI/SD）...")
    _ensure_deep_images(projects, publisher)
    check_cancelled()

    article_text, dynamic_title = generate_github_article(projects)
    check_cancelled()
    if not article_text or not dynamic_title:
        print("❌ AI 创作失败，跳过。")
        return

    # 后处理：将旧的占位符统一替换掉
    for p in projects:
        if p.get('tree_image_path') and p.get('image_url'):
            keyword = f"{p['repo'].split('/')[-1]} {p['lang']} project architecture"
            placeholder = f"【此处插入配图：{keyword}】"
            if placeholder in article_text:
                article_text = article_text.replace(
                    placeholder,
                    f"【GITHUB配图：{p['image_url']}】"
                )

    print("\n🎨 正在执行排版优化与配图处理...")
    final_html, review_data = process_article_content(article_text, publisher)

    topic = dynamic_title

    # 封面处理：直接使用固定的 GitHub 专题封面
    thumb_id = publisher.upload_image(GITHUB_FIXED_COVER)

    clean_title, title_warnings = validate_title(topic)
    for warning in title_warnings:
        print(f"  ⚠️ 标题警告: {warning}")

    # 动态生成摘要（而非硬编码），提升推送点击率
    repo_name = projects[0]['repo'].split('/')[-1]
    repo_desc = (projects[0].get('desc') or '')[:60]
    digest = generate_github_digest(repo_name, repo_desc)

    _print_review_report(
        title=clean_title,
        word_count=review_data["word_count"],
        image_count=review_data["image_count"],
        sensitive_words=review_data["sensitive_words"],
        cover_ok=thumb_id is not None,
        digest=digest,
    )

    success = _publish_draft_github(publisher, clean_title, final_html, thumb_id, digest)
    
    # 发布成功后，将项目记入历史，避免下次重复抓取
    if success:
        repo_names = [p['repo'] for p in projects]
        save_github_history(repo_names)
        
        try:
            import json
            record_file = "github_publish_records.json"
            records = []
            if os.path.exists(record_file):
                with open(record_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            records.append({
                "title": clean_title,
                "repos": repo_names
            })
            with open(record_file, "w", encoding="utf-8") as f:
                json.dump(records[-50:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 GitHub 发布记录失败: {}", e)
            
        print(f"✅ 已将 {len(repo_names)} 个项目加入历史过滤名单。")
