from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseNode(ABC):
    """
    流水线节点基类
    """
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> bool:
        """
        执行节点逻辑。
        :param context: 贯穿整个流水线的上下文数据字典
        :return: 返回 True 表示继续下一个节点；返回 False 表示终止流水线
        """
        pass
