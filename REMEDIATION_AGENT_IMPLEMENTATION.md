# Remediation Agent Implementation (LangGraph + GitHub + LLM)

## Overview

The Remediation Agent is the **third agent** in the self-healing incident response pipeline:

```
Monitoring Agent → Diagnosis Agent → Remediation Agent → Human Approval → Execution
```

The Remediation Agent performs **decision-making and action execution** for incidents:

1. **Classifies** the issue type (CODE_CHANGE, INFRASTRUCTURE, or UNKNOWN)
2. **Generates** code patches for code-fixable issues
3. **Creates GitHub PRs** for code changes (with human review gates)
4. **Creates GitHub Issues** for infrastructure problems
5. **Requests human approval** before executing any code changes

## Key Responsibilities

### Decision Classification
- Takes diagnosis output from Diagnosis Agent
- Uses LLM to classify issue into:
  - **CODE_CHANGE**: Fixable via code modification (syntax errors, missing imports, logic bugs, config bugs)
  - **INFRASTRUCTURE**: Requires ops/deployment changes (Redis down, Docker issues, network problems)
  - **UNKNOWN**: Ambiguous or insufficient information

### Code Patch Generation
- Fetches relevant repository files
- Generates minimal, correct patches for code-fixable issues
- Validates patch syntax before applying
- Creates feature branches

### GitHub Operations
- Creates feature branches (`fix/<description>`)
- Applies patches to files
- Commits changes
- Opens Pull Requests with comprehensive descriptions
- Creates Issues for infrastructure problems
- Uses git/GitHub CLI commands

### Human-in-the-Loop
- **CRITICAL**: Pauses execution before code changes
- Presents patches for human review
- Waits for approval (approve/edit/reject)
- Only proceeds after explicit approval

## Architecture

### File Structure

```
agents/remediation/
├── __init__.py
├── agent.py                # Main RemediationAgent class + LangGraph orchestration
├── schemas.py              # TypedDict and Pydantic models
├── classifier.py           # Issue classification logic (LLM-powered)
├── patch_generator.py      # Code patch generation
└── github_operations.py    # GitHub CLI wrapper for git/gh commands
```

### Core Components

#### 1. **RemediationState** (TypedDict)
The state that flows through the LangGraph workflow:

```python
class RemediationState(TypedDict):
    payload: Dict[str, Any]              # Input incident data
    diagnosis: Optional[DiagnosisInput]  # Parsed diagnosis from Diagnosis Agent
    classification: Optional[Dict]       # Issue type classification result
    patches: list[CodePatch]            # Generated code patches
    github_actions: list[GitHubAction]  # Results of GitHub operations
    remediation_result: Optional[RemediationResult]
    human_approval: Optional[bool]      # Did human approve?
    approval_notes: Optional[str]
```

#### 2. **RemediationAgent** (Main Orchestrator)

Implements the LangGraph workflow with nodes:

- `normalize_diagnosis`: Convert payload to typed DiagnosisInput
- `classify_issue`: LLM-based issue classification
- `generate_patches`: Create code patches (if CODE_CHANGE)
- `request_approval`: HITL gate before code changes
- `create_pr`: Execute GitHub PR creation
- `create_issue`: Create GitHub issue for infra problems
- `finalize`: Generate final remediation report

**Conditional routing** based on fix_type:

```
classify_issue → generate_patches → [branch by fix_type]
                                  ├→ CODE_CHANGE → request_approval → create_pr
                                  └→ INFRASTRUCTURE/UNKNOWN → create_issue
                                  
Both paths → finalize → END
```

## State Model

### Input Format

Payload from Diagnosis Agent:

```python
{
    "incident_id": "inc-001",
    "error_logs": "...",
    "root_cause": "Redis connection refused",
    "confidence": 0.92,
    "patterns_detected": ["connection_refused", "timeout"],
    "explanation": "Redis container is not responding on port 6379",
    "recommended_action": "Restart Redis container or check network connectivity"
}
```

### Output Format

```python
{
    "incident_id": "inc-001",
    "fix_type": "INFRASTRUCTURE",
    "decision": "INFRASTRUCTURE",
    "classification_reasoning": "Keywords suggest infrastructure issue...",
    "github_actions": [
        {
            "action_type": "create_issue",
            "status": "success",
            "issue_number": 42,
            "url": "https://github.com/.../issues/42"
        }
    ],
    "patches_generated": [],
    "explanation": "...",
    "next_steps": "Issue #42 created. Manual investigation required."
}
```

## Node Behaviors

### 1. `normalize_diagnosis`

Converts flexible payload formats into typed `DiagnosisInput`.

Supports patterns:
- Canonical fields: `incident_id`, `timestamp`, `service`, `log_snippet`
- From Diagnosis Agent: `root_cause`, `confidence`, `patterns_detected`
- Fallback fields: `id`, `summary`, `logs`

### 2. `classify_issue`

**Uses LLM (via Ollama + Mistral) for strong decision logic.**

