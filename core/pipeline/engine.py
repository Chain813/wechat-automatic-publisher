from typing import List, Dict, Any
from loguru import logger
from core.pipeline.nodes import BaseNode
from core.shared.runtime import check_cancelled

class PipelineEngine:
    """
    DAG / 流水线引擎。
    按顺序执行各个节点，并将 context 贯穿整个执行过程。
    """
    def __init__(self, name: str = "Pipeline"):
        self.name = name
        self.nodes: List[BaseNode] = []
        self.context: Dict[str, Any] = {}

    def add_node(self, node: BaseNode):
        self.nodes.append(node)
        return self

    def run(self, initial_context: Dict[str, Any] = None) -> bool:
        if initial_context:
            self.context.update(initial_context)
            
        logger.info(f"🚀 开始执行流水线: {self.name} (共 {len(self.nodes)} 个节点)")
        
        for idx, node in enumerate(self.nodes):
            check_cancelled()
            logger.info(f"[{idx+1}/{len(self.nodes)}] 正在执行节点: {node.name}")
            try:
                success = node.execute(self.context)
                if not success:
                    logger.warning(f"⚠️ 流水线在节点 {node.name} 中止。")
                    return False
            except Exception as e:
                logger.error(f"❌ 节点 {node.name} 执行发生未捕获异常: {e}")
                self.context["error"] = str(e)
                return False
                
        logger.info(f"✅ 流水线 {self.name} 执行完毕！")
        return True
