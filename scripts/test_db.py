import pymysql
import sys

# Get Windows IP
import subprocess
result = subprocess.run(['cat', '/etc/resolv.conf'], capture_output=True, text=True)
for line in result.stdout.split('\n'):
    if 'nameserver' in line:
        WIN_IP = line.split()[1]
        break

print(f"Testing connection to Windows MySQL at {WIN_IP}:3306")
print("="*60)

try:
    print("1. Attempting to connect...")
    connection = pymysql.connect(
        host=WIN_IP,
        port=3306,
        user='wsl_user',
        database='bms_ged',
        connect_timeout=5
    )
    print("✅ Connection successful!")
    
    print("\n2. Testing database access...")
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE();")
        db = cursor.fetchone()
        print(f"✅ Connected to database: {db[0]}")
        
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        print(f"✅ Found {len(tables)} tables")
    
    connection.close()
    print("\n✅ ALL TESTS PASSED!")
    
except pymysql.err.OperationalError as e:
    print(f"\n❌ Connection Error: {e}")
    print("\nPossible causes:")
    print("1. MySQL not listening on 0.0.0.0 (check my.ini)")
    print("2. Windows Firewall blocking port 3306")
    print("3. Wrong IP address")
    print(f"\nTry: telnet {WIN_IP} 3306")
    
except pymysql.err.OperationalError as e:
    if '1045' in str(e):
        print(f"\n❌ Authentication Error: {e}")
        print("\nThe user/password is wrong or user doesn't have remote access.")
        print("Run this in Windows MySQL:")
        print("  CREATE USER 'bms_bot'@'%' IDENTIFIED BY 'bms2025';")
        print("  GRANT ALL PRIVILEGES ON bms_ged.* TO 'bms_bot'@'%';")
        print("  FLUSH PRIVILEGES;")
    else:
        print(f"\n❌ Database Error: {e}")
        
except Exception as e:
    print(f"\n❌ Unexpected Error: {e}")
    import traceback
    traceback.print_exc()