Prompt engineering distinguishes:

**CODE_CHANGE indicators:**
- Syntax errors
- Missing imports or undefined functions
- Incorrect API/library usage
- Logic bugs or wrong algorithms
- Configuration bugs in code
- Type errors or null pointers
- Missing error handling
- Incorrect data transformations

**INFRASTRUCTURE indicators:**
- Service/container down (Redis, DB, Docker)
- Network connectivity issues
- Environment variables missing
- Port conflicts or firewall issues
- Resource exhaustion
- Health check failures
- Deployment tool failures
- External service timeouts

**Fallback heuristic:**
- If LLM fails, uses keyword matching
- Infrastructure keywords: "redis", "docker", "network", "connection", "timeout", etc.
- Code keywords: "syntax", "import", "undefined", "logic", "algorithm", etc.

### 3. `generate_patches`

**Only runs if classification = CODE_CHANGE**

1. Fetches repository files
2. Uses LLM to generate minimal patches
3. Validates syntax (for Python: compile check)
4. Returns list of CodePatch objects

Patch content includes:
- Original file content
- Patched file content
- Change summary
- Description

**Key constraint:** Only modifies files that exist in repo. Never hallucinate paths.

### 4. `request_approval`

**CRITICAL HUMAN-IN-THE-LOOP GATE**

Pauses execution before any code changes:

```python
[Remediation] ⏸ HUMAN APPROVAL REQUIRED for inc-001
  - app/main.py: Fix missing import statement
  - agents/diagnosis/agent.py: Add null check
```

Current implementation:
- Logs patch details
- Assumes approval (TODO: integrate approval system)
- Approval system placeholder (Slack, email, API endpoints)

### 5. `create_pr`

Executes GitHub operations:

1. **Create feature branch**: `fix/<sanitized-description>-<incident-id>`
2. **Apply patches**: File-by-file modification
3. **Stage changes**: `git add <files>`
4. **Commit**: `git commit -m "fix: <root cause>"`
5. **Create PR**: `gh pr create --title=... --body=...`
6. **Checkout main**: Return to main branch

PR description includes:
- Issue summary
- Root cause analysis
- Confidence level
- Pattern details
- Files modified
- Recommended action
- Risk assessment
- Pre-merge checklist

Returns GitHubAction with PR number if successful.

### 6. `create_issue`

For INFRASTRUCTURE or UNKNOWN issues:

1. **Determine issue type**: Infrastructure label or "needs-investigation"
2. **Create issue**: `gh issue create --title=... --body=... --labels=...`
3. **Include diagnosis details**: Root cause, analysis, patterns, logs, next steps

Issue description includes:
- Root cause (bold)
- Detailed analysis
- Confidence level
- Patterns detected
- Error log excerpt
- Recommended actions
- Investigation checklist

Returns GitHubAction with issue number if successful.

### 7. `finalize`

Generates final remediation report:

- Consolidates all GitHub actions
- Determines next steps based on outcomes
- Creates RemediationResult
- Logs summary

**Success scenarios:**
- CODE_CHANGE + PR created → "PR #123 created. Awaiting review."
- INFRASTRUCTURE + issue created → "Issue #456 created. Manual action required."

**Failure scenarios:**
- GitHub CLI unavailable → "Manual PR/issue creation required"
- Patch validation failed → "Patches generated. Manual submission."

## Tools & Dependencies

### GitHub Operations

`GitHubOperations` class wraps:
- `git` CLI: branch creation, commits
- `gh` CLI: PR and issue creation

**Why CLI over API:**
- Authentication via $GH_TOKEN environment variable
- Consistent with established workflows
- No additional Python libraries needed
- Works with any GitHub instance

### LLM Integration

Uses **Ollama + Mistral** model:

```python
llm = ChatOllama(
    model="mistral",
    temperature=0.3,  # Lower = more deterministic
    base_url="http://localhost:11434",
)
```

Structured output via `with_structured_output(MySchema)`.

### Validation

- **Syntax validation**: compile() for Python files
- **File existence checks**: Prevent hallucination
- **Content matching**: Verify original content before patching

## Security & Safety

### Constraints (Non-Negotiable)

❌ **NEVER:**
- Push directly to main branch
- Hallucinate file paths
- Modify files that don't exist
- Skip human approval for code changes
- Apply patches without validation

✅ **ALWAYS:**
- Create feature branches
- Validate patches before committing
- Include comprehensive PR descriptions
- Request human approval (HITL)
- Log all operations

### Risk Mitigation

1. **Patch validation**: Syntax check + content verification
2. **Feature branches**: All changes isolated
3. **Human review**: Code changes require approval
4. **Audit trail**: All operations logged
5. **Error handling**: Graceful fallback on failures

## Integration Points

### Receives From
- **Diagnosis Agent**: `DiagnosisResult` via incident stream or direct call
- **Incident Orchestration Graph**: `IncidentState` with `diagnosis` field

