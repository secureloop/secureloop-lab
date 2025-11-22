#!/bin/bash
#
# GitHub Actions Policy Summary Generator
# Creates nice markdown summaries for GitHub Actions workflow runs
#

set -euo pipefail

RESULTS_DIR="${1:-.}"

# Function to parse conftest JSON output
parse_results() {
    local file="$1"
    local policy_name="$2"

    if [ ! -f "$file" ]; then
        echo "⚠️ No results found for $policy_name"
        return
    fi

    # Parse JSON results
    successes=$(jq -r '.[0].successes // 0' "$file" 2>/dev/null || echo "0")
    warnings=$(jq -r '[.[0].warnings // []] | length' "$file" 2>/dev/null || echo "0")
    failures=$(jq -r '[.[0].failures // []] | length' "$file" 2>/dev/null || echo "0")

    # Status badge
    if [ "$failures" -gt 0 ]; then
        status="🔴 **FAILED**"
    elif [ "$warnings" -gt 0 ]; then
        status="🟡 **WARNING**"
    else
        status="🟢 **PASSED**"
    fi

    # Generate markdown
    cat << EOF

### $policy_name $status

| Metric | Count |
|--------|-------|
| ✅ Successes | $successes |
| ⚠️  Warnings | $warnings |
| ❌ Failures | $failures |

EOF

    # List warnings if any
    if [ "$warnings" -gt 0 ]; then
        echo "<details>"
        echo "<summary>⚠️  View Warnings ($warnings)</summary>"
        echo ""
        echo "\`\`\`"
        jq -r '.[0].warnings[]?.msg // empty' "$file" 2>/dev/null | head -20
        echo "\`\`\`"
        echo "</details>"
        echo ""
    fi

    # List failures if any
    if [ "$failures" -gt 0 ]; then
        echo "<details>"
        echo "<summary>❌ View Failures ($failures)</summary>"
        echo ""
        echo "\`\`\`"
        jq -r '.[0].failures[]?.msg // empty' "$file" 2>/dev/null | head -20
        echo "\`\`\`"
        echo "</details>"
        echo ""
    fi
}

# Generate GitHub Actions Summary
{
    echo "# 🔒 Policy Validation Report"
    echo ""
    echo "**Generated:** $(date '+%Y-%m-%d %H:%M:%S UTC')"
    echo ""
    echo "---"

    # SBOM Policy
    parse_results "$RESULTS_DIR/sbom-results.json" "📋 SBOM License Compliance"

    # Docker Policy
    parse_results "$RESULTS_DIR/docker-results.json" "🐳 Docker Image Security"

    # Maven Policy (if exists)
    if [ -f "$RESULTS_DIR/maven-results.json" ]; then
        parse_results "$RESULTS_DIR/maven-results.json" "☕ Maven Build Standards"
    fi

    echo "---"
    echo ""
    echo "📁 **Artifacts:** Download detailed results from the workflow artifacts"
    echo ""
    echo "💡 **Tip:** Review warnings and failures to improve compliance"

} >> "${GITHUB_STEP_SUMMARY:-/tmp/policy-summary.md}"

# Also output to stdout for logs
cat "${GITHUB_STEP_SUMMARY:-/tmp/policy-summary.md}"
