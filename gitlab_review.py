"""
GitLab Documentation Review Script

Creates GitLab merge request suggestions from Claude's document review findings,
using GitLab's native suggestion feature for one-click corrections.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests


class GitLabReviewError(Exception):
    """Custom exception for GitLab review script errors."""
    pass


class GitLabReviewer:
    """Main class for creating GitLab merge requests with review suggestions."""
    
    def __init__(self, api_key: str, verbose: bool = False):
        self.api_key = api_key
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
    
    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message with timestamp and level."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level == "ERROR":
            print(f"[{timestamp}] ❌ {message}", file=sys.stderr)
        elif level == "WARNING":
            print(f"[{timestamp}] ⚠️  {message}")
        elif level == "SUCCESS":
            print(f"[{timestamp}] ✅ {message}")
        elif self.verbose or level == "INFO":
            print(f"[{timestamp}] ℹ️  {message}")
    
    def parse_gitlab_url(self, project_url: str) -> Tuple[str, str, str]:
        """
        Parse GitLab project URL to extract instance, namespace, and project name.
        
        Args:
            project_url: Full GitLab project URL
            
        Returns:
            Tuple of (instance_url, namespace, project_name)
        """
        try:
            parsed = urllib.parse.urlparse(project_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL format")
            
            instance_url = f"{parsed.scheme}://{parsed.netloc}"
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) < 2:
                raise ValueError("URL must contain namespace and project name")
            
            namespace = path_parts[0]
            project_name = path_parts[1]
            
            return instance_url, namespace, project_name
            
        except Exception as e:
            raise GitLabReviewError(f"Failed to parse GitLab URL '{project_url}': {e}")
    
    def get_project_info(self, instance_url: str, namespace: str, project_name: str) -> Dict:
        """
        Get GitLab project information including project ID.
        
        Args:
            instance_url: GitLab instance base URL
            namespace: Project namespace
            project_name: Project name
            
        Returns:
            Project information dictionary
        """
        api_url = f"{instance_url}/api/v4"
        project_path = f"{namespace}%2F{project_name}"
        url = f"{api_url}/projects/{project_path}"
        
        try:
            if self.verbose:
                self.log(f"Fetching project info from URL: {url}")
            
            response = self.session.get(url)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            if response.status_code == 401:
                raise GitLabReviewError("Authentication failed. Please check your GITLAB_API_KEY.")
            elif response.status_code == 403:
                raise GitLabReviewError("Insufficient permissions to access this project.")
            elif response.status_code == 404:
                raise GitLabReviewError(f"Project '{namespace}/{project_name}' not found.")
            
            response.raise_for_status()
            project_info = response.json()
            
            self.log(f"Found project: {project_info['name']} (ID: {project_info['id']})")
            return project_info
            
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to get project information: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def load_findings(self, findings_file: str) -> List[Dict]:
        """
        Load and validate Claude findings from JSON file.
        
        Args:
            findings_file: Path to JSON file containing findings
            
        Returns:
            List of validated findings
        """
        try:
            with open(findings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both direct list and wrapped format
            findings = data if isinstance(data, list) else data.get('findings', [])
            
            if not findings:
                raise GitLabReviewError("No findings found in the JSON file.")
            
            # Validate each finding
            valid_findings = []
            required_fields = ['initial_text', 'corrected_text', 'problem_description']
            
            for i, finding in enumerate(findings):
                if not isinstance(finding, dict):
                    self.log(f"Skipping finding {i+1}: Not a valid object", "WARNING")
                    continue
                
                missing_fields = [field for field in required_fields if not finding.get(field)]
                if missing_fields:
                    self.log(f"Skipping finding {i+1}: Missing fields: {missing_fields}", "WARNING")
                    continue
                
                # Clean up text fields
                finding['initial_text'] = finding['initial_text'].strip()
                finding['corrected_text'] = finding['corrected_text'].strip()
                
                if not finding['initial_text']:
                    self.log(f"Skipping finding {i+1}: Empty initial_text", "WARNING")
                    continue
                
                valid_findings.append(finding)
            
            if not valid_findings:
                raise GitLabReviewError("No valid findings found after validation.")
            
            self.log(f"Loaded {len(valid_findings)} valid findings for review")
            return valid_findings
            
        except FileNotFoundError:
            raise GitLabReviewError(f"Findings file '{findings_file}' not found.")
        except json.JSONDecodeError as e:
            raise GitLabReviewError(f"Invalid JSON in findings file: {e}")
        except Exception as e:
            raise GitLabReviewError(f"Failed to load findings: {e}")
    
    def get_file_content(self, api_url: str, project_id: int, file_path: str, ref: str) -> str:
        """
        Get file content from GitLab repository.
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            file_path: Path to file in repository
            ref: Branch or tag name
            
        Returns:
            File content as string
        """
        url = f"{api_url}/projects/{project_id}/repository/files/{urllib.parse.quote(file_path, safe='')}"
        
        try:
            if self.verbose:
                self.log(f"Fetching file content from URL: {url}")
            
            response = self.session.get(url, params={'ref': ref})
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            if response.status_code == 404:
                raise GitLabReviewError(f"File '{file_path}' not found in repository.")
            
            response.raise_for_status()
            file_info = response.json()
            
            # Decode content
            content = file_info.get('content', '')
            encoding = file_info.get('encoding', 'text')
            
            if encoding == 'base64':
                try:
                    content = base64.b64decode(content).decode('utf-8')
                except UnicodeDecodeError:
                    raise GitLabReviewError(f"File '{file_path}' appears to be binary and cannot be processed.")
            
            self.log(f"Retrieved file content: {len(content)} characters")
            return content
            
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to get file content: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def find_text_lines(self, content: str, findings: List[Dict]) -> Dict[int, int]:
        """
        Find line numbers for each finding's initial text.
        
        Args:
            content: File content
            findings: List of findings
            
        Returns:
            Dictionary mapping finding index to line number
        """
        lines = content.splitlines()
        finding_lines = {}
        
        for i, finding in enumerate(findings):
            initial_text = finding['initial_text']
            matches = []
            
            # Search for text in each line
            for line_num, line in enumerate(lines, 1):
                if initial_text in line:
                    matches.append(line_num)
            
            if len(matches) == 0:
                self.log(f"Finding {i+1}: Text not found - '{initial_text[:50]}...'", "WARNING")
            elif len(matches) > 1:
                self.log(f"Finding {i+1}: Multiple matches found on lines {matches} - skipping", "WARNING")
            else:
                finding_lines[i] = matches[0]
                self.log(f"Finding {i+1}: Located on line {matches[0]}", "SUCCESS")
        
        return finding_lines
    
    def create_merge_request(self, api_url: str, project_id: int, file_path: str, 
                           findings_count: int, source_branch: str, target_branch: str) -> Dict:
        """
        Create a merge request for the review.
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            file_path: Path to reviewed file
            findings_count: Number of findings
            source_branch: Source branch for the merge request
            target_branch: Target branch for the merge request
            
        Returns:
            Merge request information
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        title = f"Documentation review: {file_path} - {timestamp}"
        
        description = f"""# Automated Documentation Review

This MR contains suggested corrections for `{file_path}` identified by AI review.

**Review Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Total Suggestions**: {findings_count}

## How to Review
1. Each comment contains a suggestion that can be applied with one click
2. Click "Apply suggestion" to accept a change
3. Use "Add suggestion to batch" to apply multiple changes together
4. Reply to discuss any suggestion before applying

## Next Steps
- Review each suggestion below
- Apply accepted changes
- Merge this MR when review is complete
"""
        
        data = {
            'title': title,
            'description': description,
            'source_branch': source_branch,
            'target_branch': target_branch
        }
        
        url = f"{api_url}/projects/{project_id}/merge_requests"
        
        try:
            if self.verbose:
                self.log(f"Creating merge request at URL: {url}")
                self.log(f"Request data: {json.dumps(data, indent=2)}")
            
            response = self.session.post(url, json=data)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            response.raise_for_status()
            mr_info = response.json()
            
            self.log(f"Created merge request: {mr_info['web_url']}")
            return mr_info
            
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to create merge request: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def get_mr_diff_info(self, api_url: str, project_id: int, mr_iid: int) -> Dict:
        """
        Get merge request diff information for positioning comments.
        
        Returns a dictionary with the following keys:
            - 'base_commit_sha': The SHA of the base commit in the target branch (the branch being merged into)
            - 'head_commit_sha': The SHA of the head commit in the source branch (the branch containing the changes)
            - 'start_commit_sha': The SHA of the common ancestor commit between the source and target branches
        
        These values are used to position comments correctly in the merge request diff view.
        For more details, see the GitLab API documentation for merge requests:
        https://docs.gitlab.com/ee/api/merge_requests.html#response-attributes
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            mr_iid: Merge request IID
            
        Returns:
            Dictionary with SHA values
        """
        url = f"{api_url}/projects/{project_id}/merge_requests/{mr_iid}"
        
        try:
            if self.verbose:
                self.log(f"Fetching MR diff info from URL: {url}")
            
            response = self.session.get(url)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            response.raise_for_status()
            mr_info = response.json()
            
            if 'diff_refs' not in mr_info:
                raise GitLabReviewError("No diff_refs found in merge request.")
            
            return {
                'base_commit_sha': mr_info['diff_refs']['base_sha'],
                'head_commit_sha': mr_info['diff_refs']['head_sha'],
                'start_commit_sha': mr_info['diff_refs']['start_sha']
            }
            
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to get MR diff information: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def create_discussion(self, api_url: str, project_id: int, mr_iid: int,
                         finding: Dict, line_number: int, diff_info: Dict, file_path: str) -> str:
        """
        Create a discussion thread with suggestion for a finding.
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            mr_iid: Merge request IID
            finding: Finding dictionary
            line_number: Line number for the comment
            diff_info: Diff information with SHA values
            file_path: Path to the file
            
        Returns:
            Discussion ID
        """
        # Format the comment body with GitLab suggestion syntax
        body = f"""{finding['problem_description']}

```suggestion:-0+0
{finding['corrected_text']}
```"""
        # Compute SHA1 hash of the filename
        filename_hash = hashlib.sha1(file_path.encode('utf-8')).hexdigest()
        position = {
            'position_type': 'text',
            'base_sha': diff_info['base_commit_sha'],
            'head_sha': diff_info['head_commit_sha'],
            'start_sha': diff_info['start_commit_sha'],
            'old_path': file_path,
            'new_path': file_path,
            'old_line': line_number,
            'new_line': line_number,
            'line_range': {
                'start': {
                    'old_line': line_number,
                    'new_line': line_number,
                    'line_code': f"{filename_hash}_{line_number}_{line_number}"
                },
                'end': {
                    'old_line': line_number,
                    'new_line': line_number,
                    'line_code': f"{filename_hash}_{line_number}_{line_number}"
                }
            }   
        }
        
        data = {
            'body': body,
            'position': position
        }
        
        url = f"{api_url}/projects/{project_id}/merge_requests/{mr_iid}/discussions"
        
        try:
            if self.verbose:
                self.log(f"Creating discussion at URL: {url}")
                self.log(f"Request data: {json.dumps(data, indent=2)}")
            
            response = self.session.post(url, json=data)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            response.raise_for_status()
            discussion = response.json()
            
            return discussion['id']
            
        except requests.RequestException as e:
            # Capture response text for detailed error analysis
            response_text = response.text if response else "No response received"
            error_msg = f"Failed to create discussion: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def create_branch(self, api_url: str, project_id: int, branch_name: str, ref: str) -> None:
        """
        Create a new branch in the project.
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            branch_name: Name of the new branch
            ref: Branch or commit SHA to base the new branch on
        """
        url = f"{api_url}/projects/{project_id}/repository/branches"
        data = {
            'branch': branch_name,
            'ref': ref
        }
        
        try:
            if self.verbose:
                self.log(f"Creating branch at URL: {url}")
                self.log(f"Request data: {json.dumps(data, indent=2)}")
            
            response = self.session.post(url, json=data)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
                self.log(f"Response content: {response.text}")
                
            response.raise_for_status()
            self.log(f"Created branch: {branch_name}")
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to create branch: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def add_blank_line(self, api_url: str, project_id: int, branch_name: str, file_path: str) -> None:
        """
        Add a blank line at the end of a file and commit it to create a diff.
        
        Args:
            api_url: GitLab API base URL
            project_id: Project ID
            branch_name: Name of the branch to commit to
            file_path: Path to the file to modify
        """
        # First, get the current file content
        try:
            if self.verbose:
                self.log(f"Getting current content of {file_path} on branch {branch_name}")
                
            # Get the current file content
            content = self.get_file_content(api_url, project_id, file_path, branch_name)
            
            # Add a blank line if it doesn't already end with one
            if not content.endswith('\n'):
                content += '\n'
            content += '\n'  # Add an extra blank line
            
            # Use the file update API
            url = f"{api_url}/projects/{project_id}/repository/files/{urllib.parse.quote(file_path, safe='')}"
            
            # Prepare update data
            update_data = {
                'branch': branch_name,
                'content': content,
                'commit_message': 'Add blank line for review comments'
            }
            
            if self.verbose:
                self.log(f"Updating file at URL: {url}")
                update_data_log = update_data.copy()
                update_data_log['content'] = '[content truncated]'
                self.log(f"Update data: {json.dumps(update_data_log, indent=2)}")
            
            response = self.session.put(url, json=update_data)
            
            if self.verbose:
                self.log(f"Response status: {response.status_code}")
                self.log(f"Response headers: {response.headers}")
            
            response.raise_for_status()
            self.log(f"Added blank line to {file_path}")
            
        except requests.RequestException as e:
            response_text = response.text if hasattr(response, 'text') else "No response received"
            error_msg = f"Failed to add blank line to file: {e}\nResponse: {response_text}"
            raise GitLabReviewError(error_msg)
    
    def process_review(self, project_url: str, file_path: str, findings_file: str) -> Dict:
        """
        Main method to process the review and create merge request with suggestions.
        
        Args:
            project_url: GitLab project URL
            file_path: Path to file in repository
            findings_file: Path to findings JSON file
            
        Returns:
            Summary dictionary
        """
        # Parse project URL
        instance_url, namespace, project_name = self.parse_gitlab_url(project_url)
        api_url = f"{instance_url}/api/v4"
        
        # Get project information
        project_info = self.get_project_info(instance_url, namespace, project_name)
        project_id = project_info['id']
        default_branch = project_info['default_branch']
        
        # Load findings
        findings = self.load_findings(findings_file)
        
        # Create a new branch for the review
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        branch_name = f"documentation-review-{timestamp}"
        self.create_branch(api_url, project_id, branch_name, default_branch)
        
        # Get file content and find text locations
        content = self.get_file_content(api_url, project_id, file_path, default_branch)
        finding_lines = self.find_text_lines(content, findings)
        
        if not finding_lines:
            raise GitLabReviewError("No findings could be located in the file.")
        
        # Create merge request
        mr_info = self.create_merge_request(api_url, project_id, file_path, len(findings), branch_name, default_branch)
        mr_iid = mr_info['iid']
        
        # Add a blank line at the end of the file
        self.add_blank_line(api_url, project_id, branch_name, file_path)
        
        # sleep for 10 seconds otherwise GitLab will return 500 errors (probably because it would still be updating the Merge Request)
        time.sleep(10)
        
        # Get diff information
        diff_info = self.get_mr_diff_info(api_url, project_id, mr_iid)
        
        # Create discussions for each finding
        discussion_ids = []
        comments_created = 0
        
        for finding_idx, line_number in finding_lines.items():
            finding = findings[finding_idx]
            
            self.log(f"Processing finding {finding_idx + 1} of {len(findings)}: \"{finding['problem_description'][:50]}...\"")
            
            try:
                discussion_id = self.create_discussion(
                    api_url, project_id, mr_iid, finding, line_number, diff_info, file_path
                )
                discussion_ids.append(discussion_id)
                comments_created += 1
                self.log(f"✓ Comment created on line {line_number}", "SUCCESS")
                
                # Rate limiting
                time.sleep(2)
                    
            except Exception as e:
                self.log(f"Failed to create comment for finding {finding_idx + 1}: {e}", "ERROR")
        
        # Summary
        skipped_count = len(findings) - len(finding_lines)
        summary = {
            "mr_url": mr_info['web_url'],
            "mr_iid": mr_iid,
            "total_findings": len(findings),
            "comments_created": comments_created,
            "skipped_findings": skipped_count,
            "discussion_ids": discussion_ids,
            "timestamp": datetime.now().isoformat()
        }
        
        self.log("\n=== SUMMARY ===")
        self.log(f"✓ Total findings: {len(findings)}")
        self.log(f"✓ Comments created: {comments_created}")
        if skipped_count > 0:
            self.log(f"⚠ Skipped (text not found): {skipped_count}")
        self.log(f"\n📋 Merge Request: {mr_info['web_url']}")
        
        return summary


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Create GitLab merge request suggestions from review findings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  export GITLAB_API_KEY="xxxxxxxxxxxxxxxxxxxx"
  python gitlab_review.py https://gitlab.com/myorg/myproject filepath/filename findings.json