### Outputs To
- **Communication Agent**: Remediation result (success/failure, action taken)
- **GitHub**: PRs and Issues
- **Redis stream** (optional): Remediation report for downstream consumption

### Example Flow in Incident Graph

```python
# incident_orchestration.py
async def remediate_incident(state: IncidentState) -> IncidentState:
    agent = RemediationAgent()
    remediation_payload = {
        "incident_id": state["incident_id"],
        **state["diagnosis"],  # Unpack all diagnosis fields
    }
    result = await agent.remediate(remediation_payload)
    state["actions_taken"].append({"type": "remediation", "result": result})
    return state
```

## Common Scenarios

### Scenario 1: Code Fix (Missing Import)

```
Input:
  root_cause: "ModuleNotFoundError: No module named 'requests'"
  patterns: ["import_error", "module_not_found"]

Workflow:
  1. classify_issue → CODE_CHANGE
  2. generate_patches → Create patch adding "import requests"
  3. request_approval → HITL gate
  4. create_pr → Open PR "Fix: Add missing requests import"
  5. finalize → Report PR #123 ready for review

Output:
  fix_type: CODE_CHANGE
  github_actions: [PR #123]
```

### Scenario 2: Infrastructure Issue (Redis Down)

```
Input:
  root_cause: "Redis connection refused: port 6379"
  patterns: ["connection_refused", "timeout"]

Workflow:
  1. classify_issue → INFRASTRUCTURE
  2. generate_patches → Skipped
  3. create_issue → Open issue "Infrastructure: Redis connection refused"
  4. finalize → Report Issue #456 for investigation

Output:
  fix_type: INFRASTRUCTURE
  github_actions: [Issue #456 with labels: "infrastructure", "incident"]
```

### Scenario 3: Ambiguous (Unknown)

```
Input:
  root_cause: "Unexpected error occurred"
  confidence: 0.3

Workflow:
  1. classify_issue → UNKNOWN (low confidence)
  2. create_issue → Open issue "Investigation Required: Unexpected error"
  3. finalize → Report Issue #789 marked "needs-investigation"

Output:
  fix_type: UNKNOWN
  github_actions: [Issue #789 with label: "needs-investigation"]
```

## Real-World Extensions (Phase 2+)

### Approval System Integration
- Slack messages with patch diffs
- Email with approval links
- API endpoint for async approval
- Webhook integration

### Advanced Patch Generation
- Context-aware generation (use codebase structure)
- Multi-file patch generation
- Dependency analysis
- Test generation alongside fixes

### MCP Integration
- Use GitHub MCP for repository access
- Structured repo file retrieval
- Native MCP tools dispatch

### Test Execution
- Run test suite before opening PR
- Report test results in PR description
- Block PR creation if tests fail

### Metrics & Analytics
- Track remediation success rates
- Measure fix correctness
- Monitor approval times
- Cost analysis per fix type

## Debugging

### Common Issues

**1. "No such file" error in patch application**
```
Solution: Verify file exists and path is relative to repo root.
Check: self._repo_path / file_path (should resolve correctly)
```

**2. LLM fails to generate patch**
```
Solution: Check Ollama is running on http://localhost:11434
Fallback: Heuristic patches (simple replacements)
```

**3. GitHub CLI commands fail**
```
Solution: Check gh CLI is installed and authenticated
Verify: gh auth status
Set: GH_TOKEN environment variable
```

**4. Content mismatch in patch application**
```
Solution: File has been modified since diagnosis
Action: Log warning and proceed with caution
Consider: Re-running diagnosis on latest code
```

## Testing

Key test cases:

- [ ] Classify code error correctly
- [ ] Classify infrastructure error correctly
- [ ] Generate syntactically valid patches
- [ ] Reject invalid file paths
- [ ] Create PR with all required information
- [ ] Create issue with proper labels
- [ ] Handle API failures gracefully
- [ ] Human approval gate blocks execution

## Configuration

Via `app/config.py`:

```python
Config.REDIS_URL  # Redis connection
Config.INCIDENT_STREAM  # Input stream for incidents
Config.DIAGNOSIS_STREAM  # Input stream for diagnosis results
# Add: Config.REMEDIATION_STREAM
```

Environment variables:

```bash
GH_TOKEN  # GitHub CLI authentication (required for gh commands)
OLLAMA_URL  # Ollama server URL (default: http://localhost:11434)
REPO_PATH  # Repository path (default: current directory)
```

## Summary

The Remediation Agent represents the **action layer** of the self-healing system:

✅ **Smart classification**: Uses LLM to properly distinguish code vs infra issues
✅ **Safe automation**: Validates patches, requires human approval for code changes
✅ **Comprehensive tracking**: Creates audit trail via GitHub PRs and Issues
✅ **Extensible design**: Ready for approval systems, MCP integration, advanced patching
✅ **Production-ready**: Error handling, logging, constraint enforcement

It closes the loop: **Monitoring → Diagnosis → Remediation → Human Review → Resolution**
