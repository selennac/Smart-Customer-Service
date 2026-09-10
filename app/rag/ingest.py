"""将Markdown知识库加载为结构化的LangChain文档。"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.documents import Document

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")      # 匹配Markdown标题
SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*")      # 中文/英文句子边界分割

# 文件名到主题标签的映射
TOPIC_BY_FILENAME = {
    "退款政策.md": "refund",
    "退换货政策.md": "return_exchange",
    "物流配送说明.md": "logistics",
    "会员权益.md": "membership",
    "常见问题.md": "faq",
}


def _split_long_body(body: str, max_chars: int, overlap: int) -> list[str]:
    """在句子边界处分割过长的正文，并保留少量重叠。"""
    body = body.strip()
    if len(body) <= max_chars:
        return [body] if body else []

    sentences = [part.strip() for part in SENTENCE_RE.split(body) if part.strip()]
    # 如果切分不出可用句子边界（正则找不到分隔符时返回[整段]），
    # 或某个"句子"本身就超过上限：贪心拼接无法处理单句超长，
    # 此时整段退回带重叠的字符窗口切分。
    if not sentences or any(len(s) > max_chars for s in sentences):
        step = max(1, max_chars - overlap)
        return [body[index:index + max_chars] for index in range(0, len(body), step)]

    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current}{sentence}" if not current else f"{current} {sentence}"
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = f"{current[-overlap:] if overlap else ''}{sentence}"
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _section_records(markdown: str) -> tuple[str, list[tuple[str, str, str]]]:
    """在H2标题边界处拆分Markdown，同时保留文档引言部分。"""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    document_title = ""
    records: list[tuple[str, str, str]] = []          # 存储：(章节标题, 章节路径, 正文)
    current_title: str | None = None
    current_path: str = ""
    current_lines: list[str] = []

    def flush() -> None:
        """将当前累积的内容写入记录。"""
        nonlocal current_lines
        if current_title is not None:
            body = "\n".join(current_lines).strip()
            if body:
                records.append((current_title, current_path, body))
        current_lines = []

    for line in lines:
        match = HEADING_RE.match(line)
        if not match:
            current_lines.append(line)
            continue

        level = len(match.group(1))
        title = match.group(2).strip()
        if level == 1 and not document_title:
            document_title = title                    # 一级标题作为文档标题
        elif level == 2:
            if current_title is None:
                introduction = "\n".join(current_lines).strip()
                if introduction:
                    records.append((document_title, document_title, introduction))
            flush()
            current_title = title
            current_path = f"{document_title} > {title}" if document_title else title
        else:
            # 将嵌套标题保留在章节正文中作为局部上下文
            current_lines.append(line)

    flush()
    document_title = document_title or "未命名文档"
    if not records:
        body = "\n".join(line for line in lines if not HEADING_RE.match(line)).strip()
        if body:
            records.append((document_title, document_title, body))
    return document_title, records


def split_markdown_file(path: str | Path, *, max_chars: int = 450, overlap: int = 50) -> list[Document]:
    """将一个UTF-8编码的Markdown文件转换为带丰富元数据的语义块。"""
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("max_chars必须为正数，且 0 <= overlap < max_chars")

    path = Path(path)
    document_title, sections = _section_records(path.read_text(encoding="utf-8"))
    topic = TOPIC_BY_FILENAME.get(path.name, "general")   # 根据文件名确定主题
    document_type = "faq" if topic == "faq" else "policy" # FAQ或其他政策文档
    documents: list[Document] = []

    for section_title, section_path, body in sections:
        for part in _split_long_body(body, max_chars, overlap):
            index = len(documents) + 1
            chunk_id = f"{path.stem}-{index:03d}"         # 生成唯一块ID，如"退款政策-001"
            documents.append(
                Document(
                    id=chunk_id,
                    page_content=f"文档：{document_title}\n章节：{section_path}\n\n{part}",
                    metadata={
                        "source": path.name,              # 源文件名
                        "document_title": document_title, # 文档标题
                        "section_title": section_title,   # 章节标题
                        "section_path": section_path,     # 章节完整路径
                        "topic": topic,                   # 主题标签
                        "document_type": document_type,   # 文档类型
                        "chunk_index": index,             # 块索引
                    },
                )
            )
    return documents


def load_knowledge_documents(
        directory: str, *, max_chars: int = 450, overlap: int = 50
) -> list[Document]:
    """按确定顺序加载目录中的所有Markdown文件，用于向量索引。"""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"知识库目录不存在：{directory}")

    paths = sorted(directory.glob("*.md"), key=lambda item: item.name)
    if not paths:
        raise FileNotFoundError(f"在目录中未找到Markdown文件：{directory}")
    documents: list[Document] = []
    for path in paths:
        documents.extend(split_markdown_file(path, max_chars=max_chars, overlap=overlap))
    return documents