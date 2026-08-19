#!/usr/bin/env python3
"""Test script to verify the project setup."""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """Test that all modules can be imported."""
    print("🔍 Testing imports...")
    
    try:
        # Test core modules
        from app.core.config import settings
        print("✅ Core config imported")
        
        from app.core.logging import setup_logging
        print("✅ Core logging imported")
        
        from app.core.security import create_access_token
        print("✅ Core security imported")
        
        from app.core.exceptions import TGOAPIException
        print("✅ Core exceptions imported")
        
        # Test models
        from app.models import Project, Staff, Visitor, Platform, Tag
        print("✅ Models imported")
        
        # Test schemas
        from app.schemas import ProjectCreate, StaffCreate, VisitorCreate
        print("✅ Schemas imported")
        
        # Test main app
        from app.main import app
        print("✅ FastAPI app imported")
        
        print("🎉 All imports successful!")
        return True
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_configuration():
    """Test configuration loading."""
    print("\n🔧 Testing configuration...")
    
    try:
        from app.core.config import settings
        
        # Test basic settings
        assert settings.PROJECT_NAME == "TGO-Tech API Service"
        assert settings.API_V1_STR == "/v1"
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES > 0
        
        print("✅ Configuration loaded successfully")
        print(f"   Project: {settings.PROJECT_NAME}")
        print(f"   Version: {settings.PROJECT_VERSION}")
        print(f"   Environment: {settings.ENVIRONMENT}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False


def test_models():
    """Test model creation."""
    print("\n🗄️ Testing models...")
    
    try:
        from app.models import Project, Staff, Visitor
        from uuid import uuid4
        
        # Test model instantiation (without database)
        project = Project(
            name="Test Project",
            api_key="test_key"
        )
        
        staff = Staff(
            project_id=uuid4(),
            username="test_user",
            password_hash="hashed_password"
        )
        
        visitor = Visitor(
            project_id=uuid4(),
            platform_id=uuid4(),
            platform_open_id="test_visitor"
        )
        
        print("✅ Models can be instantiated")
        print(f"   Project: {project.name}")
        print(f"   Staff: {staff.username}")
        print(f"   Visitor: {visitor.platform_open_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Model test failed: {e}")
        return False


def test_schemas():
    """Test schema validation."""
    print("\n📋 Testing schemas...")
    
    try:
        from app.schemas import ProjectCreate, StaffCreate, VisitorCreate
        from app.models import StaffRole, PlatformType
        
        # Test schema validation
        project_data = ProjectCreate(name="Test Project")
        print(f"✅ ProjectCreate: {project_data.name}")
        
        staff_data = StaffCreate(
            username="test_user",
            password="test_password",
            role=StaffRole.USER
        )
        print(f"✅ StaffCreate: {staff_data.username}")
        
        visitor_data = VisitorCreate(
            platform_open_id="test_visitor",
            platform_type=PlatformType.WEBSITE
        )
        print(f"✅ VisitorCreate: {visitor_data.platform_open_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Schema test failed: {e}")
        return False


def test_security():
    """Test security functions."""
    print("\n🔐 Testing security...")
    
    try:
        from app.core.security import create_access_token, get_password_hash, verify_password
        
        # Test password hashing
        password = "test_password"
        hashed = get_password_hash(password)
        is_valid = verify_password(password, hashed)
        
        assert is_valid, "Password verification failed"
        print("✅ Password hashing works")
        
        # Test token creation
        token = create_access_token("test_user")
        assert token, "Token creation failed"
        print("✅ JWT token creation works")
        
        return True
        
    except Exception as e:
        print(f"❌ Security test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("🚀 TGO-Tech API Setup Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_configuration,
        test_models,
        test_schemas,
        test_security,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        else:
            break
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! Your setup is working correctly.")
        print("💡 You can now run 'make dev' to start the development environment.")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
