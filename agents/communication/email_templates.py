"""Email body templates for incident reports."""

from datetime import datetime
from typing import Any, Optional


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def format_incident_report_html(
    incident_id: str,
    timestamp: str,
    error_message: str,
    error_location: str,
    diagnosis: dict[str, Any],
    remediation: dict[str, Any],
) -> str:
    """
    Format incident report as HTML email body.
    
    Args:
        incident_id: Unique incident identifier
        timestamp: When the incident occurred
        error_message: Error message from logs
        error_location: Where the error occurred (file, function, etc.)
        diagnosis: Diagnosis results
        remediation: Remediation results
        
    Returns:
        HTML formatted email body
    """
    
    # Extract key diagnosis and remediation details
    root_cause = escape_html(diagnosis.get("root_cause", "Unknown"))
    confidence = diagnosis.get("confidence", 0)
    patterns = diagnosis.get("patterns_detected", [])
    explanation = escape_html(diagnosis.get("explanation", ""))
    recommended_action = escape_html(diagnosis.get("recommended_action", ""))
    
    fix_type = remediation.get("fix_type", "UNKNOWN")
    decision = escape_html(remediation.get("decision", ""))
    github_actions = remediation.get("github_actions", [])
    
    # Build patterns list
    patterns_html = ""
    if patterns:
        patterns_html = "<ul>"
        for pattern in patterns:
            patterns_html += f"<li>{escape_html(pattern)}</li>"
        patterns_html += "</ul>"
    else:
        patterns_html = "<p><em>No specific patterns detected</em></p>"
    
    # Build GitHub actions list
    actions_html = ""
    if github_actions:
        actions_html = "<ul>"
        for action in github_actions:
            action_type = action.get("action_type", "unknown")
            status = action.get("status", "unknown")
            url = action.get("url", "")
            
            status_color = "green" if status == "success" else "red"
            status_badge = f'<span style="color: {status_color}; font-weight: bold;">{status.upper()}</span>'
            
            action_label = action_type.replace("_", " ").title()
            
            if url:
                actions_html += f'<li>{action_label}: {status_badge} - <a href="{escape_html(url)}">{escape_html(url)}</a></li>'
            else:
                actions_html += f'<li>{action_label}: {status_badge}</li>'
        actions_html += "</ul>"
    else:
        actions_html = "<p><em>No GitHub actions performed</em></p>"
    
    # Determine severity/status color based on resolution
    resolution_status = "success" if any(
        a.get("status") == "success" for a in github_actions
    ) else "pending"
    status_color = "#28a745" if resolution_status == "success" else "#fd7e14"
    
    html_body = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f6f8;
            }}
            .email-content {{
                background-color: white;
                border-radius: 8px;
                padding: 30px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .header {{
                border-bottom: 3px solid {status_color};
                padding-bottom: 20px;
                margin-bottom: 20px;
            }}
            h1 {{
                margin: 0 0 10px 0;
                color: #222;
                font-size: 24px;
            }}
            .status-badge {{
                display: inline-block;
                background-color: {status_color};
                color: white;
                padding: 5px 15px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
                text-transform: uppercase;
            }}
            .section {{
                margin-bottom: 25px;
            }}
            .section-title {{
                font-size: 16px;
                font-weight: bold;
                color: #222;
                margin-bottom: 12px;
                border-left: 4px solid #007bff;
                padding-left: 12px;
            }}
            .info-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin-bottom: 15px;
            }}
            .info-item {{
                padding: 10px;
                background-color: #f8f9fa;
                border-radius: 4px;
            }}
            .info-label {{
                font-weight: bold;
                color: #666;
                font-size: 12px;
                text-transform: uppercase;
            }}
            .info-value {{
                font-size: 14px;
                color: #333;
                margin-top: 5px;
                word-break: break-word;
            }}
            .confidence-bar {{
                display: inline-block;
                width: 100%;
                height: 20px;
                background-color: #e0e0e0;
                border-radius: 4px;
                overflow: hidden;
                margin-top: 5px;
            }}
            .confidence-fill {{
                height: 100%;
                background-color: #28a745;
                width: {confidence * 100}%;
                transition: width 0.3s ease;
            }}
            ul {{
                list-style-type: none;
                padding: 0;
            }}
            ul li {{
                padding: 8px 0;
                border-bottom: 1px solid #eee;
            }}
            ul li:last-child {{
                border-bottom: none;
            }}
            .code-block {{
                background-color: #f4f4f4;
                border-left: 3px solid #007bff;
                padding: 12px;
                margin: 10px 0;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                overflow-x: auto;
            }}
            .footer {{
                border-top: 1px solid #eee;
                padding-top: 20px;
                margin-top: 25px;
                font-size: 12px;
                color: #666;
            }}
            a {{
                color: #007bff;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="email-content">
                <div class="header">
                    <h1>Incident Report</h1>
                    <div class="status-badge">{resolution_status}</div>
                </div>
                
                <div class="section">
                    <div class="section-title">📋 Incident Details</div>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Incident ID</div>
                            <div class="info-value">{escape_html(incident_id)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Timestamp</div>
                            <div class="info-value">{escape_html(timestamp)}</div>
                        </div>
                    </div>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Error Message</div>
                            <div class="info-value"><code>{escape_html(error_message)}</code></div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Error Location</div>
                            <div class="info-value">{escape_html(error_location)}</div>
                        </div>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-title">🔍 Diagnosis Results</div>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Root Cause</div>
                            <div class="info-value">{root_cause}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Confidence Level</div>
                            <div class="info-value">
                                {int(confidence * 100)}%
                                <div class="confidence-bar">
                                    <div class="confidence-fill" style="width: {confidence * 100}%;"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Explanation</div>
                        <div class="info-value">{explanation}</div>
                    </div>
                    <div class="section">
                        <div class="info-label">Detected Patterns</div>
                        {patterns_html}
                    </div>
                    <div class="info-item">
                        <div class="info-label">Recommended Action</div>
                        <div class="info-value">{recommended_action}</div>
                    </div>
                </div>
                
                <div class="section">
                    <div class="section-title">🔧 Remediation Actions</div>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Fix Type</div>
                            <div class="info-value">{escape_html(fix_type)}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Decision</div>
                            <div class="info-value">{decision}</div>
                        </div>
                    </div>
                    <div class="section">
                        <div class="info-label">GitHub Actions</div>
                        {actions_html}
                    </div>
                </div>
                
                <div class="footer">
                    <p>This is an automated incident report generated by the Incident Orchestration System.</p>
                    <p>Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_body


def format_incident_report_plain_text(
    incident_id: str,
    timestamp: str,
    error_message: str,
    error_location: str,
    diagnosis: dict[str, Any],
    remediation: dict[str, Any],
) -> str:
    """
    Format incident report as plain text email body.
    
    Args:
        incident_id: Unique incident identifier
        timestamp: When the incident occurred
        error_message: Error message from logs
        error_location: Where the error occurred
        diagnosis: Diagnosis results
        remediation: Remediation results
        
    Returns:
        Plain text formatted email body
    """
    
    root_cause = diagnosis.get("root_cause", "Unknown")
    confidence = diagnosis.get("confidence", 0)
    patterns = diagnosis.get("patterns_detected", [])
    explanation = diagnosis.get("explanation", "")
    recommended_action = diagnosis.get("recommended_action", "")
    
    fix_type = remediation.get("fix_type", "UNKNOWN")
    decision = remediation.get("decision", "")
    github_actions = remediation.get("github_actions", [])
    
    resolution_status = "success" if any(
        a.get("status") == "success" for a in github_actions
    ) else "pending"
    
    # Build patterns section
    patterns_section = "\n".join(f"  - {pattern}" for pattern in patterns) if patterns else "  (None)"
    
    # Build GitHub actions section
    github_actions_section = ""
    if github_actions:
        actions_lines = []
        for action in github_actions:
            action_type = action.get("action_type", "unknown").replace("_", " ").title()
            status = action.get("status", "unknown").upper()
            url = action.get("url", "")
            
            line = f"  - {action_type}: {status}"
            if url:
                line += f" - {url}"
            actions_lines.append(line)
        github_actions_section = "\n".join(actions_lines)
    else:
        github_actions_section = "  (None)"
    
    text_body = f"""
INCIDENT REPORT
{'=' * 80}

STATUS: {resolution_status.upper()}

INCIDENT DETAILS
{'-' * 80}
Incident ID: {incident_id}
Timestamp: {timestamp}
Error Message: {error_message}
Error Location: {error_location}

DIAGNOSIS RESULTS
{'-' * 80}
Root Cause: {root_cause}
Confidence Level: {int(confidence * 100)}%
Explanation: {explanation}

Detected Patterns:
{patterns_section}

Recommended Action: {recommended_action}

REMEDIATION ACTIONS
{'-' * 80}
Fix Type: {fix_type}
Decision: {decision}

GitHub Actions:
{github_actions_section}

{'-' * 80}
This is an automated incident report generated by the Incident Orchestration System.
Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
    
    return text_body.strip()