The syntax of the findings JSON file is as follows:
[
  {
    "initial_text": "This is a example of poor grammar",
    "corrected_text": "This is an example of poor grammar",
    "problem_description": "Incorrect article usage - should use 'an' before words starting with vowel sounds"
  },
  ...
]
where:
- initial_text: The original text that needs to be corrected
- corrected_text: The suggested correction for the text
- problem_description: A description of the issue found in the text
        """
    )
    
    parser.add_argument('project_url', help='GitLab project URL (e.g., https://gitlab.com/username/project)')
    parser.add_argument('file_path', help='Path to reviewed file in repository (e.g., docs/README.md)')
    parser.add_argument('findings_file', help='JSON file containing review findings')
    parser.add_argument('--verbose', action='store_true', help='Enable detailed logging')
    
    args = parser.parse_args()
    
    # Validate environment
    api_key = os.getenv('GITLAB_API_KEY')
    if not api_key:
        print("❌ Error: GITLAB_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)
    
    # Validate findings file exists
    if not os.path.isfile(args.findings_file):
        print(f"❌ Error: Findings file '{args.findings_file}' not found", file=sys.stderr)
        sys.exit(1)
    
    try:
        reviewer = GitLabReviewer(api_key, verbose=args.verbose)
        summary = reviewer.process_review(args.project_url, args.file_path, args.findings_file)
        
        # Save summary to file
        summary_file = f"review_summary_{summary['mr_iid']}.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\n📄 Summary saved to: {summary_file}")
        
        sys.exit(0)
        
    except GitLabReviewError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(3)
    except KeyboardInterrupt:
        print("\n⚠️ Operation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == '__main__':
    main()
