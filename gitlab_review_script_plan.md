# GitLab Documentation Review Script - Implementation Plan

## Overview
A Python script that creates GitLab merge request suggestions from Claude's document review findings, using GitLab's native suggestion feature for one-click corrections.

## Script Structure & Dependencies

### Required Libraries
- `requests`: GitLab API calls
- `argparse`: Command line parsing
- `json`: Parse findings file
- `base64`: Decode file content from GitLab
- `urllib.parse`: URL manipulation
- `time`: Rate limiting delays
- `datetime`: Timestamp generation

### Command Line Interface
```bash
python gitlab_review.py <gitlab_project_url> <file_path> <findings_file>
```

**Arguments:**
- `gitlab_project_url`: Full GitLab project URL (e.g., `https://gitlab.com/username/project`)
- `file_path`: Path to reviewed file in repository (e.g., `docs/README.md`)
- `findings_file`: JSON file containing Claude's findings

**Environment Variables:**
- `GITLAB_API_KEY`: GitLab personal access token (required)

## Implementation Steps

### 1. Environment & Input Validation
- Load `GITLAB_API_KEY` from environment
- Parse command line arguments using `argparse`
- Validate inputs:
  - GitLab API key exists and is non-empty
  - Findings file exists and is readable
  - Project URL follows expected format
- Exit gracefully with helpful error messages if validation fails

### 2. GitLab Project Information Extraction
- Parse project URL to extract:
  - GitLab instance base URL (e.g., `https://gitlab.com`)
  - Project namespace and name (e.g., `username/project`)
- Construct GitLab API base URL: `{instance}/api/v4`
- Get project information: `GET /projects/{namespace}%2F{project}`
- Extract project ID from response

### 3. Load and Validate Claude Findings
- Load JSON findings file
- Validate structure - each finding must contain:
  ```json
  {
    "initial_text": "problematic text to locate",
    "corrected_text": "proposed correction", 
    "problem_description": "explanation of the issue"
  }
  ```
- Log summary: `"Loaded {count} findings for review"`
- Exit if no valid findings found

### 4. File Content Analysis
- Fetch current file content: `GET /projects/{id}/repository/files/{file_path}`
- Handle API response:
  - Decode base64 content if `encoding: "base64"`
  - Handle file not found errors
  - Skip binary files with warning
- For each finding:
  - Search for `initial_text` in file content
  - Calculate line number(s) where text appears
  - Handle multiple occurrences:
    - Log warning about multiple matches
    - Skip finding (safer than guessing)
  - Store mapping: `finding_index → line_number`

### 5. Create Merge Request
- Generate MR title: `f"Documentation review: {file_path} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"`
- Create MR description template:
  ```markdown
  # Automated Documentation Review
  
  This MR contains suggested corrections for `{file_path}` identified by AI review.
  
  **Review Date**: {timestamp}
  **Total Suggestions**: {len(findings)}
  
  ## How to Review
  1. Each comment contains a suggestion that can be applied with one click
  2. Click "Apply suggestion" to accept a change
  3. Use "Add suggestion to batch" to apply multiple changes together
  4. Reply to discuss any suggestion before applying
  
  ## Next Steps
  - Review each suggestion below
  - Apply accepted changes
  - Close this MR when review is complete
  ```
- Create MR: `POST /projects/{id}/merge_requests`
  - Source branch: default branch
  - Target branch: default branch (creates empty diff)
  - Store MR IID for subsequent operations

### 6. Get MR Diff Information
- Fetch MR versions: `GET /projects/{id}/merge_requests/{mr_iid}/versions`
- Extract required SHA values from first (latest) version:
  - `base_commit_sha`
  - `head_commit_sha` 
  - `start_commit_sha`
- These values are required for positioning line-specific comments

### 7. Create Discussion Threads
For each valid finding (where text was located):

#### A. Prepare Position Parameters
```python
position = {
    'position_type': 'text',
    'base_sha': base_commit_sha,
    'head_sha': head_commit_sha, 
    'start_sha': start_commit_sha,
    'old_path': file_path,
    'new_path': file_path,
    'old_line': line_number,
    'new_line': line_number  # Same line since file unchanged
}
```

#### B. Format Comment Body
````markdown
**Problem**: {problem_description}
**Current text**: "{initial_text}"
**Explanation**: {detailed_explanation_if_needed}

```suggestion:-0+0
{corrected_text}
```
````

#### C. Create Discussion Thread
- API call: `POST /projects/{id}/merge_requests/{mr_iid}/discussions`
- Include position and body parameters
- Handle rate limiting with 1-second delays between requests
- Store discussion ID for reporting

### 8. Error Handling & Recovery

#### Text Location Errors
- **Text not found**: Log warning, skip finding, continue processing
- **Multiple matches**: Log warning with line numbers, skip finding
- **Empty text**: Log error, skip finding

#### API Errors
- **Authentication (401)**: Exit with clear message about `GITLAB_API_KEY`
- **Permissions (403)**: Exit with message about insufficient permissions
- **Rate limiting (429)**: Implement exponential backoff with max retries
- **Network errors**: Retry up to 3 times with delays

#### File Errors
- **File not found (404)**: Exit with error - file path may be incorrect
- **Binary file**: Skip with warning - cannot process non-text files
- **Large files**: Handle potential API limits gracefully

### 9. Progress Reporting & Logging
- Show progress during processing:
  ```
  Processing finding 3 of 15: "Grammar error in introduction"
  ✓ Comment created on line 42
  ```
- Log skipped findings with reasons:
  ```
  ⚠ Skipped finding 7: Text "original content" not found in file
  ```
- Provide final summary:
  ```
  Summary:
  ✓ Total findings: 15
  ✓ Comments created: 12
  ⚠ Skipped (text not found): 2
  ⚠ Skipped (multiple matches): 1
  
  📋 Merge Request: https://gitlab.com/project/-/merge_requests/42
  ```

### 10. Output & Completion
- Print MR URL prominently for easy access
- Optional: Create summary JSON file with:
  ```json
  {
    "mr_url": "https://gitlab.com/project/-/merge_requests/42",
    "mr_iid": 42,
    "total_findings": 15,
    "comments_created": 12,
    "skipped_findings": 3,
    "discussion_ids": ["abc123", "def456", ...],
    "timestamp": "2025-09-15T10:30:00Z"
  }
  ```

## Configuration Options

### Command Line Flags (Optional)
- `--dry-run`: Show what would be created without making API calls
- `--verbose`: Enable detailed logging
- `--delay`: Custom delay between API calls (default: 1 second)

### Error Exit Codes
- `0`: Success
- `1`: Invalid arguments or environment
- `2`: GitLab API authentication/permission errors
- `3`: File not found or processing errors
- `4`: No valid findings to process

## Example Usage

```bash
# Set API key
export GITLAB_API_KEY="glpat-xxxxxxxxxxxxxxxxxxxx"

# Run script
python gitlab_review.py \
  https://gitlab.com/myorg/documentation \
  docs/user-guide.md \
  claude_findings.json

# Output:
# Loaded 8 findings for review
# Processing finding 1 of 8: "Inconsistent terminology"
# ✓ Comment created on line 23
# Processing finding 2 of 8: "Grammar error"
# ✓ Comment created on line 45
# ...
# 
# Summary:
# ✓ Comments created: 7
# ⚠ Skipped (text not found): 1
# 
# 📋 Review at: https://gitlab.com/myorg/documentation/-/merge_requests/15
```

## Security Considerations
- Never log or print the GitLab API key
- Use environment variables for sensitive data
- Validate all user inputs to prevent injection attacks
- Handle API errors gracefully without exposing internal details