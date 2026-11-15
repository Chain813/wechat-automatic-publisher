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
    fact_check_result: str = ""

    def __str__(self) -> str:
        return self.title

    def __len__(self) -> int:
        return len(self.title)

    def __iter__(self):
        return iter(self.title)

    def __contains__(self, item) -> bool:
        return item in self.title

    def __add__(self, other) -> str:
        return self.title + str(other)

    def __radd__(self, other) -> str:
        return str(other) + self.title

    def __hash__(self) -> int:
        return hash((self.title, self.url))

    def __eq__(self, other) -> bool:
        if isinstance(other, HotspotItem):
            return self.title == other.title and self.url == other.url
        if isinstance(other, str):
            return self.title == other
        return False

    def strip(self, *args, **kwargs) -> str:
        return self.title.strip(*args, **kwargs)

    def lstrip(self, *args, **kwargs) -> str:
        return self.title.lstrip(*args, **kwargs)

    def rstrip(self, *args, **kwargs) -> str:
        return self.title.rstrip(*args, **kwargs)

    def lower(self) -> str:
        return self.title.lower()

    def upper(self) -> str:
        return self.title.upper()

    def startswith(self, *args, **kwargs) -> bool:
        return self.title.startswith(*args, **kwargs)

    def endswith(self, *args, **kwargs) -> bool:
        return self.title.endswith(*args, **kwargs)

    def replace(self, *args, **kwargs) -> str:
        return self.title.replace(*args, **kwargs)


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
