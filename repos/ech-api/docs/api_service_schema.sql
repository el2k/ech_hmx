-- =====================================================
-- TGO-TECH API SERVICE DATABASE SCHEMA
-- =====================================================
-- Service: API Service (Core Business Logic)
-- Responsibilities: User management, visitor interactions, business operations
-- Tables: api_projects, api_platforms, api_staff, api_visitors, api_visitor_assignments, api_visitor_tags, api_tags
-- =====================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- CORE BUSINESS TABLES
-- =====================================================

-- Projects table: Multi-tenant isolation (MASTER COPY)
CREATE TABLE api_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL COMMENT 'Project name',
    api_key VARCHAR(255) UNIQUE NOT NULL COMMENT 'API key for authentication',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for api_projects
CREATE INDEX idx_api_projects_api_key ON api_projects(api_key);
CREATE INDEX idx_api_projects_deleted_at ON api_projects(deleted_at);

-- Create platform type enum
CREATE TYPE platform_type_enum AS ENUM (
    'website',
    'wechat',
    'whatsapp',
    'telegram',
    'email',
    'sms',
    'facebook',
    'instagram',
    'twitter',
    'linkedin',
    'discord',
    'slack',
    'teams',
    'webchat',
    'phone'
);

-- Platforms table: Communication platforms (WeChat, WhatsApp, etc.)
CREATE TABLE api_platforms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    name VARCHAR(100) NOT NULL COMMENT 'Platform name (e.g., WeChat, WhatsApp)',
    type platform_type_enum NOT NULL COMMENT 'Platform type from predefined enum',
    config JSONB COMMENT 'Platform-specific configuration',
    is_active BOOLEAN NOT NULL DEFAULT true COMMENT 'Whether platform is active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_api_platforms_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE
);

-- Create indexes for api_platforms
CREATE INDEX idx_api_platforms_project_id ON api_platforms(project_id);
CREATE INDEX idx_api_platforms_type ON api_platforms(type);
CREATE INDEX idx_api_platforms_is_active ON api_platforms(is_active);
CREATE INDEX idx_api_platforms_deleted_at ON api_platforms(deleted_at);

-- Staff table: Human users
CREATE TABLE api_staff (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    username VARCHAR(50) UNIQUE NOT NULL COMMENT 'Staff username for login',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Hashed password for authentication (bcrypt, argon2, etc.)',
    nickname VARCHAR(100) COMMENT 'Staff display name',
    avatar_url VARCHAR(255) COMMENT 'Staff avatar URL',
    role VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT 'Staff role: user or agent',
    status VARCHAR(20) NOT NULL DEFAULT 'offline' COMMENT 'Staff status: online, offline, busy',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_api_staff_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE,
    CONSTRAINT chk_api_staff_role CHECK (role IN ('user', 'agent')),
    CONSTRAINT chk_api_staff_status CHECK (status IN ('online', 'offline', 'busy'))
);

-- Create indexes for api_staff
CREATE INDEX idx_api_staff_project_id ON api_staff(project_id);
CREATE INDEX idx_api_staff_role ON api_staff(role);
CREATE INDEX idx_api_staff_status ON api_staff(status);
CREATE INDEX idx_api_staff_deleted_at ON api_staff(deleted_at);

-- Visitors table: External users/customers
CREATE TABLE api_visitors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    platform_id UUID NOT NULL COMMENT 'Associated platform ID',
    platform_open_id VARCHAR(255) NOT NULL COMMENT 'Visitor unique identifier on this platform',
    name VARCHAR(100) COMMENT 'Visitor real name',
    nickname VARCHAR(100) COMMENT 'Visitor nickname on this platform',
    avatar_url VARCHAR(255) COMMENT 'Visitor avatar URL on this platform',
    phone_number VARCHAR(30) COMMENT 'Visitor phone number on this platform',
    email VARCHAR(255) COMMENT 'Visitor email on this platform',
    first_visit_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When the visitor first accessed the system',
    last_visit_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Visitor most recent activity/visit time',
    last_offline_time TIMESTAMP WITH TIME ZONE COMMENT 'Most recent time visitor went offline (NULL when never offline or currently online)',
    is_online BOOLEAN NOT NULL DEFAULT false COMMENT 'Whether the visitor is currently online/active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_api_visitors_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_visitors_platform FOREIGN KEY (platform_id) REFERENCES api_platforms(id)
);

-- Create indexes for api_visitors
CREATE INDEX idx_api_visitors_project_id ON api_visitors(project_id);
CREATE INDEX idx_api_visitors_platform_id ON api_visitors(platform_id);
CREATE INDEX idx_api_visitors_project_platform ON api_visitors(project_id, platform_id);
CREATE INDEX idx_api_visitors_platform_open_id ON api_visitors(platform_id, platform_open_id);
CREATE INDEX idx_api_visitors_last_visit_time ON api_visitors(last_visit_time);
CREATE INDEX idx_api_visitors_last_offline_time ON api_visitors(last_offline_time);
CREATE INDEX idx_api_visitors_is_online ON api_visitors(is_online);
CREATE INDEX idx_api_visitors_online_status_platform ON api_visitors(project_id, platform_id, is_online);
CREATE INDEX idx_api_visitors_project_offline_time ON api_visitors(project_id, last_offline_time);
CREATE INDEX idx_api_visitors_deleted_at ON api_visitors(deleted_at);

