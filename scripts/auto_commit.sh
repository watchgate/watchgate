#!/bin/bash
# auto_commit.sh: Automatically adds, commits, and pushes changes to GitHub.

# Change to your repository's directory (if not already there)
cd "$(dirname "$0")" || exit

# Stage all changes
git add .

# Create a commit message with current date/time
commit_message="Auto commit: $(date '+%Y-%m-%d %H:%M:%S')"
git commit -m "$commit_message"

# Push changes to the 'main' branch (adjust branch name if necessary)
git push -u origin main
