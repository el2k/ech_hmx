#!/usr/bin/env python3
"""Reset admin password script.

This script resets the admin user's password to a new randomly generated password.
The new password is output to the console.

Usage:
    # In Docker container:
    docker exec tgo-api resetadmin
    
    # Or directly with Python:
    python scripts/reset_admin_password.py

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (auto-detected from app config if not set)
    
Example:
    DATABASE_URL="postgresql://user:pass@localhost:5432/tgo_api" python scripts/reset_admin_password.py
"""

import os
import secrets
import string
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Fixed admin username (same as in setup.py)
ADMIN_USERNAME = "admin"


def generate_secure_password(length: int = 16) -> str:
    """Generate a secure random password.
    
    Args:
        length: Password length (default: 16)
        
    Returns:
        A secure random password containing letters, digits, and special characters
    """
    # Use a mix of characters for security
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Ensure at least one of each type
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    # Fill the rest randomly
    password.extend(secrets.choice(alphabet) for _ in range(length - 4))
    # Shuffle to avoid predictable positions
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def get_sync_database_url() -> str:
    """Get synchronous database URL from environment or app config.
    
    Ensures the URL uses psycopg2 driver for synchronous operations.
    """
    # First try environment variable
    database_url = os.getenv("DATABASE_URL")
    
    # If not in env, try to get from app config (for Docker container)
    if not database_url:
        try:
            from app.core.config import settings
            # Use the sync URL directly from settings
            return settings.database_url_sync
        except Exception:
            pass
    
    if not database_url:
        print("Error: DATABASE_URL not found")
        print("Please set DATABASE_URL environment variable or ensure app config is available")
        print("Example: DATABASE_URL='postgresql://user:pass@localhost:5432/tgo_api' python scripts/reset_admin_password.py")
        sys.exit(1)
    
    # Convert to sync URL (psycopg2 driver)
    if "postgresql+asyncpg://" in database_url:
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    if "postgresql+psycopg2://" in database_url:
        return database_url
    if "postgresql://" in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg2://")
    
    # Fallback: enforce psycopg2
    if "://" in database_url:
        _, rest = database_url.split("://", 1)
        return f"postgresql+psycopg2://{rest}"
    
    return database_url


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt directly (avoids passlib compatibility issues)."""
    import bcrypt
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def reset_admin_password() -> None:
    """Reset the admin user's password."""
    # Import here to avoid issues if running outside app context
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.staff import Staff
    
    # Get synchronous database URL
    database_url = get_sync_database_url()
    
    # Create database connection
    try:
        engine = create_engine(database_url)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
    except Exception as e:
        print(f"Error: Failed to connect to database: {e}")
        sys.exit(1)
    
    try:
        # Find admin user
        admin = db.query(Staff).filter(
            Staff.username == ADMIN_USERNAME,
            Staff.deleted_at.is_(None)
        ).first()
        
        if not admin:
            print(f"Error: Admin user '{ADMIN_USERNAME}' not found")
            print("Please run the setup process first to create the admin account")
            sys.exit(1)
        
        # Generate new password
        new_password = generate_secure_password()
        
        # Hash and update password
        admin.password_hash = get_password_hash(new_password)
        db.commit()
        
        # Output results
        print("=" * 50)
        print("Admin password reset successful!")
        print("=" * 50)
        print(f"Username: {ADMIN_USERNAME}")
        print(f"New Password: {new_password}")
        print("=" * 50)
        print("IMPORTANT: Please save this password securely!")
        print("This password will not be shown again.")
        print("=" * 50)
        
    except Exception as e:
        db.rollback()
        print(f"Error: Failed to reset password: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    reset_admin_password()

