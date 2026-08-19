"""Seed initial AI models into api_ai_models table.

Usage:
    python3 scripts/seed_ai_models.py

This script is idempotent: it upserts by (provider, model_id).
"""
from __future__ import annotations

# Ensure repository root is importable so `import app` works when running as a script
import sys
from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models import AIModel

logger = get_logger("seed.ai_models")


def _openai_models() -> List[Dict[str, Any]]:
    return [
        {
            "provider": "openai",
            "model_id": "gpt-4",
            "model_name": "GPT-4",
            "model_type": "chat",
            "description": "OpenAI GPT-4",
            "capabilities": {"vision": False, "function_calling": True, "streaming": True},
            "context_window": 8192,
            "max_tokens": 4096,
            "is_active": True,
        },
        {
            "provider": "openai",
            "model_id": "gpt-4-turbo",
            "model_name": "GPT-4 Turbo",
            "model_type": "chat",
            "description": "OpenAI GPT-4 Turbo with vision",
            "capabilities": {"vision": True, "function_calling": True, "streaming": True},
            "context_window": 128000,
            "max_tokens": 4096,
            "is_active": True,
        },
        {
            "provider": "openai",
            "model_id": "gpt-3.5-turbo",
            "model_name": "GPT-3.5 Turbo",
            "model_type": "chat",
            "description": "OpenAI GPT-3.5 Turbo",
            "capabilities": {"vision": False, "function_calling": True, "streaming": True},
            "context_window": 16385,
            "max_tokens": 4096,
            "is_active": True,
        },
        {
            "provider": "openai",
            "model_id": "text-embedding-ada-002",
            "model_name": "Text Embedding Ada 002",
            "model_type": "embedding",
            "description": "OpenAI embedding model Ada 002",
            "capabilities": {"vision": False, "function_calling": False, "streaming": False},
            "context_window": 8191,
            "max_tokens": None,
            "is_active": True,
        },
        {
            "provider": "openai",
            "model_id": "text-embedding-3-small",
            "model_name": "Text Embedding 3 Small",
            "model_type": "embedding",
            "description": "OpenAI embedding model 3 small",
            "capabilities": {"vision": False, "function_calling": False, "streaming": False},
            "context_window": 8191,
            "max_tokens": None,
            "is_active": True,
        },
    ]


def _anthropic_models() -> List[Dict[str, Any]]:
    common = {
        "capabilities": {"vision": True, "function_calling": False, "streaming": True},
        "context_window": 200000,
        "max_tokens": 4096,
        "is_active": True,
    }
    return [
        {
            "provider": "anthropic",
            "model_id": "claude-3-opus-20240229",
            "model_name": "Claude 3 Opus",
            "model_type": "chat",
            "description": "Anthropic Claude 3 Opus",
            **common,
        },
        {
            "provider": "anthropic",
            "model_id": "claude-3-sonnet-20240229",
            "model_name": "Claude 3 Sonnet",
            "model_type": "chat",
            "description": "Anthropic Claude 3 Sonnet",
            **common,
        },
        {
            "provider": "anthropic",
            "model_id": "claude-3-haiku-20240307",
            "model_name": "Claude 3 Haiku",
            "model_type": "chat",
            "description": "Anthropic Claude 3 Haiku",
            **common,
        },
    ]


def _dashscope_models() -> List[Dict[str, Any]]:
    # For DashScope/Qwen, accurate limits vary by plan/version; leave unknown sizes as None to avoid inaccurate data.
    return [
        {
            "provider": "dashscope",
            "model_id": "qwen-max",
            "model_name": "Qwen-Max",
            "model_type": "chat",
            "description": "Alibaba DashScope Qwen-Max",
            "capabilities": {"vision": True, "function_calling": True, "streaming": True},
            "context_window": None,
            "max_tokens": None,
            "is_active": True,
        },
        {
            "provider": "dashscope",
            "model_id": "qwen-plus",
            "model_name": "Qwen-Plus",
            "model_type": "chat",
            "description": "Alibaba DashScope Qwen-Plus",
            "capabilities": {"vision": True, "function_calling": True, "streaming": True},
            "context_window": None,
            "max_tokens": None,
            "is_active": True,
        },
        {
            "provider": "dashscope",
            "model_id": "qwen-turbo",
            "model_name": "Qwen-Turbo",
            "model_type": "chat",
            "description": "Alibaba DashScope Qwen-Turbo",
            "capabilities": {"vision": True, "function_calling": True, "streaming": True},
            "context_window": None,
            "max_tokens": None,
            "is_active": True,
        },
    ]


def _azure_openai_from_openai(openai_seeds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clones = []
    for m in openai_seeds:
        clone = dict(m)
        clone["provider"] = "azure_openai"
        clones.append(clone)
    return clones


def build_seed_data() -> List[Dict[str, Any]]:
    openai = _openai_models()
    azure = _azure_openai_from_openai(openai)
    anthropic = _anthropic_models()
    dashscope = _dashscope_models()
    return openai + azure + anthropic + dashscope


def upsert_models(session, seeds: List[Dict[str, Any]]) -> dict:
    inserted = 0
    updated = 0
    for data in seeds:
        provider = data["provider"]
        model_id = data["model_id"]
        item: Optional[AIModel] = (
            session.query(AIModel).filter(
                AIModel.provider == provider,
                AIModel.model_id == model_id,
            ).first()
        )
        if item:
            # Update existing, restore if soft-deleted
            for k, v in data.items():
                setattr(item, k, v)
            item.deleted_at = None
            item.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            item = AIModel(**data)
            session.add(item)
            inserted += 1
    session.commit()
    return {"inserted": inserted, "updated": updated}


def main() -> None:
    seeds = build_seed_data()
    session = SessionLocal()
    try:
        result = upsert_models(session, seeds)
        logger.info(
            "Seeded AI models", extra={"inserted": result["inserted"], "updated": result["updated"], "total": len(seeds)}
        )
        print(f"Seed completed: inserted={result['inserted']} updated={result['updated']} total={len(seeds)}")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to seed AI models: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()

