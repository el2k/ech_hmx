"""MCP-related Pydantic schemas."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# MCP工具定义的Pydantic模型，用于描述从设备获取的工具信息，包括名称、描述和输入参数的JSON Schema。
class MCPToolDefinition(BaseModel):
    """Schema for an MCP tool definition (from device)."""

    name: str = Field(..., description="Tool name")
    description: Optional[str] = Field(None, description="Tool description")
    inputSchema: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for inputs",
    )

# MCP工具列表响应的Pydantic模型，用于描述从设备获取的工具列表。
class MCPToolsListResponse(BaseModel):
    """Response schema for listing MCP tools."""

    tools: List[MCPToolDefinition]

# MCP工具调用请求的Pydantic模型，用于描述调用MCP工具时的请求参数，包括工具名称和输入参数。
class MCPToolCallRequest(BaseModel):
    """Request schema for calling an MCP tool (REST helper)."""

    name: str = Field(..., description="Tool name to call")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )

# MCP工具调用响应的Pydantic模型，用于描述调用MCP工具后的响应结果，包括返回内容和是否发生错误的标志。
class MCPToolCallResponse(BaseModel):
    """Response schema for MCP tool call."""

    content: Optional[List[Dict[str, Any]]] = None
    isError: bool = False
