# AWS Overview & Operations Guide

This document describes the AWS setup for the Good-Driving-Incentive-Program and how to connect, view logs, and manage it from the terminal.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Mobile App     │     │  Web Browser     │     │  AWS S3         │
│  (Android)      │     │  (Driver/Sponsor)│     │  (Profile pics) │
└────────┬────────┘     └────────┬─────────┘     └────────▲────────┘
         │                       │                        │
         │    HTTP/HTTPS         │                        │ Presigned URLs
         ▼                       ▼                        │
┌─────────────────────────────────────────────────────────────────────┐
│  EC2 Instance (Ubuntu)                                               │
│  - Flask app via Gunicorn (port 5000)                                 │
│  - App path: /home/ubuntu/gooddriver/                                 │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 │ MySQL (private VPC)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  RDS MySQL (us-east-1)                                               │
│  - Database: gooddriver                                              │
│  - Private endpoint (EC2 → RDS via security group)                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## AWS Components

| Component | Purpose |
|-----------|---------|
| **EC2** | Runs the Flask backend (Gunicorn). Web + mobile API. |
| **RDS MySQL** | Persistent database for accounts, drivers, orders, etc. |
| **S3** | Profile picture storage (avatars). Uses presigned URLs. |
| **Security Groups** | Control inbound/outbound traffic (EC2, RDS). |

---

## Prerequisites

- **SSH key** (`.pem`) for the EC2 instance (downloaded when creating the instance)
- **AWS CLI** (optional, for console-less inspection): `aws configure`
- **EC2 IP or hostname** (public IP or Elastic IP)

---

## 1. Connect to EC2 via SSH

### Get connection details

If you don't have the IP:

```bash
# List running EC2 instances (requires AWS CLI + credentials)
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=running" \
  --query "Reservations[*].Instances[*].[PublicIpAddress,InstanceId,Tags[?Key=='Name'].Value|[0]]" \
  --output table
```

Or use the **AWS Console** → EC2 → Instances → copy the **Public IPv4 address**.

### SSH into the instance

```bash
# Replace with your EC2 public IP and key path
ssh -i /path/to/your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

Example (if your key is `gooddriver.pem` and IP is `98.89.178.156`):

```bash
ssh -i ~/.ssh/gooddriver.pem ubuntu@98.89.178.156
```

### First-time SSH tips

- Ensure key permissions: `chmod 400 /path/to/your-key.pem`
- If you get "Permission denied (publickey)", verify the key pair matches the instance
- Default user is `ubuntu` for Amazon Linux 2 / Ubuntu AMIs

---

## 2. View Live Application Logs

Once connected via SSH:

### Gunicorn / Flask logs (primary)

```bash
# Follow logs in real time (live tail)
sudo journalctl -u gunicorn -f

# Last 100 lines
sudo journalctl -u gunicorn -n 100

# Logs since boot
sudo journalctl -u gunicorn -b

# Logs from last hour
sudo journalctl -u gunicorn --since "1 hour ago"
```

### If using a file-based log

```bash
tail -f /var/log/gunicorn/error.log
# or
tail -f /var/log/gunicorn/access.log
```

### Nginx logs (if used as reverse proxy)

```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### System logs (general)

```bash
# System messages
sudo tail -f /var/log/syslog

# Auth attempts (SSH, etc.)
sudo tail -f /var/log/auth.log
```

---

## 3. App Location & Structure

On the EC2 instance:

| Path | Description |
|------|-------------|
| `/home/ubuntu/gooddriver/` | Project root |
| `/home/ubuntu/gooddriver/flask/` | Flask app |
| `/home/ubuntu/gooddriver/flask/.env` | Environment variables (DB, secrets, etc.) |
| `/home/ubuntu/gooddriver/venv/` or `flask/venv/` | Python virtualenv |

---

## 4. Restart the Application

After changing `.env` or deploying new code:

```bash
sudo systemctl restart gunicorn
```

Check status:

```bash
sudo systemctl status gunicorn
```

---

## 5. Useful Terminal Commands

### On EC2 (after SSH)

```bash
# Check if app is listening on port 5000
sudo ss -tlnp | grep 5000

# Check disk space
df -h

# Check memory
free -h

# Run database connection test (from project root)
cd /home/ubuntu/gooddriver
source venv/bin/activate  # or: flask/venv/bin/activate
python tests/test_db_connection.py
```

### AWS CLI (from your local machine)

```bash
# Describe EC2 instances
aws ec2 describe-instances --region us-east-1

# Describe RDS instance
aws rds describe-db-instances --region us-east-1

# List S3 buckets
aws s3 ls

# Check EC2 instance status
aws ec2 describe-instance-status --region us-east-1
```

---

## 6. RDS & Database

- **Endpoint**: Check `flask/.env` on EC2: `DB_HOST=...`
- **Region**: `us-east-1`
- **Security**: RDS is in a private subnet; only EC2 (via security group) can connect
- **Troubleshooting**: See [TROUBLESHOOTING_DB.md](TROUBLESHOOTING_DB.md)

---

## 7. S3 (Profile Pictures)

- **Region**: `us-east-1` (default)
- **Env vars**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`
- **Path**: Avatars stored under `avatars/` prefix (configurable)

---

## 8. Mobile App Configuration

The Android app points to the EC2 server:

- **Base URL**: Configured in `AuthService.kt` → `baseUrl`
- **Format**: `http://<EC2_PUBLIC_IP>:5000` or `https://...` if behind a proxy/load balancer
- If the EC2 IP changes (e.g., instance restart without Elastic IP), update the mobile app and rebuild.

---

## Quick Reference

| Task | Command |
|------|---------|
| SSH into EC2 | `ssh -i key.pem ubuntu@<EC2_IP>` |
| Live logs | `sudo journalctl -u gunicorn -f` |
| Restart app | `sudo systemctl restart gunicorn` |
| App status | `sudo systemctl status gunicorn` |
| DB test | `cd /home/ubuntu/gooddriver && source venv/bin/activate && python tests/test_db_connection.py` |