-- Visitor assignments table: Track visitor-to-staff assignments
CREATE TABLE api_visitor_assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    visitor_id UUID NOT NULL COMMENT 'Assigned visitor',
    assigned_staff_id UUID COMMENT 'Currently assigned staff member',
    previous_staff_id UUID COMMENT 'Previously assigned staff member',
    assigned_by_staff_id UUID COMMENT 'Staff member who made the assignment',
    assignment_type VARCHAR(20) NOT NULL COMMENT 'Type of assignment: assign, reassign, unassign, auto_assign',
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'When assignment was made',
    notes TEXT COMMENT 'Assignment notes',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_api_visitor_assignments_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_visitor_assignments_visitor FOREIGN KEY (visitor_id) REFERENCES api_visitors(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_visitor_assignments_assigned_staff FOREIGN KEY (assigned_staff_id) REFERENCES api_staff(id),
    CONSTRAINT fk_api_visitor_assignments_previous_staff FOREIGN KEY (previous_staff_id) REFERENCES api_staff(id),
    CONSTRAINT fk_api_visitor_assignments_assigned_by_staff FOREIGN KEY (assigned_by_staff_id) REFERENCES api_staff(id),
    CONSTRAINT chk_api_visitor_assignments_type CHECK (assignment_type IN ('assign', 'reassign', 'unassign', 'auto_assign'))
);

-- Create indexes for api_visitor_assignments
CREATE INDEX idx_api_visitor_assignments_project_id ON api_visitor_assignments(project_id);
CREATE INDEX idx_api_visitor_assignments_visitor_id ON api_visitor_assignments(visitor_id);
CREATE INDEX idx_api_visitor_assignments_assigned_staff_id ON api_visitor_assignments(assigned_staff_id);
CREATE INDEX idx_api_visitor_assignments_timestamp ON api_visitor_assignments(timestamp);
CREATE INDEX idx_api_visitor_assignments_assignment_type ON api_visitor_assignments(assignment_type);

-- Tags table: Categorization and labeling system
CREATE TABLE api_tags (
    id VARCHAR(255) PRIMARY KEY COMMENT 'Base64 encoded ID: base64_encode(name + "@" + category)',
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    name VARCHAR(50) NOT NULL COMMENT 'Tag name',
    category VARCHAR(20) NOT NULL COMMENT 'Tag category: visitor (for customer categorization) or knowledge (for content categorization), aiPersona (for AI persona)',
    weight INTEGER NOT NULL DEFAULT 0 COMMENT 'Tag importance/priority weight (0-10, higher values indicate higher priority)',
    color VARCHAR(20) COMMENT 'Tag color',
    description VARCHAR(255) COMMENT 'Tag description',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_api_tags_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE,
    CONSTRAINT uk_api_tags_project_name UNIQUE (project_id, name),
    CONSTRAINT chk_api_tags_category CHECK (category IN ('visitor', 'knowledge')),
    CONSTRAINT chk_api_tags_weight CHECK (weight >= 0 AND weight <= 10)
);

-- Create indexes for api_tags
CREATE INDEX idx_api_tags_project_id ON api_tags(project_id);
CREATE INDEX idx_api_tags_project_name ON api_tags(project_id, name);
CREATE INDEX idx_api_tags_category ON api_tags(category);
CREATE INDEX idx_api_tags_weight ON api_tags(weight);
CREATE INDEX idx_api_tags_project_category ON api_tags(project_id, category);
CREATE INDEX idx_api_tags_project_weight ON api_tags(project_id, weight);
CREATE INDEX idx_api_tags_category_weight ON api_tags(category, weight);
CREATE INDEX idx_api_tags_project_category_weight ON api_tags(project_id, category, weight);
CREATE INDEX idx_api_tags_deleted_at ON api_tags(deleted_at);

-- Visitor tags table: Many-to-many relationship between visitors and tags
CREATE TABLE api_visitor_tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL COMMENT 'Associated project ID for multi-tenant isolation',
    visitor_id UUID NOT NULL COMMENT 'Associated visitor ID',
    tag_id VARCHAR(255) NOT NULL COMMENT 'Associated tag ID (Base64 encoded)',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_api_visitor_tags_project FOREIGN KEY (project_id) REFERENCES api_projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_visitor_tags_visitor FOREIGN KEY (visitor_id) REFERENCES api_visitors(id),
    CONSTRAINT fk_api_visitor_tags_tag FOREIGN KEY (tag_id) REFERENCES api_tags(id),
    CONSTRAINT uk_api_visitor_tags_visitor_tag UNIQUE (visitor_id, tag_id)
);

-- Create indexes for api_visitor_tags
CREATE INDEX idx_api_visitor_tags_project_id ON api_visitor_tags(project_id);
CREATE INDEX idx_api_visitor_tags_visitor_id ON api_visitor_tags(visitor_id);
CREATE INDEX idx_api_visitor_tags_tag_id ON api_visitor_tags(tag_id);
CREATE INDEX idx_api_visitor_tags_project_visitor ON api_visitor_tags(project_id, visitor_id);

-- =====================================================
-- END OF API SERVICE SCHEMA
-- =====================================================
