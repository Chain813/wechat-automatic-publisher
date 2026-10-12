import os
import time
import hashlib
from datetime import datetime
from loguru import logger
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SD_ENABLED, GITHUB_FIXED_COVER
from core.github.collector import generate_code_screenshot, get_repo_code_snippet, save_github_history, take_github_readme_screenshot, take_live_ui_screenshot
from core.github.processor import generate_github_article, generate_github_digest
from core.shared.article_utils import process_article_content, _print_review_report
from core.shared.llm import validate_title
from utils.image_handler import download_project_image_for_github, reset_image_cache
from core.shared.runtime import check_cancelled

from core.pipeline.nodes import BaseNode
from core.pipeline.engine import PipelineEngine
from core.plugins.manager import plugin_manager
from core.db.manager import db_manager
from core.db.models import ArticleHistory

# --- 辅助方法 ---

def _jsdelivr_mirror(url):
    """raw.githubusercontent.com → cdn.jsdelivr.net 国内可直连镜像"""
    import re as _re
    m = _re.match(r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$", url)
    if m:
        user, repo, branch, path = m.groups()
        return f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}"
    return url


def _download_and_upload_url(url, publisher, prefix="remote"):
    from utils.http_client import build_api_session
    tmp_path = None
    candidates = [url]
    if "raw.githubusercontent.com" in url:
        candidates.append(_jsdelivr_mirror(url))
    try:
        session = build_api_session()
        res = None
        used_url = url
        for cand in candidates:
            try:
                r = session.get(cand, timeout=15)
                if r.status_code == 200 and len(r.content) > 5000:
                    res, used_url = r, cand
                    break
            except Exception:
                res = None
        if res is None or res.status_code != 200:
            logger.warning("  下载失败 status={}: {}", getattr(res, "status_code", "网络异常"), url[:80])
            return None
        if len(res.content) <= 5000:
            logger.warning("  图片太小 ({} bytes): {}", len(res.content), url[:80])
            return None
        if used_url != url:
            logger.info("  🌐 已切换 jsdelivr 镜像下载: {}", url[:60])

        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        elif ".gif" in url.lower():
            ext = ".gif"
        elif ".webp" in url.lower():
            ext = ".webp"
        tmp_path = os.path.join("assets", f"{prefix}_{int(time.time()*1000)}{ext}")
        os.makedirs("assets", exist_ok=True)
        with open(tmp_path, 'wb') as f:
            f.write(res.content)

        img_url = publisher.upload_news_image(tmp_path)
        if not img_url:
            logger.warning("  微信上传失败: {}", tmp_path)
        return img_url
    except Exception as e:
        logger.warning("  下载/上传异常: {} — {}", str(e)[:80], url[:80])
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _ensure_deep_images(projects, publisher):
    for p in projects:
        check_cancelled()

        urls = []
        urls_lock = threading.Lock()
        enough = threading.Event()

        def _try_add(make_fn, label):
            if enough.is_set():
                return None
            check_cancelled()
            try:
                img_url = make_fn()
            except Exception as e:
                logger.warning("  ❌ {} 异常: {}", label, e)
                return None
            if img_url:
                with urls_lock:
                    if len(urls) < 3:
                        urls.append(img_url)
                        print(f"  ✅ {label} 已上传")
                        if len(urls) >= 3:
                            enough.set()
            else:
                print(f"  ⚠️ {label} 未返回有效图片")
            return img_url

        print(f"  🔍 项目数据: social={bool(p.get('social_preview_url'))}, "
              f"gif={len([u for u in p.get('other_images', []) if u.lower().endswith('.gif')])}, "
              f"homepage={bool(p.get('homepage'))}, "
              f"image_url={bool(p.get('image_url'))}, "
              f"other_images={len(p.get('other_images', []))}, "
              f"SD={SD_ENABLED}")

        tasks = []

        social_url = p.get('social_preview_url')
        if social_url:
            tasks.append(("Social Preview", lambda u=social_url: _download_and_upload_url(u, publisher, "social")))

        other_images = p.get('other_images', [])
        gif_images = [u for u in other_images if u.lower().endswith('.gif')]
        for gif_url in gif_images[:2]:
            tasks.append(("GIF 动画", lambda u=gif_url: _download_and_upload_url(u, publisher, "gif")))

        homepage = p.get('homepage')
        if homepage:
            def _make_demo(repo=p['repo'], url=homepage):
                path = take_live_ui_screenshot(repo, url)
                return publisher.upload_news_image(path) if path and os.path.exists(path) else None
            tasks.append(("Demo 截图", _make_demo))

        def _make_readme(repo=p['repo'], fp=p.get('readme_file_path')):
            path = take_github_readme_screenshot(repo, fp)
            return publisher.upload_news_image(path) if path and os.path.exists(path) else None
        tasks.append(("README 截图", _make_readme))

        if SD_ENABLED:
            def _make_sd(repo=p['repo'], desc=p.get('desc', ''), lang=p.get('lang', 'Unknown'), topics=p.get('topics', [])):
                path = download_project_image_for_github(repo_name=repo, description=desc, lang=lang, topics=topics)
                return publisher.upload_news_image(path) if path else None
            tasks.append(("SD 配图", _make_sd))

        def _make_code(repo=p['repo'], lang=p.get('lang', 'python')):
            code_text, _ = get_repo_code_snippet(repo)
            if code_text:
                img = generate_code_screenshot(code_text, lang)
                return publisher.upload_news_image(img) if img and os.path.exists(img) else None
            return None
        tasks.append(("代码截图", _make_code))

        print(f"  🚀 并行启动 {len(tasks)} 个配图任务...")
        if not tasks:
            print("  ⚠️ 无可用配图任务（social_url/gif/homepage/SD 均为空）")
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
                futures = {pool.submit(_try_add, fn, name): name for name, fn in tasks}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.warning("  配图任务异常: {}", e)
                    if enough.is_set():
                        for f in futures:
                            f.cancel()
                        break
            print(f"  📊 并行配图完成: 成功 {len(urls)}/3 张")

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
            print(f"  📸 最终配图: {len(urls)} 张 — {[u[:60]+'...' for u in urls]}")
        else:
            print("  ❌ 最终配图: 0 张（所有来源均失败）")


