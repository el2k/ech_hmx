"""
Health check endpoints.
"""

import time
from datetime import datetime

from fastapi import APIRouter

from ..config import get_settings
from ..database import database_health_check
from ..schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Comprehensive health check endpoint.
    
    Returns the overall health status of the service and its dependencies.
    """
    settings = get_settings()
    start_time = time.time()
    
    # Check database health
    db_health = await database_health_check()
    
    # TODO: Add checks for other services (Redis, Vector DB, etc.)
    # 添加其他服务的健康检查逻辑，例如 Redis、向量数据库等。
    redis_health = {"status": "healthy", "response_time_ms": 5}  # Placeholder
    vector_db_health = {"status": "healthy", "response_time_ms": 25}  # Placeholder
    
    # Determine overall status
    # 所有检查的状态，如果有任何一个不健康，则整体状态为不健康。
    all_checks = [db_health, redis_health, vector_db_health]
    overall_status = "healthy" if all(check["status"] == "healthy" for check in all_checks) else "unhealthy"
    
    total_time = round((time.time() - start_time) * 1000, 2)
    
    return HealthResponse(
        status=overall_status,
        version=settings.app_version,
        timestamp=datetime.utcnow().isoformat(),
        checks={
            "database": db_health,
            "redis": redis_health,
            "vector_db": vector_db_health,
            "total_check_time_ms": total_time,
        }
    )

# 这里只是一个简单的健康检查示例，实际生产环境中可能需要更复杂的逻辑，例如检查数据库连接池状态、缓存命中率、外部 API 响应时间等。
@router.get("/ready")
async def readiness_check():
    """
    Kubernetes readiness probe endpoint.
    
    Returns 200 if the service is ready to accept traffic, 503 otherwise.
    """
    # Simple readiness check - just verify database connection
    db_health = await database_health_check()
    
    if db_health["status"] == "healthy":
        return {"status": "ready"}
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Service not ready")

# 这里的 liveness check 只是一个简单的示例，实际生产环境中可能需要更复杂的逻辑，例如检查线程状态、内存使用情况、死锁检测等。
@router.get("/live")
async def liveness_check():
    """
    Kubernetes liveness probe endpoint.
    
    Returns 200 if the service is alive, 503 if it should be restarted.
    """
    # Simple liveness check - just return OK
    # In a real implementation, you might check for deadlocks, memory leaks, etc.
    return {"status": "alive"}
