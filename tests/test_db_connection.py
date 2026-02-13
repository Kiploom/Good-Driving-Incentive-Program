#!/usr/bin/env python3
"""
Database Connection Test Script
Run this on your EC2 instance to diagnose database connection issues.

Usage (from project root):
    cd /home/ubuntu/gooddriver
    source venv/bin/activate  # or: flask/venv/bin/activate
    python tests/test_db_connection.py

Or from flask directory (legacy):
    cd flask && python -c "import sys; sys.path.insert(0,'..'); exec(open('../tests/test_db_connection.py').read())"
"""

import os
import sys
from pathlib import Path

# Ensure .env is loaded from flask/ directory
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
DEFAULT_ENV = PROJECT_ROOT / "flask" / ".env"

from dotenv import load_dotenv, find_dotenv

env_path = DEFAULT_ENV if DEFAULT_ENV.exists() else find_dotenv()
if not env_path:
    print("❌ ERROR: .env file not found!")
    print("   Expected at flask/.env or set ENV_PATH. Run from project root.")
    sys.exit(1)
load_dotenv(env_path)
print(f"✓ Loaded .env from: {env_path}")

# Get database credentials
db_host = os.getenv("DB_HOST")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")
db_port = os.getenv("DB_PORT", "3306")

# Check if all required variables are set
missing = []
if not db_host:
    missing.append("DB_HOST")
if not db_user:
    missing.append("DB_USER")
if not db_password:
    missing.append("DB_PASSWORD")
if not db_name:
    missing.append("DB_NAME")

if missing:
    print(f"❌ ERROR: Missing required environment variables: {', '.join(missing)}")
    sys.exit(1)

print("\n📋 Database Configuration:")
print(f"   Host: {db_host}")
print(f"   User: {db_user}")
print(f"   Database: {db_name}")
print(f"   Port: {db_port}")
print(f"   Password: {'*' * len(db_password) if db_password else 'NOT SET'}")

# Try to import pymysql
try:
    import pymysql
    print("\n✓ pymysql module found")
except ImportError:
    print("\n❌ ERROR: pymysql module not found!")
    print("   Install it with: pip install pymysql")
    sys.exit(1)

# Test connection
print("\n🔌 Testing database connection...")
try:
    conn = pymysql.connect(
        host=db_host,
        user=db_user,
        password=db_password,
        database=db_name,
        port=int(db_port),
        connect_timeout=10
    )
    print("✓ Connection successful!")
    
    # Test a simple query
    cursor = conn.cursor()
    cursor.execute("SELECT 1 as test")
    result = cursor.fetchone()
    print(f"✓ Query test successful: {result}")
    
    # Check database name
    cursor.execute("SELECT DATABASE()")
    db = cursor.fetchone()
    print(f"✓ Connected to database: {db[0]}")
    
    cursor.close()
    conn.close()
    print("\n✅ All database tests passed!")
    
except pymysql.err.OperationalError as e:
    error_code, error_msg = e.args
    print(f"\n❌ Connection failed!")
    print(f"   Error Code: {error_code}")
    print(f"   Error Message: {error_msg}")
    
    if error_code == 1045:
        print("\n💡 This is an authentication error. Possible causes:")
        print("   1. Wrong password in .env file")
        print("   2. RDS security group doesn't allow connections from this IP")
        print("   3. MySQL user doesn't have permissions from this host")
        print("\n   Check:")
        print("   - Verify DB_PASSWORD in .env matches RDS master password")
        print("   - Verify RDS security group allows MySQL (3306) from this EC2 instance")
        print("   - Check MySQL user permissions: SELECT user, host FROM mysql.user WHERE user = 'admin';")
    elif error_code == 2003:
        print("\n💡 Cannot connect to database server. Possible causes:")
        print("   1. RDS security group doesn't allow connections from this IP")
        print("   2. Wrong DB_HOST in .env file")
        print("   3. RDS instance is not publicly accessible (if connecting from outside VPC)")
    elif error_code == 1049:
        print("\n💡 Database doesn't exist. Check DB_NAME in .env file.")
    
    sys.exit(1)
    
except Exception as e:
    print(f"\n❌ Unexpected error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
