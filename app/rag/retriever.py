"""Embedding和Chroma持久化与FAQ检索器构建。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

project_root = Path(__file__).parent.parent.parent


def create_embeddings(
    *, model: str | None = None, api_key: str | None = None, base_url: str | None = None
) -> DashScopeEmbeddings:
    """创建兼容DashScope的OpenAI风格嵌入客户端。"""
    load_dotenv()
    api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key or api_key.startswith("replace-with-"):
        raise ValueError("请在构建向量存储前设置 LLM_API_KEY 或 DASHSCOPE_API_KEY")
    return DashScopeEmbeddings(
        model=model or os.getenv("EMBEDDING_MODEL"),
        dashscope_api_key=api_key,
    )


def build_vector_store(
    documents: Sequence[Document] | None = None,
    *,
    persist_directory: str | Path | None = None,
    collection_name: str = "customer_service_knowledge",
    recreate: bool = False,
) -> Chroma:
    """将知识文档增量写入持久化的Chroma集合。

    稳定的文档块ID使重复运行具有幂等性。当需要删除或重命名源文档块时，
    设置 ``recreate=True`` 可使这些块从集合中消失。
    """
    documents = list(documents)
    if not documents:
        raise ValueError("没有要索引的文档")

    embeddings = create_embeddings()
    persist_path = str(project_root / persist_directory)
    store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_path,
    )
    if recreate:
        store.delete_collection()
        store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_path,
        )

    # 阿里云的嵌入模型一次只能处理20个文档，因此分批添加
    batch_size = 20
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        store.add_documents(batch, ids=[doc.id for doc in batch])
        print(f"已添加 {i + len(batch)}/{len(documents)} 个文档")
    return store


def get_retriever(
    *,
    persist_directory: str | Path | None = None,
    collection_name: str = "customer_service_knowledge",
    k: int = 4,
    topic: str | None = None,
) -> BaseRetriever:
    """打开持久化的集合，返回一个相似度检索器。"""
    if k <= 0:
        raise ValueError("k 必须为正数")
    store = Chroma(
        collection_name=collection_name,
        embedding_function=create_embeddings(),
        persist_directory=str(project_root / persist_directory),
    )
    search_kwargs: dict[str, object] = {"k": k}
    if topic:
        search_kwargs["filter"] = {"topic": topic}
    return store.as_retriever(search_type="similarity", search_kwargs=search_kwargs)