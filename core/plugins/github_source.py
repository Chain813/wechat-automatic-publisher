from typing import List, Dict, Any
from core.plugins.base import BaseSourcePlugin
from core.github.collector import fetch_one_worthy_project

class GithubPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "github_repo"

    @property
    def display_name(self) -> str:
        return "GitHub热门开源项目"

    def fetch_data(self) -> List[Dict[str, Any]]:
        """
        抓取 GitHub 候选项目
        """
        # 复用已有的抓取逻辑
        return fetch_one_worthy_project()
