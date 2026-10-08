from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Any, Optional


@dataclass
class HotspotItem:
    title: str
    url: str = ""
    source_id: str = ""
    summary: str = ""
    publish_time: Optional[str] = None
    raw_content: str = ""
    tier: int = 2

    def __str__(self) -> str:
        return self.title

    def __len__(self) -> int:
        return len(self.title)

    def strip(self, *args, **kwargs) -> str:
        return self.title.strip(*args, **kwargs)


class BaseSourcePlugin(ABC):
    """
    数据源插件基类
    """
    
    @property
    @abstractmethod
    def source_id(self) -> str:
        """插件唯一标识符，例如 'weibo', 'github'"""
        pass
        
    @property
    def display_name(self) -> str:
        """展示名称，例如 '微博热搜'"""
        return self.source_id

    @abstractmethod
    def fetch_data(self) -> List[Any]:
        """
        抓取核心逻辑
        :return: 获取到的项目列表，通常是包含标题、链接等信息的字典列表，或纯文本标题列表
        """
        pass
