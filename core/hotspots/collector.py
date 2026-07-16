"""
============================================================
  超级热点聚合引擎 v7.0 (微信适配版) - Plugin 版
  迁移记录：原有采集逻辑已重构为 DataSource 插件系统，位于 core/plugins/ 目录下。
============================================================
"""
from loguru import logger
from config import NEWS_SOURCES
from core.plugins.manager import plugin_manager
from core.plugins.utils import _is_title_fresh, get_source_health_report, reset_source_health

# 重新导出供外部使用
__all__ = ["fetch_all_hotspots", "get_source_health_report", "reset_source_health"]

def fetch_all_hotspots():
    """
    聚合入口：并行抓取所有配置的源。
    使用 PluginManager 动态加载并执行插件。
    """
    return fetch_all_hotspots_parallel()

def fetch_all_hotspots_parallel():
    sources = [s for s in NEWS_SOURCES if plugin_manager.get_plugin(s)]
    if not sources:
        logger.warning("  没有可用的采集源！")
        return ""

    logger.info("正在启动全网热点并行扫描引擎 ({} 源)...", len(sources))

    import concurrent.futures
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as executor:
        future_map = {
            executor.submit(plugin_manager.get_plugin(s).fetch_data): s
            for s in sources
        }
        for future in concurrent.futures.as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.warning("  {} 并行任务异常: {}", name, e)
                results[name] = []

    # 拼接输出
    all_summary = []
    for src in sources:
        plugin = plugin_manager.get_plugin(src)
        topics = results.get(src, [])
        if topics:
            original_count = len(topics)
            topics = [t for t in topics if _is_title_fresh(t)]
            filtered_count = original_count - len(topics)
            if filtered_count > 0:
                logger.info("  {} 源过滤掉 {} 条旧内容", src, filtered_count)
            label = plugin.display_name if plugin else src
            all_summary.append(f"【{label}】")
            all_summary.extend(topics)
            all_summary.append("")

    final_text = "\n".join(all_summary).strip()
    if not final_text:
        return ""

    logger.info("  成功拉取全网 {} 条热搜聚合数据", len([l for l in all_summary if l and not l.startswith("【")]))
    return final_text
