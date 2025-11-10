#!/usr/bin/env python3
"""
Debug script to test database connection from within the container.
Run this inside the API container to diagnose connection issues.
"""
import os
import socket
from pathlib import Path

print("=" * 60)
print("Database Connection Debug")
print("=" * 60)
print()

# Check environment variables
print("📋 Environment Variables:")
print("-" * 60)
env_vars = [
    'DB_TYPE', 'DB_MODE', 'DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PORT',
    'DB_PASSWORD', 'DB_PASSWORD_FILE', 'DATABASE_URL',
    'NEO4J_URL', 'REDIS_URL', 'STACK_NAME'
]

for var in env_vars:
    value = os.getenv(var, '<NOT SET>')
    # Mask passwords
    if 'PASSWORD' in var and value != '<NOT SET>':
        value = '***MASKED***'
    print(f"  {var:20} = {value}")
print()

# Check secrets
print("🔐 Docker Secrets:")
print("-" * 60)
secrets_dir = Path('/run/secrets')
if secrets_dir.exists():
    for secret_file in secrets_dir.iterdir():
        if secret_file.is_file():
            try:
                content = secret_file.read_text().strip()
                masked = '***' + content[-4:] if len(content) > 4 else '***'
                print(f"  {secret_file.name}: exists ({len(content)} chars, ends with {masked})")
            except Exception as e:
                print(f"  {secret_file.name}: ERROR reading - {e}")
else:
    print("  ⚠️  /run/secrets directory does not exist")
print()

# DNS Resolution Test
print("🌐 DNS Resolution:")
print("-" * 60)
hosts_to_test = [
    'postgres',
    'python-api-template_postgres',
    os.getenv('DB_HOST', 'postgres'),
    'redis',
    'python-api-template_redis',
    'neo4j',
    'python-api-template_neo4j'
]

for host in set(hosts_to_test):  # Remove duplicates
    try:
        ip = socket.gethostbyname(host)
        print(f"  ✅ {host:35} -> {ip}")
    except socket.gaierror as e:
        print(f"  ❌ {host:35} -> FAILED: {e}")
print()

# Port connectivity test
print("🔌 Port Connectivity:")
print("-" * 60)
db_host = os.getenv('DB_HOST', 'postgres')
db_port = int(os.getenv('DB_PORT', '5432'))

def test_port(host, port, timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        return False

print(f"  Testing {db_host}:{db_port}...")
if test_port(db_host, db_port):
    print(f"  ✅ Port {db_port} is OPEN on {db_host}")
else:
    print(f"  ❌ Port {db_port} is CLOSED on {db_host}")
print()

# Try to build database URL
print("🔗 Database URL Construction:")
print("-" * 60)
db_type = os.getenv('DB_TYPE', 'postgresql')
db_mode = os.getenv('DB_MODE', 'local')
database_url = os.getenv('DATABASE_URL', '')

print(f"  DB_TYPE: {db_type}")
print(f"  DB_MODE: {db_mode}")

if database_url:
    # Mask password in URL
    import re
    masked_url = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', database_url)
    print(f"  DATABASE_URL: {masked_url}")
else:
    print(f"  DATABASE_URL: <NOT SET>")
    
    # Try to construct URL
    db_password_file = os.getenv('DB_PASSWORD_FILE', '')
    if db_password_file and Path(db_password_file).exists():
        password = Path(db_password_file).read_text().strip()
        password_masked = '***' + password[-4:] if len(password) > 4 else '***'
        print(f"  Password from file: {password_masked} ({len(password)} chars)")
        
        constructed_url = f"{db_type}://{os.getenv('DB_USER')}:***@{db_host}:{db_port}/{os.getenv('DB_NAME')}"
        print(f"  Constructed URL: {constructed_url}")
    else:
        print(f"  ⚠️  Cannot construct URL - DB_PASSWORD_FILE not set or doesn't exist")

print()
print("=" * 60)
print("Debug complete!")
print("=" * 60)
