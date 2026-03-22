# Remediation Agent - Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### 1. Install Dependencies

```bash
# Already in requirements.txt, but verify:
pip install langgraph langchain langchain-ollama redis pydantic
```

### 2. Ensure Prerequisites

```bash
# GitHub CLI must be installed and authenticated
gh auth status

# Set your GitHub token
export GH_TOKEN=$(gh auth token)

# Ollama must be running (for LLM classification)
# Start with: ollama serve
# In another terminal: ollama pull mistral
```

### 3. Initialize Agent in Your Code

```python
from agents.remediation import RemediationAgent

# Create agent (will use repo root by default)
agent = RemediationAgent(
    repo_path="/path/to/your/repo",
    # redis_url and remediation_stream are optional
)
```

### 4. Call the Remediation API

```python
# Prepare incident data (from Diagnosis Agent)
incident = {
    "incident_id": "incident-123",
    "error_logs": "...",
    "root_cause": "Missing dependency",
    "confidence": 0.92,
    "patterns_detected": ["import_error"],
    "explanation": "Application tries to import 'requests' but it's not in requirements",
    "recommended_action": "Add requests to requirements.txt"
}

# Run remediation
result = await agent.remediate(incident)

# Check result
print(f"Fix Type: {result['fix_type']}")
print(f"Status: {result['next_steps']}")
if result['github_actions']:
    for action in result['github_actions']:
        if action['action_type'] == 'create_pr':
            print(f"PR Created: #{action['pr_number']}")
```

---

## 📋 Workflow Decision Tree

```
┌─ Incident Data
│  (error_logs, root_cause, confidence, patterns)
│
├─ Classify Issue
│  ├─ CODE_CHANGE? → Generate Patch → Request Approval → Create PR
│  ├─ INFRASTRUCTURE? → Escalate → Create Issue
│  └─ UNKNOWN? → Escalate → Create Issue
│
└─ Return Result
   (fix_type, github_actions, patches_generated, next_steps)
```

---

## 🏃 Real-World Example: Missing Import

### Input
```json
{
  "incident_id": "inc-42",
  "error_logs": "ModuleNotFoundError: No module named 'requests'",
  "root_cause": "Missing import in main.py",
  "confidence": 0.95,
  "patterns_detected": ["import_error", "module_not_found"],
  "explanation": "main.py uses requests.get() without importing requests",
  "recommended_action": "Add 'import requests' at top of main.py"
}
```

### Workflow
1. ✅ **Classify** → CODE_CHANGE (contains word "import")
2. ✅ **Generate Patch** → LLM adds `import requests` to main.py
3. ✅ **Request Approval** → Logs patch details (awaiting human review)
4. ✅ **Create PR** → Opens PR #123 "Fix: Add missing requests import"
5. ✅ **Finalize** → Reports success

### Output
```json
{
  "fix_type": "CODE_CHANGE",
  "decision": "CODE_CHANGE",
  "github_actions": [
    {
      "action_type": "create_pr",
      "status": "success",
      "pr_number": 123
    }
  ],
  "next_steps": "PR #123 created. Awaiting code review and merge."
}
```

---

## 🏃 Real-World Example: Redis Connection Failure

### Input
```json
{
  "incident_id": "inc-43",
  "error_logs": "ConnectionRefusedError: Connection refused: Redis port 6379",
  "root_cause": "Redis container not responding",
  "confidence": 0.92,
  "patterns_detected": ["connection_refused", "timeout"],
  "explanation": "Redis container crashed or is not listening on port 6379",
  "recommended_action": "Restart Redis container or check Docker network"
}
```

### Workflow
1. ✅ **Classify** → INFRASTRUCTURE (contains "redis", "connection")
2. ⏭️ **Skip Patch Generation** → Not a code issue
3. ✅ **Create Issue** → Opens Issue #456 with infrastructure label
4. ✅ **Finalize** → Reports escalation

### Output
```json
{
  "fix_type": "INFRASTRUCTURE",
  "decision": "INFRASTRUCTURE",
  "github_actions": [
    {
      "action_type": "create_issue",
      "status": "success",
      "issue_number": 456
    }
  ],
  "next_steps": "Issue #456 created. Manual investigation and action required."
}
```

---

## 🔧 Configuration via Environment

```bash
# GitHub authentication (required for gh commands)
export GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Optional: Ollama URL (defaults to http://localhost:11434)
export OLLAMA_URL=http://localhost:11434

# Optional: Repository path (defaults to current directory)
export REPO_PATH=/home/user/my-app
```

---

## 📝 Integration with Incident Orchestration

In your `incident_orchestration.py`:

```python
async def remediate_incident(state: IncidentState) -> IncidentState:
    """Node: execute remediation."""
    from agents.remediation import RemediationAgent
    
    agent = RemediationAgent()
    
    # Pass diagnosis output to remediation
    remediation_payload = {
        "incident_id": state["incident_id"],
        **state["diagnosis"],  # Unpack all diagnosis fields
    }
    
    result = await agent.remediate(remediation_payload)
    
    # Track result
    state["actions_taken"].append({
        "type": "remediation",
        "result": result
    })
    
    return state
```