# --- 流水线节点定义 ---

class FetchGithubNode(BaseNode):
    def execute(self, context: dict) -> bool:
        check_cancelled()
        plugin = plugin_manager.get_plugin("github_repo")
        if not plugin:
            print("❌ Github 插件未加载。")
            return False
            
        projects = plugin.fetch_data()
        if not projects:
            print("📭 今日暂无获取到 GitHub 热门项目。")
            return False

        print(f"\n🚀 准备深度解析 GitHub 热门项目: {projects[0]['repo']}")
        context['projects'] = projects
        return True

class ProcessGithubImagesNode(BaseNode):
    def execute(self, context: dict) -> bool:
        check_cancelled()
        projects = context['projects']
        publisher = context['publisher']
        reset_image_cache()

        print("\n🖼️  正在为项目生成深度配图（README/UI/SD）...")
        _ensure_deep_images(projects, publisher)
        return True

class GenerateGithubArticleNode(BaseNode):
    def execute(self, context: dict) -> bool:
        check_cancelled()
        projects = context['projects']
        publisher = context['publisher']

        article_text, dynamic_title = generate_github_article(projects)
        if not article_text or not dynamic_title:
            print("❌ AI 创作失败，跳过。")
            return False

        for p in projects:
            if p.get('tree_image_path') and p.get('image_url'):
                keyword = f"{p['repo'].split('/')[-1]} {p['lang']} project architecture"
                placeholder = f"【此处插入配图：{keyword}】"
                if placeholder in article_text:
                    article_text = article_text.replace(placeholder, f"【GITHUB配图：{p['image_url']}】")

        print("\n🎨 正在执行排版优化与配图处理...")
        final_html, review_data = process_article_content(article_text, publisher)

        repo_name = projects[0]['repo'].split('/')[-1]
        repo_desc = (projects[0].get('desc') or '')[:60]
        digest = generate_github_digest(repo_name, repo_desc)

        context['article_data'] = {
            'topic': dynamic_title,
            'final_html': final_html,
            'review_data': review_data,
            'digest': digest
        }
        return True

