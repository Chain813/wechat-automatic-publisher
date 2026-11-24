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

class ArticleCounts:
    def __init__(self):
        self.succeeded = self.failed = self.uncertain = self.skipped = 0
        self.errors = []
        self.cancelled = False

    def record(self, success, error=None):
        if success:
            self.succeeded += 1
        elif str(error).startswith("CLOUD_UNCERTAIN"):
            self.uncertain += 1
        else:
            self.failed += 1
        if error:
            self.errors.append(str(error))

    def outcome(self, task_type):
        from core.shared.runtime import WorkflowOutcome
        attempted = self.succeeded + self.failed + self.uncertain
        if self.cancelled:
            status = "cancelled"
        elif not attempted:
            status = "skipped"
        elif not self.succeeded:
            status = "failed"
        elif self.failed or self.uncertain:
            status = "partial_success"
        else:
            status = "success"
        return WorkflowOutcome(task_type=task_type, status=status, attempted=attempted,
                               succeeded=self.succeeded, failed=self.failed, uncertain=self.uncertain,
                               skipped=self.skipped, summary=f"{self.succeeded}/{attempted}",
                               error="; ".join(self.errors))


def run_counted(task_type, operation):
    from core.shared.runtime import WorkflowCancelled, check_cancelled
    counts = ArticleCounts()
    try:
        check_cancelled()
        operation(counts)
    except WorkflowCancelled as exc:
        counts.cancelled = True
        counts.errors.append(str(exc))
    except Exception as exc:
        counts.record(False, str(exc))
    return counts.outcome(task_type)
