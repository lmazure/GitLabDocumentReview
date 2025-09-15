# GitLab Documentation Review Script

A Python script that creates GitLab merge request suggestions from Claude's document review findings, using GitLab's native suggestion feature for one-click corrections.

## Features

- **Automated MR Creation**: Creates merge requests with AI-generated documentation suggestions
- **GitLab Native Suggestions**: Uses GitLab's built-in suggestion syntax for one-click corrections
- **Smart Text Matching**: Locates problematic text in files and maps to specific line numbers
- **Comprehensive Error Handling**: Graceful handling of API errors, missing text, and edge cases
- **Progress Reporting**: Real-time feedback during processing with detailed summaries
- **Dry Run Mode**: Preview what would be created without making actual changes

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd GitLabDocumentReview
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your GitLab API token:
```bash
export GITLAB_API_KEY="glpat-xxxxxxxxxxxxxxxxxxxx"
```

## Usage

### Basic Usage

```bash
python gitlab_review.py <gitlab_project_url> <file_path> <findings_file>
```

**Arguments:**
- `gitlab_project_url`: Full GitLab project URL (e.g., `https://gitlab.com/username/project`)
- `file_path`: Path to reviewed file in repository (e.g., `docs/README.md`)
- `findings_file`: JSON file containing Claude's findings

### Command Line Options

- `--dry-run`: Show what would be created without making API calls
- `--verbose`: Enable detailed logging
- `--delay`: Custom delay between API calls in seconds (default: 1.0)

### Examples

```bash
# Basic usage
python gitlab_review.py \
  https://gitlab.com/myorg/documentation \
  docs/user-guide.md \
  claude_findings.json

# Dry run to preview changes
python gitlab_review.py --dry-run \
  https://gitlab.com/myorg/docs \
  README.md \
  findings.json

# Verbose output with custom delay
python gitlab_review.py --verbose --delay 2.0 \
  https://gitlab.example.com/team/project \
  docs/api.md \
  review_findings.json
```

## Findings File Format

The findings file should be a JSON array with objects containing:

```json
[
  {
    "initial_text": "problematic text to locate",
    "corrected_text": "proposed correction",
    "problem_description": "explanation of the issue"
  }
]
```

### Example Findings File

See `example_findings.json` for a complete example with common documentation issues like:
- Grammar corrections
- Word choice improvements
- Punctuation fixes
- Style consistency

## How It Works

1. **Validation**: Validates GitLab API access and input files
2. **Project Analysis**: Extracts project information from GitLab URL
3. **File Processing**: Retrieves file content and locates problematic text
4. **MR Creation**: Creates a merge request with descriptive title and instructions
5. **Suggestion Comments**: Adds line-specific comments with GitLab suggestion syntax
6. **Summary**: Provides detailed report of created suggestions and any skipped items

## GitLab Permissions

Your GitLab API token needs the following permissions:
- `api`: Full API access
- `read_repository`: Read repository files
- `write_repository`: Create merge requests and comments

## Error Handling

The script handles various error conditions gracefully:

- **Authentication Issues**: Clear messages about API token problems
- **Missing Files**: Helpful errors when files aren't found
- **Text Not Found**: Warnings when review text can't be located
- **Multiple Matches**: Skips ambiguous text matches for safety
- **Network Issues**: Retries with exponential backoff

## Exit Codes

- `0`: Success
- `1`: Invalid arguments or environment setup
- `2`: GitLab API authentication/permission errors
- `3`: File not found or processing errors
- `4`: No valid findings to process

## Output

The script generates:
- **Console Output**: Real-time progress and summary
- **Summary JSON**: Detailed results saved to `review_summary_{mr_iid}.json`
- **GitLab MR**: Merge request with suggestion comments

### Example Output

```
[10:30:15] ✅ Found project: Documentation (ID: 123)
[10:30:16] ℹ️  Loaded 8 valid findings for review
[10:30:17] ℹ️  Retrieved file content: 2,847 characters
[10:30:17] ✅ Finding 1: Located on line 23
[10:30:17] ✅ Finding 2: Located on line 45
[10:30:18] ⚠️  Finding 3: Text not found - 'outdated content...'
[10:30:18] ✅ Created merge request: https://gitlab.com/project/-/merge_requests/42
[10:30:19] ✅ ✓ Comment created on line 23
[10:30:20] ✅ ✓ Comment created on line 45

=== SUMMARY ===
[10:30:21] ℹ️  ✓ Total findings: 8
[10:30:21] ℹ️  ✓ Comments created: 7
[10:30:21] ℹ️  ⚠ Skipped (text not found): 1

[10:30:21] ℹ️  📋 Merge Request: https://gitlab.com/project/-/merge_requests/42
```

## Security Considerations

- Never commit your GitLab API token to version control
- Use environment variables for sensitive configuration
- The script validates all inputs to prevent injection attacks
- API errors are handled without exposing internal details

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Troubleshooting

### Common Issues

**"Authentication failed"**
- Check that `GITLAB_API_KEY` is set correctly
- Verify your token has the required permissions
- Ensure the token hasn't expired

**"Project not found"**
- Verify the GitLab URL is correct
- Check that you have access to the project
- Ensure the project exists and is not private (unless you have access)

**"File not found"**
- Check the file path is correct relative to repository root
- Verify the file exists in the default branch
- Ensure file path uses forward slashes, not backslashes

**"Text not found" warnings**
- The original text may have been modified since the review
- Check for exact text matches (case-sensitive)
- Consider updating the findings file with current text

### Getting Help

If you encounter issues:
1. Run with `--verbose` for detailed logging
2. Try `--dry-run` to test without making changes
3. Check the GitLab API documentation for your instance
4. Verify your findings JSON format matches the expected structure
