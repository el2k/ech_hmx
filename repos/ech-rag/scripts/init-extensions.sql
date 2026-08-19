-- Initialize PostgreSQL extensions for RAG service
-- This script runs before the main schema creation
-- 脚本开头通过 CREATE EXTENSION IF NOT EXISTS 安全地启用了五个核心扩展，为 RAG 服务提供底层能力支持：
-- uuid-ossp：提供生成 UUID（通用唯一识别码）的函数，通常用于生成数据表的主键 ID。
-- vector：即 pgvector 扩展，这是 RAG 系统的核心，允许数据库存储向量数据（Embeddings）并执行向量相似度计算34。
-- pg_trgm：提供基于三元组（trigram）的文本相似度计算和模糊匹配功能，常用于拼写纠错或模糊搜索。
-- btree_gin：为 GIN 索引增加对 B-tree 数据类型的支持，提升高级组合索引的查询性能。
-- unaccent：用于文本规范化，去除文本中的重音符号（如将 é 转为 e），提升多语言文本检索的准确性。
-- Enable UUID extension for generating UUIDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgvector extension for vector operations
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable pg_trgm for text similarity and fuzzy matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Enable btree_gin for advanced indexing
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Enable unaccent for text normalization
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Create a function to generate timestamp with timezone
-- 创建自动更新时间戳的触发器函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create a function for full-text search ranking
-- 创建全文检索排序函数
CREATE OR REPLACE FUNCTION calculate_search_rank(
    query_text text,
    content_text text,
    title_text text DEFAULT ''
)
RETURNS float AS $$
BEGIN
    RETURN (
        ts_rank_cd(
            to_tsvector('english', COALESCE(title_text, '')),
            plainto_tsquery('english', query_text)
        ) * 2.0 +
        ts_rank_cd(
            to_tsvector('english', COALESCE(content_text, '')),
            plainto_tsquery('english', query_text)
        )
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Create a function for vector similarity search with metadata filtering
-- 创建带元数据过滤的向量相似度搜索函数
CREATE OR REPLACE FUNCTION vector_similarity_search(
    query_embedding vector,
    collection_filter uuid DEFAULT NULL,
    content_type_filter text DEFAULT NULL,
    language_filter text DEFAULT NULL,
    min_confidence float DEFAULT 0.0,
    result_limit int DEFAULT 20
)
RETURNS TABLE(
    id uuid,
    similarity_score float,
    content text,
    document_title text,
    collection_id uuid,
    content_type text,
    language text,
    confidence_score float
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        rfd.id,
        1 - (rfd.embedding <=> query_embedding) as similarity_score,
        rfd.content,
        rfd.document_title,
        rfd.collection_id,
        rfd.content_type,
        rfd.language,
        rfd.confidence_score
    FROM rag_file_documents rfd
    WHERE 
        (collection_filter IS NULL OR rfd.collection_id = collection_filter)
        AND (content_type_filter IS NULL OR rfd.content_type = content_type_filter)
        AND (language_filter IS NULL OR rfd.language = language_filter)
        AND (rfd.confidence_score IS NULL OR rfd.confidence_score >= min_confidence)
        AND rfd.embedding IS NOT NULL
    ORDER BY rfd.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;
