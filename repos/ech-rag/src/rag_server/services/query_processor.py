"""
Query preprocessing for improved retrieval.

This module provides query expansion and preprocessing capabilities
to improve RAG retrieval accuracy through multi-query approaches.

TODO: 升级为LLM驱动的查询预处理 (参考FastGPT queryExtension.ts)
======================================================================
FastGPT的实现方式:
1. 使用LLM生成10个查询变体（消耗~200-500 token/查询）
2. 结合对话历史消除指代歧义（如"它"→"FastGPT"）
3. 从不同角度扩展（原因/影响/解决方案/对比等）
4. 使用Submodular贪心算法从N个候选中选最优3个
5. Few-shot提示词包含8个多语言示例

FastGPT Prompt模板核心:
- 为"原问题"生成N个不同版本的"检索词"
- 从不同角度探索主题以提高语义丰富度
- 要求: 相关性、多角度、无冗余、简洁可搜索

当前实现: 规则驱动(零成本)，可在需要时升级为LLM驱动
======================================================================
"""
# 用轻量的规则化手段，为用户的原始查询生成多个不同表述的变体，配合上层的多查询混合检索，提升文档召回的命中率和准确率。
from typing import List, Optional

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)


class QueryProcessor:
    """Process and expand queries for better retrieval."""
    
    def __init__(self):
        self.settings = get_settings()
        # Chinese stopwords for keyword extraction
        self._stopwords = {
            "的", "是", "在", "和", "了", "有", "与", "为", "等", "及",
            "这", "那", "你", "我", "他", "她", "它", "们", "也", "都",
            "就", "而", "但", "如果", "因为", "所以", "虽然", "可以",
            "什么", "如何", "怎么", "怎样", "为什么", "哪些", "哪个",
            "请", "吗", "呢", "啊", "吧", "呀", "嘛", "哦", "哈"
        }
    
    async def expand_query(self, query: str) -> List[str]:
        """
        Expand query with variations for multi-query retrieval.
        
        Args:
            query: Original user query
            
        Returns:
            List of query variations including original
        """
        queries = [query]
        
        # 1. Extract keywords version
        keywords = self._extract_keywords(query)
        if keywords and len(keywords) >= 2:
            keyword_query = " ".join(keywords)
            if keyword_query != query:
                queries.append(keyword_query)
        
        # 2. Convert question to declarative statement
        declarative = self._to_declarative(query)
        if declarative and declarative not in queries:
            queries.append(declarative)
        
        logger.debug(f"Expanded query '{query}' to {len(queries)} variants: {queries}")
        return queries
    
    def _extract_keywords(self, query: str) -> List[str]:
        """
        Extract key terms from query by removing stopwords.
        
        Args:
            query: Input query string
            
        Returns:
            List of keywords
        """
        # Remove punctuation and split
        cleaned = query.replace("？", "").replace("?", "").replace("，", " ").replace(",", " ")
        cleaned = cleaned.replace("。", "").replace(".", "").replace("：", " ").replace(":", " ")
        
        words = cleaned.split()
        keywords = [w for w in words if w not in self._stopwords and len(w) > 1]
        
        return keywords
    
    def _to_declarative(self, query: str) -> Optional[str]:
        """
        Convert question to declarative statement for better matching.
        
        Args:
            query: Question string
            
        Returns:
            Declarative version or None if not applicable
        """
        # Question patterns to remove/replace
        replacements = [
            ("什么是", ""),
            ("如何", ""),
            ("怎么", ""),
            ("怎样", ""),
            ("为什么", ""),
            ("哪些", ""),
            ("哪个", ""),
            ("请问", ""),
            ("？", ""),
            ("?", ""),
        ]
        
        result = query.strip()
        changed = False
        
        for old, new in replacements:
            if old in result:
                result = result.replace(old, new)
                changed = True
        
        result = result.strip()
        
        # Only return if it changed and has content
        return result if changed and len(result) >= 2 else None


# Global processor instance
# 采用懒汉式单例设计：全局只初始化一次处理器实例，重复调用复用同一个对象；
_processor: Optional[QueryProcessor] = None


def get_query_processor() -> QueryProcessor:
    """Get the global query processor instance."""
    global _processor
    if _processor is None:
        _processor = QueryProcessor()
    return _processor


def reset_query_processor() -> None:
    """Reset the global processor instance. Useful for testing."""
    global _processor
    _processor = None