class PublishGithubNode(BaseNode):
    def execute(self, context: dict) -> bool:
        check_cancelled()
        projects = context['projects']
        publisher = context['publisher']
        article_data = context['article_data']

        topic = article_data['topic']
        final_html = article_data['final_html']
        review_data = article_data['review_data']
        digest = article_data['digest']

        thumb_id = publisher.upload_image(GITHUB_FIXED_COVER)
        clean_title, title_warnings = validate_title(topic)
        for warning in title_warnings:
            print(f"  ⚠️ 标题警告: {warning}")

        all_ok = _print_review_report(
            title=clean_title,
            word_count=review_data["word_count"],
            image_count=review_data["image_count"],
            sensitive_words=review_data["sensitive_words"],
            cover_ok=thumb_id is not None,
            digest=digest,
        )

        # 主编审校门禁 (Critic & Quality Gate)
        from core.pipeline.critic import evaluate_article_quality, format_critic_report
        review_res = evaluate_article_quality(clean_title, final_html, article_type="github")
        print(format_critic_report(review_res))

        if not review_res["passed"] or not all_ok:
            err = f"未通过主编质量门禁 ({review_res['score']}分): {'; '.join(review_res['critic_issues'])}"
            print(f"❌ 门禁拦截发布：「{clean_title}」— {err}")
            try:
                title_hash = hashlib.md5(clean_title.encode('utf-8')).hexdigest()
                os.makedirs(os.path.join("data", "previews"), exist_ok=True)
                with open(os.path.join("data", "previews", f"fail_{title_hash}.html"), "w", encoding="utf-8") as f:
                    f.write(final_html)

                primary_repo_url = f"https://github.com/{projects[0]['repo']}" if projects else ""
                session = db_manager.get_session()
                try:
                    ah = ArticleHistory(
                        title=clean_title,
                        source_type="github",
                        publish_date=datetime.now().strftime("%Y-%m-%d"),
                        success_status=False,
                        media_id=None,
                        error_log=err,
                        quality_score=review_res["score"],
                        source_url=primary_repo_url,
                        thumb_media_id=thumb_id,
                        status="REJECTED"
                    )
                    session.add(ah)
                    session.commit()
                finally:
                    db_manager.remove_session()
            except Exception as e:
                logger.warning("保存 GitHub 门禁拦截记录异常: {}", e)
            return False

        print("\n🚀 正在同步至微信公众号云端草稿箱...")
        success, result = publisher.publish_and_notify(clean_title, final_html, thumb_id, digest)
        if not success:
            print(f"❌ 同步草稿箱失败：{result}")
            return False

        draft_id = result['media_id']
        print(f"\n{'⭐' * 30}\n  🎉 恭喜！发布成功\n  📄 标题：{clean_title}\n  🆔 草稿：{draft_id}\n{'⭐' * 30}")
        
        # 保存本地 HTML 预览供 WebUI 人机工作台查看
        try:
            os.makedirs(os.path.join("data", "previews"), exist_ok=True)
            with open(os.path.join("data", "previews", f"{draft_id}.html"), "w", encoding="utf-8") as f:
                f.write(final_html)
        except Exception as pe:
            logger.debug("保存 GitHub 预览 HTML 异常: {}", pe)

        repo_names = [p['repo'] for p in projects]
        save_github_history(repo_names)
        
        try:
            primary_repo_url = f"https://github.com/{projects[0]['repo']}" if projects else ""
            session = db_manager.get_session()
            try:
                ah = ArticleHistory(
                    title=clean_title,
                    source_type="github",
                    publish_date=datetime.now().strftime("%Y-%m-%d"),
                    success_status=True,
                    media_id=draft_id,
                    error_log=None,
                    quality_score=review_res["score"],
                    source_url=primary_repo_url,
                    thumb_media_id=thumb_id,
                    status="DRAFT"
                )
                session.add(ah)
                session.commit()
            finally:
                db_manager.remove_session()
        except Exception as e:
            logger.warning("保存 GitHub 发布记录失败: {}", e)
            
        print(f"✅ 已将 {len(repo_names)} 个项目加入历史过滤名单。")
        return True

# --- 主调度 ---

def run_github_workflow(publisher):
    engine = PipelineEngine(name="GithubWorkflow")
    engine.add_node(FetchGithubNode())
    engine.add_node(ProcessGithubImagesNode())
    engine.add_node(GenerateGithubArticleNode())
    engine.add_node(PublishGithubNode())
    
    engine.run({"publisher": publisher})
