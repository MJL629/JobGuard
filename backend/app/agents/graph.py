"""旧导入路径兼容层。

生产图已统一到 :mod:`app.graph.builder`。保留此模块是为了不破坏可能存在的
外部调用；它不再维护第二套图或声明空业务节点。
"""

from typing import Optional

from app.graph.builder import build_jobguard_graph, classify_message, get_jobguard_graph


def build_graph():
    return build_jobguard_graph()


def get_graph():
    return get_jobguard_graph()


async def run_graph(user_message: str, user_profile: Optional[dict] = None) -> dict:
    result = await classify_message(user_message)
    return {
        **result,
        "user_profile": user_profile,
        "error": None,
    }
