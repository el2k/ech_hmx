from pydantic import BaseModel, Field, JsonValue
from typing import Optional, Dict, Any
from datetime import datetime

class ToolExecuteRequest(BaseModel):
    """Request schema for executing a tool."""
    inputs: Dict[str, JsonValue] = Field(..., description="Input parameters for the tool")

class ToolExecuteResponse(BaseModel):
    """Response schema for tool execution."""
    success: bool = Field(..., description="Whether the tool execution was successful")
    result: Optional[JsonValue] = Field(None, description="The result of the tool execution")
    error: Optional[str] = Field(None, description="Error message if the execution failed")
    execution_time: Optional[float] = Field(None, description="Time taken to execute the tool in seconds")

class ToolResponse(BaseModel):
    """Schema for Tool API responses, simplified for workflow engine usage."""
    id: str = Field(..., description="Unique identifier of the tool")
    project_id: str = Field(..., description="The ID of the project this tool belongs to")
    name: str = Field(..., description="Name of the tool")
    description: Optional[str] = Field(None, description="Description of the tool")
    tool_type: str = Field(..., description="Type of the tool (e.g., MCP, FUNCTION)")
    # Add other fields if necessary, but these are likely enough for the executor to log or check

