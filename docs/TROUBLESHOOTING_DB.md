# Database Connection Troubleshooting Guide

## Error: Access denied for user 'admin'@'172.31.13.94'

This error occurs when the Flask app on EC2 cannot authenticate to RDS MySQL.

### Step 1: Verify .env file on EC2 server

SSH into your EC2 instance and check the `.env` file:

```bash
ssh ubuntu@your-ec2-ip
cd /home/ubuntu/gooddriver/flask
cat .env | grep DB_
```

Ensure these values match your RDS credentials:
- `DB_HOST=database-1.canaaa0ysp9s.us-east-1.rds.amazonaws.com`
- `DB_USER=admin`
- `DB_PASSWORD=V!2*cH*(t9Ux|fXNPpf(_.9HNn_A`
- `DB_NAME=gooddriver`
- `DB_PORT=3306`

**Important**: The password contains special characters (`!`, `*`, `(`, `)`, `|`, `_`). Make sure:
- No extra spaces or quotes around the password
- The password is exactly as shown (no escaping needed in .env)
- The .env file uses Unix line endings (LF, not CRLF)

### Step 2: Test database connection manually

On your EC2 instance, test the connection:

```bash
# Install mysql client if needed
sudo apt-get update
sudo apt-get install mysql-client -y

# Test connection
mysql -h database-1.canaaa0ysp9s.us-east-1.rds.amazonaws.com \
      -u admin \
      -p'V!2*cH*(t9Ux|fXNPpf(_.9HNn_A' \
      -D gooddriver \
      -e "SELECT 1;"
```

If this fails, the issue is with credentials or network access.

### Step 3: Check RDS Security Group

1. Go to AWS Console → RDS → Your database instance
2. Click on the **Security** tab
3. Check the **Security groups** associated with your RDS instance
4. Click on the security group → **Inbound rules**
5. Ensure there's a rule allowing MySQL (port 3306) from:
   - Your EC2 instance's security group, OR
   - The EC2 instance's private IP (172.31.13.94), OR
   - The EC2 instance's subnet CIDR (e.g., 172.31.0.0/16)

**Recommended**: Allow from EC2 security group (not IP address) for easier management.

### Step 4: Verify RDS user permissions

Connect to RDS from a machine that can access it (or use AWS RDS Query Editor) and check:

```sql
-- Check if user exists and from which hosts
SELECT user, host FROM mysql.user WHERE user = 'admin';

-- Check user privileges
SHOW GRANTS FOR 'admin'@'%';
```

The user should be able to connect from `%` (any host) or specifically from `172.31.13.94`.

### Step 5: Check if password needs to be reset

If the password was changed in RDS but not updated in .env:

1. Reset the RDS master password (if you have access):
   - AWS Console → RDS → Your instance → Modify
   - Change master password
   - Update `.env` file on EC2 with new password

2. Or update the .env file if you know the correct password

### Step 6: Restart Gunicorn after .env changes

After updating `.env`, restart your Flask app:

```bash
sudo systemctl restart gunicorn
# Or if using supervisor/systemd:
sudo systemctl restart your-app-service

# Check logs
sudo journalctl -u gunicorn -f
# Or
tail -f /var/log/gunicorn/error.log
```

### Step 7: Verify environment variables are loaded

Add temporary debug logging to verify credentials are loaded:

```python
# In flask/config.py, temporarily add:
print(f"DB_HOST: {db_config['host']}")
print(f"DB_USER: {db_config['user']}")
print(f"DB_PASSWORD: {'*' * len(db_config['password']) if db_config['password'] else 'NOT SET'}")
```

### Common Issues:

1. **Password with special characters**: MySQL passwords with `!`, `*`, `(`, `)`, `|` should work, but ensure no shell interpretation. Use quotes in command line, but NOT in .env file.

2. **.env file location**: Ensure `.env` is in `/home/ubuntu/gooddriver/flask/` (where `config.py` looks for it).

3. **Environment variables**: If using systemd, ensure environment variables are loaded. Check your service file:
   ```ini
   [Service]
   EnvironmentFile=/home/ubuntu/gooddriver/flask/.env
   ```

4. **Working directory**: Ensure gunicorn runs from the correct directory where `.env` exists.

### Quick Fix Script

Run the database connection test script (from project root):

```bash
cd /home/ubuntu/gooddriver
source venv/bin/activate  # or: flask/venv/bin/activate
python tests/test_db_connection.py
```

The script loads `.env` from `flask/.env` and tests the connection.
