#!/bin/bash
# Release script for creating git tags with semantic versioning

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}Error: You have uncommitted changes${NC}"
    echo "Please commit or stash your changes before creating a release."
    git status --short
    exit 1
fi

# Check for untracked files
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
    echo -e "${YELLOW}Warning: You have untracked files${NC}"
    git ls-files --others --exclude-standard
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get current branch
current_branch=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $current_branch"

# Get the most recent tag (if any)
latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "none")
echo "Latest tag: $latest_tag"

# Suggest next version
if [ "$latest_tag" = "none" ]; then
    suggested_version="0.1.0"
else
    # Strip 'v' prefix if present
    version_number=${latest_tag#v}
    # Split version into parts
    IFS='.' read -r major minor patch <<< "$version_number"
    # Increment patch version
    next_patch=$((patch + 1))
    suggested_version="$major.$minor.$next_patch"
fi

echo -e "\n${GREEN}Suggested next version: $suggested_version${NC}"
echo "Enter version number (or press Enter to use suggested version):"
read -r version_input

# Use suggested version if no input provided
if [ -z "$version_input" ]; then
    version="$suggested_version"
else
    version="$version_input"
fi

# Validate version format (basic semantic versioning check)
if ! [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}Error: Invalid version format '$version'${NC}"
    echo "Version must be in format: X.Y.Z (e.g., 1.0.0)"
    exit 1
fi

# Add 'v' prefix for tag
tag="v$version"

# Check if tag already exists
if git rev-parse "$tag" >/dev/null 2>&1; then
    echo -e "${RED}Error: Tag $tag already exists${NC}"
    exit 1
fi

# Show what will be tagged
echo -e "\n${YELLOW}Creating tag:${NC} $tag"
echo -e "${YELLOW}On commit:${NC} $(git rev-parse --short HEAD) - $(git log -1 --pretty=format:'%s')"
echo -e "${YELLOW}Branch:${NC} $current_branch"

# Confirm
read -p "Create this tag? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Create annotated tag
echo -e "\n${GREEN}Creating annotated tag $tag...${NC}"
git tag -a "$tag" -m "Release $version"

echo -e "${GREEN}Tag created successfully!${NC}"
echo -e "\nNext steps:"
echo -e "  1. Push the tag to GitHub:"
echo -e "     ${YELLOW}git push origin $tag${NC}"
echo -e "\n  2. Users can now install this version:"
echo -e "     ${YELLOW}uv tool install git+https://github.com/dhis2/gatling-statistics@$tag${NC}"
echo -e "\nOr push the tag now? (y/N) "
read -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}Pushing tag to origin...${NC}"
    git push origin "$tag"
    echo -e "${GREEN}Tag pushed successfully!${NC}"
    echo -e "\nUsers can now install with:"
    echo -e "  ${YELLOW}uv tool install git+https://github.com/dhis2/gatling-statistics@$tag${NC}"
fi
