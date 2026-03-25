# Communication Agent Implementation

## Overview

The Communication Agent is responsible for sending professional email reports about incidents to developers. It captures:
- **Error Details**: When and where the error occurred
- **Diagnosis Results**: Root cause analysis from the Diagnosis Agent
- **Remediation Actions**: Actions performed by the Remediation Agent (PR creation, GitHub issues, etc.)

## Components

### 1. **CommunicationAgent** (`agents/communication/agent.py`)
Main entry point for sending notifications.

**Key Method:**
```python
async def notify(self, incident_data: dict[str, Any]) -> dict[str, Any]
```

**Input Format:**
```python
{
    "incident_id": str,              # Unique incident identifier
    "created_at": str,               # ISO8601 timestamp
    "error_message": str,            # Error message from logs
    "error_location": str,           # File/function where error occurred
    "diagnosis": {
        "root_cause": str,
        "confidence": float,         # 0.0 to 1.0
        "patterns_detected": [str],
        "explanation": str,
        "recommended_action": str
    },
    "remediation": {
        "fix_type": str,             # "CODE_CHANGE", "INFRASTRUCTURE", "UNKNOWN"
        "decision": str,
        "github_actions": [
            {
                "action_type": str,  # "create_pr", "create_issue"
                "status": str,       # "success", "failed"
                "url": str,
                "pr_number": int,
                "issue_number": int
            }
        ]
    },
    "developer_email": str           # Optional; defaults to Config.DEVELOPER_EMAIL
}
```

**Output Format:**
```python
{
    "status": str,              # "success", "failed", "skipped"
    "incident_id": str,
    "recipient": str,           # Email address
    "subject": str,
    "error": str                # If status is "failed"
}
```

### 2. **EmailService** (`agents/communication/email_service.py`)
Handles SMTP email transmission asynchronously.

**Key Method:**
```python
async def send_email(
    self,
    recipient_email: str,
    subject: str,
    html_body: str,
    plain_text_body: Optional[str] = None
) -> dict[str, Any]
```

**Features:**
- Runs SMTP operations in thread pool (non-blocking)
- Supports TLS encryption
- Falls back gracefully if email not configured
- Comprehensive error logging

### 3. **Email Templates** (`agents/communication/email_templates.py`)

#### `format_incident_report_html()`
Generates professional HTML email with:
- Colored status badges (success/pending)
- Incident details section
- Diagnosis results with confidence bar
- Detected patterns
- Remediation actions with GitHub links
- Professional styling

#### `format_incident_report_plain_text()`
Plain text version for email clients without HTML support.

## Configuration

### Environment Variables (in `.env.local` or `.env`)

```env
# SMTP Configuration
SMTP_SERVER="smtp.gmail.com"              # Email provider SMTP server
SMTP_PORT="587"                           # Port (587 for TLS, 465 for SSL)
SENDER_EMAIL="notifications@company.com"  # Notification sender email
SENDER_PASSWORD="your-app-password"       # App-specific password (not plain password)
DEVELOPER_EMAIL="dev@company.com"         # Developer email for incident reports
```

### Configuration in Code
All settings are in `app/config.py`:
```python
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
DEVELOPER_EMAIL = os.getenv("DEVELOPER_EMAIL", "")
```

## Integration with Orchestration Graph

The `communicate_incident()` node in `incident_orchestration.py`:

1. Collects incident data from graph state
2. Extracts diagnosis from the diagnose_incident node
3. Extracts remediation from the remediate_incident node  
4. Calls `CommunicationAgent.notify()`
5. Logs notification result to actions_taken

**Graph Flow:**
```
detect_incident 
    ↓
diagnose_incident 
    ↓
remediate_incident 
    ↓
communicate_incident ← Email sent here
    ↓
END
```

## Email Examples

### Success Case (Code Fix Applied)
**Subject:** `[Incident Report] Memory Leak in Cache Module - INC-20250325-001`

**Content:**
- Status: SUCCESS (green badge)
- Root Cause: Unbounded cache growth without eviction policy
- Confidence: 95%
- Patterns: memory_increase_spike, cache_hit_rate_drop
- Remediation: PR #2847 created with cache TTL implementation
- GitHub Actions: ✅ create_pr (success)

### Pending Case (Infrastructure Issue)
**Subject:** `[Incident Report] Database Connection Pool Exhaustion - INC-20250325-002`

**Content:**
- Status: PENDING (yellow badge)
- Root Cause: Database connection pool misconfiguration
- Confidence: 87%
- Patterns: connection_timeout, pool_exhaustion
- Remediation: Issue #1234 created for DevOps investigation
- GitHub Actions: ✅ create_issue (success)

## Email Provider Setup

### Gmail
1. Enable 2-factor authentication
2. Generate app-specific password: https://myaccount.google.com/apppasswords
3. Use generated password as `SENDER_PASSWORD`

### Office 365
1. Use `smtp.office365.com` as SMTP_SERVER
2. Use your Office 365 password as SENDER_PASSWORD

### Custom SMTP Server
Configure your server details accordingly.

## Features

✅ HTML & Plain Text Email Support  
✅ Asynchronous Email Sending  
✅ Professional Email Templates  
✅ Confidence Visualization  
✅ GitHub Action Links  
✅ Graceful Fallback if Email Not Configured  
✅ Comprehensive Error Logging  
✅ SMTP Authentication Error Handling  

## Error Handling

- **No Email Config**: Logs warning, returns "skipped" status
- **SMTP Auth Failed**: Logs error, returns "failed" status with error message
- **SMTP Exception**: Caught and logged with detailed error info
- **Network Issues**: Timeout set to 10 seconds, error is logged

## Logging

All operations are logged to `LOG_FILE` (default: `logs/agent.log`):
```
INFO: Preparing incident report for INC-20250325-001
INFO: Sending incident report to dev@company.com
INFO: Email sent successfully to dev@company.com with subject: [Incident Report] ...
```

## Testing

To test email functionality:

```python
from agents.communication import CommunicationAgent

agent = CommunicationAgent()
result = await agent.notify({
    "incident_id": "TEST-001",
    "created_at": "2025-03-25T10:30:00Z",
    "error_message": "Test error for email",
    "error_location": "test_function()",
    "diagnosis": {
        "root_cause": "Test cause",
        "confidence": 0.85,
        "patterns_detected": ["test_pattern"],
        "explanation": "This is a test",
        "recommended_action": "Check logs"
    },
    "remediation": {
        "fix_type": "CODE_CHANGE",
        "decision": "Create PR",
        "github_actions": [{
            "action_type": "create_pr",
            "status": "success",
            "pr_number": 123
        }]
    },
    "developer_email": "dev@company.com"
})
print(result)
```

## Future Enhancements

- [ ] Multiple recipient support (cc/bcc)
- [ ] Email templates with custom branding
- [ ] Slack integration alongside email
- [ ] Webhook support for external notification systems
- [ ] Email scheduling/batch notifications
- [ ] Rich text formatting for remediation code patches