---

## ⚠️ Approval System (HITTING THE GATE)

Currently, the system **assumes approval** after logging:

```
[Remediation] ⏸ HUMAN APPROVAL REQUIRED for inc-001
  - app/main.py: Add missing import requests
```

To integrate with a real approval system:

### Option 1: Slack Approval

```python
# In _request_approval_node:
slack_client.send_message(
    channel="#incident-approvals",
    text=f"Approve patch for {diagnosis.incident_id}?",
    blocks=[
        {"type": "button", "text": "✅ Approve", "action_id": f"approve_{id}"},
        {"type": "button", "text": "❌ Reject", "action_id": f"reject_{id}"}
    ]
)
# Wait for webhook callback
```

### Option 2: Email Approval

```python
# Send email with approval link
send_email(
    to="team@company.com",
    subject=f"Approval Required: {diagnosis.root_cause}",
    body=f"<a href='http://approval-api/approve/{id}'>Approve</a>"
)
```

### Option 3: API Endpoint

```python
# Expose approval endpoint
@app.post("/remediation/{incident_id}/approve")
async def approve_remediation(incident_id: str):
    # Trigger patch application and PR creation
    state["human_approval"] = True
    # Resume workflow...
```

---

## 🛠️ Troubleshooting

### Issue: `gh command not found`

**Solution:**
```bash
# Install GitHub CLI
brew install gh  # macOS
sudo apt install gh  # Linux
# or download from https://github.com/cli/cli/releases
```

### Issue: `gh auth failed`

**Solution:**
```bash
# Authenticate with GitHub
gh auth login
# or set token
export GH_TOKEN=ghp_xxxxx
```

### Issue: Ollama connection refused

**Solution:**
```bash
# Start Ollama
ollama serve

# In another terminal, pull Mistral
ollama pull mistral

# Verify it's running
curl http://localhost:11434/api/tags
```

### Issue: `File does not exist: app/main.py`

**Solution:**
- Verify repo_path is correct
- Check that file exists: `ls {repo_path}/app/main.py`
- Ensure paths are relative to repo root

---

## 📊 Monitoring & Logging

All operations are logged with `[Remediation]` prefix:

```
[Remediation] Normalizing diagnosis payload
[Remediation] Diagnosis: Missing import (confidence: 0.95)
[Remediation] Classifying issue for inc-123
[Remediation] Classification: CODE_CHANGE (confidence: 0.92)
[Remediation] Generating patches for inc-123
[Remediation] Validation: All patches validated
[Remediation] ✓ Generated 1 patches
[Remediation] ⏸ HUMAN APPROVAL REQUIRED for inc-123
  - app/main.py: Add missing import requests
[Remediation] ✓ Assuming approval (TODO: integrate approval system)
[Remediation] Creating PR for inc-123
[Remediation] ✓ Created branch: fix/add-missing-import-inc-12345
[Remediation] ✓ Patched file: app/main.py
[Remediation] ✓ Staged changes
[Remediation] ✓ Committed with message: fix: Missing import in main.py
[Remediation] ✓ Created PR: https://github.com/owner/repo/pull/123
[Remediation] PR creation: success
[Remediation] ✓ Completed for inc-123: CODE_CHANGE
```

---

## 🧪 Testing

Quick test to verify everything works:

```python
import asyncio
from agents.remediation import RemediationAgent

async def test():
    agent = RemediationAgent(repo_path=".")
    
    # Test infrastructure classification
    result = await agent.remediate({
        "incident_id": "test-001",
        "error_logs": "ConnectionRefusedError",
        "root_cause": "Redis connection failed",
        "confidence": 0.9,
        "patterns_detected": ["connection_refused"],
        "explanation": "Redis not responding",
        "recommended_action": "Check Redis"
    })
    
    print("✓ Test passed")
    print(f"Fix type: {result['fix_type']}")
    assert result['fix_type'] == "INFRASTRUCTURE"

asyncio.run(test())
```

---

## 📚 Learn More

- Full architecture: [REMEDIATION_AGENT_IMPLEMENTATION.md](../REMEDIATION_AGENT_IMPLEMENTATION.md)
- Build summary: [REMEDIATION_BUILD_SUMMARY.md](../REMEDIATION_BUILD_SUMMARY.md)
- Code: [agents/remediation/agent.py](../agents/remediation/agent.py)

---

## 🎯 Next Steps

1. ✅ Verify Ollama + GitHub CLI are working
2. ✅ Set GH_TOKEN environment variable
3. ✅ Test with a real incident payload
4. ✅ Integrate with incident orchestration graph
5. ⬜ Implement approval system (Slack/Email/API)
6. ⬜ Add metrics tracking
7. ⬜ Extend patch generation strategies

---

**You're ready to remediate! 🚀**
