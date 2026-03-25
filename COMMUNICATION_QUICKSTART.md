# Communication Agent - Quick Start

## Setup

### 1. Configure Email Environment Variables

Add these to your `.env.local` or `.env` file:

```env
# Email Configuration
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT="587"
SENDER_EMAIL="your-notification-email@gmail.com"
SENDER_PASSWORD="your-app-specific-password"
DEVELOPER_EMAIL="dev@company.com"
```

### 2. Provider-Specific Setup

#### Gmail
1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and "Windows Computer" (or your device)
3. Copy the 16-character app password
4. Use this as `SENDER_PASSWORD`

#### Microsoft/Office 365
1. Use `smtp.office365.com` as SMTP_SERVER
2. Use your Office 365 email password as SENDER_PASSWORD

#### Other Providers
Check your email provider's SMTP settings documentation

### 3. How It Works

When an incident occurs:
1. **Monitoring Agent** detects the error and creates an incident
2. **Diagnosis Agent** analyzes logs and root cause
3. **Remediation Agent** creates PRs or GitHub issues
4. **Communication Agent** sends an email report

```
Error Detected
    ↓
Incident Created
    ↓
Root Cause Analysis
    ↓
Remediation (PR/Issue)
    ↓
Email Report Sent ← You receive this
```

## Email Content

The email includes:

**📋 Incident Details**
- Incident ID and timestamp
- Error message and location

**🔍 Diagnosis**
- Root cause analysis
- Confidence level (visual bar)
- Detected patterns
- Recommended action

**🔧 Remediation**
- Type of fix (Code/Infrastructure)
- Actions taken
- GitHub PR/Issue links

## Customization

### Change Email Template

Edit `agents/communication/email_templates.py`:
- `format_incident_report_html()` - HTML version
- `format_incident_report_plain_text()` - Text version

### Add New Recipients

Pass `developer_email` in incident data:
```python
await agent.notify({
    "incident_id": "INC-001",
    # ... other fields ...
    "developer_email": "another-dev@company.com"
})
```

### Custom Email Subject

The subject is auto-generated from root cause:
```
[Incident Report] {root_cause} - {incident_id}
```

## Testing

### Test Email Configuration

```python
from agents.communication import EmailService, CommunicationAgent

# Test email service
email_service = EmailService()
result = await email_service.send_email(
    recipient_email="dev@company.com",
    subject="Test Email",
    html_body="<p>This is a test</p>",
    plain_text_body="This is a test"
)
print(result)
```

### Test Full Communication

```python
from agents.communication import CommunicationAgent

agent = CommunicationAgent()

test_incident = {
    "incident_id": "TEST-001",
    "created_at": "2025-03-25T10:30:00Z",
    "error_message": "Database connection timeout",
    "error_location": "db.py:connect()",
    "diagnosis": {
        "root_cause": "Connection pool exhaustion",
        "confidence": 0.92,
        "patterns_detected": ["timeout_increase", "pool_limit_hit"],
        "explanation": "Database connection pool reached max limit",
        "recommended_action": "Increase pool size or analyze query performance"
    },
    "remediation": {
        "fix_type": "INFRASTRUCTURE",
        "decision": "Create GitHub issue for DevOps",
        "github_actions": [{
            "action_type": "create_issue",
            "status": "success",
            "issue_number": 1234,
            "url": "https://github.com/your-repo/issues/1234"
        }]
    }
}

result = await agent.notify(test_incident)
print(result)
```

## Troubleshooting

### Email Not Sending

Check the logs:
```bash
tail -f logs/agent.log
```

Look for messages like:
- `"Email service not configured"` → Check env variables
- `"SMTP authentication failed"` → Check password/API key
- `"Failed to send email"` → Check SMTP server settings

### Gmail Authentication Error

- Ensure 2-factor authentication is enabled
- Use **app-specific password**, not your regular password
- Verify `SENDER_EMAIL` matches your Gmail account

### Office 365 Not Working

- Verify SMTP_SERVER is `smtp.office365.com`
- Check your password is correct (not app-specific here)
- Ensure "Less secure app access" is allowed if using work account

## What Happens When Email Config Missing

If email is not configured:
- Communication agent logs a warning
- Incident processing continues normally
- No email is sent (graceful degradation)

Status returned: `"skipped"` with reason `"Email service not configured"`

## Environment Variables Reference

| Variable | Required | Default | Example |
|----------|----------|---------|---------|
| SMTP_SERVER | Yes | "" | smtp.gmail.com |
| SMTP_PORT | No | 587 | 587 |
| SENDER_EMAIL | Yes | "" | notify@company.com |
| SENDER_PASSWORD | Yes | "" | 16-char app password |
| DEVELOPER_EMAIL | Yes | "" | dev@company.com |

## Integration Points

### Incident Orchestration Graph
File: `agents/graphs/incident_orchestration.py`

The `communicate_incident()` node:
- Runs automatically after remediation
- Collects all incident data
- Sends email via CommunicationAgent
- Logs result to `actions_taken`

### Manual Usage

```python
from agents.communication import CommunicationAgent

agent = CommunicationAgent()
result = await agent.notify(incident_data)
```

## Performance

- Email sending is **asynchronous** - doesn't block incident processing
- Runs in thread pool for non-blocking I/O
- Timeout: 10 seconds per email
- Suitable for high-frequency incident reporting

## Security

⚠️ **Important:**
- Never commit `.env` with real credentials
- Use `.env.local` for local development
- Use app-specific passwords, not account passwords
- Store sensitive data in secure environment variable management (Kubernetes secrets, etc.)

## Next Steps

1. ✅ Set environment variables
2. ✅ Test email configuration
3. ✅ Verify orchestration graph flow
4. ✅ Monitor logs during incident detection
5. ✅ Adjust email template if needed
