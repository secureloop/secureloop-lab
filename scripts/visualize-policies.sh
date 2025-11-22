#!/bin/bash
#
# OPA Policy Results Visualization Script
# Usage: ./scripts/visualize-policies.sh [format]
# Formats: html, json, table, summary (default: summary)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/policy-results"
FORMAT="${1:-summary}"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "🔍 Running OPA Policy Validation..."
echo ""

# Test SBOM Policy
echo "📋 Testing SBOM Policy..."
SBOM_FILE="$REPO_ROOT/demo-apps/java-spring/target/bom.json"

if [ ! -f "$SBOM_FILE" ]; then
    echo "⚠️  SBOM not found. Building project..."
    cd "$REPO_ROOT/demo-apps/java-spring"
    ./mvnw package -DskipTests
    cd "$REPO_ROOT"
fi

conftest test \
    --policy "$REPO_ROOT/policies/sbom/validation.rego" \
    --namespace sbom \
    --output "$FORMAT" \
    "$SBOM_FILE" > "$OUTPUT_DIR/sbom-results.$FORMAT" || true

# Test Docker Policy
echo "🐳 Testing Docker Policy..."
DOCKER_IMAGE="java-spring-lab:test"

if ! docker image inspect "$DOCKER_IMAGE" &> /dev/null; then
    echo "⚠️  Docker image not found. Building..."
    cd "$REPO_ROOT/demo-apps/java-spring"
    docker build -t "$DOCKER_IMAGE" .
    cd "$REPO_ROOT"
fi

docker inspect "$DOCKER_IMAGE" > "$OUTPUT_DIR/docker-metadata.json"

conftest test \
    --policy "$REPO_ROOT/policies/docker/image.rego" \
    --namespace docker \
    --output "$FORMAT" \
    "$OUTPUT_DIR/docker-metadata.json" > "$OUTPUT_DIR/docker-results.$FORMAT" || true

# Generate Summary
if [ "$FORMAT" = "summary" ] || [ "$FORMAT" = "json" ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 POLICY VALIDATION SUMMARY"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Parse SBOM results
    if [ "$FORMAT" = "json" ]; then
        SBOM_SUCCESSES=$(jq -r '.[0].successes // 0' "$OUTPUT_DIR/sbom-results.json")
        SBOM_WARNINGS=$(jq -r '.[0].warnings | length' "$OUTPUT_DIR/sbom-results.json")
        SBOM_FAILURES=$(jq -r '.[0].failures | length' "$OUTPUT_DIR/sbom-results.json")
    else
        SBOM_SUCCESSES=$(grep -c "SUCCESS" "$OUTPUT_DIR/sbom-results.summary" || echo "0")
        SBOM_WARNINGS=$(grep -c "WARN" "$OUTPUT_DIR/sbom-results.summary" || echo "0")
        SBOM_FAILURES=$(grep -c "FAIL" "$OUTPUT_DIR/sbom-results.summary" || echo "0")
    fi

    # SBOM Summary
    echo "📋 SBOM License Compliance:"
    echo -e "   ${GREEN}✓${NC} Successes: $SBOM_SUCCESSES"
    [ "$SBOM_WARNINGS" -gt 0 ] && echo -e "   ${YELLOW}⚠${NC} Warnings:  $SBOM_WARNINGS" || echo -e "   ${GREEN}✓${NC} Warnings:  0"
    [ "$SBOM_FAILURES" -gt 0 ] && echo -e "   ${RED}✗${NC} Failures:  $SBOM_FAILURES" || echo -e "   ${GREEN}✓${NC} Failures:  0"
    echo ""

    # Parse Docker results
    if [ "$FORMAT" = "json" ]; then
        DOCKER_SUCCESSES=$(jq -r '.[0].successes // 0' "$OUTPUT_DIR/docker-results.json")
        DOCKER_WARNINGS=$(jq -r '.[0].warnings | length' "$OUTPUT_DIR/docker-results.json")
        DOCKER_FAILURES=$(jq -r '.[0].failures | length' "$OUTPUT_DIR/docker-results.json")
    else
        DOCKER_SUCCESSES=$(grep -c "SUCCESS" "$OUTPUT_DIR/docker-results.summary" || echo "0")
        DOCKER_WARNINGS=$(grep -c "WARN" "$OUTPUT_DIR/docker-results.summary" || echo "0")
        DOCKER_FAILURES=$(grep -c "FAIL" "$OUTPUT_DIR/docker-results.summary" || echo "0")
    fi

    # Docker Summary
    echo "🐳 Docker Image Security:"
    echo -e "   ${GREEN}✓${NC} Successes: $DOCKER_SUCCESSES"
    [ "$DOCKER_WARNINGS" -gt 0 ] && echo -e "   ${YELLOW}⚠${NC} Warnings:  $DOCKER_WARNINGS" || echo -e "   ${GREEN}✓${NC} Warnings:  0"
    [ "$DOCKER_FAILURES" -gt 0 ] && echo -e "   ${RED}✗${NC} Failures:  $DOCKER_FAILURES" || echo -e "   ${GREEN}✓${NC} Failures:  0"
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Overall Status
    TOTAL_WARNINGS=$((SBOM_WARNINGS + DOCKER_WARNINGS))
    TOTAL_FAILURES=$((SBOM_FAILURES + DOCKER_FAILURES))

    if [ "$TOTAL_FAILURES" -gt 0 ]; then
        echo -e "${RED}✗ FAILED${NC} - $TOTAL_FAILURES policy violations found"
        exit 1
    elif [ "$TOTAL_WARNINGS" -gt 0 ]; then
        echo -e "${YELLOW}⚠ WARNINGS${NC} - $TOTAL_WARNINGS policy warnings found"
    else
        echo -e "${GREEN}✓ PASSED${NC} - All policies compliant!"
    fi
fi

echo ""
echo "📁 Results saved to: $OUTPUT_DIR"
echo "   - sbom-results.$FORMAT"
echo "   - docker-results.$FORMAT"
echo "   - docker-metadata.json"
echo ""

# Generate HTML report if requested
if [ "$FORMAT" = "html" ]; then
    echo "📄 Generating HTML report..."
    cat > "$OUTPUT_DIR/policy-report.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OPA Policy Validation Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 30px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }
        .card { padding: 20px; border-radius: 8px; text-align: center; }
        .card.success { background: #d4edda; border-left: 4px solid #28a745; }
        .card.warning { background: #fff3cd; border-left: 4px solid #ffc107; }
        .card.failure { background: #f8d7da; border-left: 4px solid #dc3545; }
        .card h3 { margin: 0 0 10px 0; font-size: 14px; color: #666; text-transform: uppercase; }
        .card .number { font-size: 36px; font-weight: bold; margin: 10px 0; }
        .policy-section { margin: 30px 0; padding: 20px; background: #f8f9fa; border-radius: 8px; }
        .result-item { padding: 10px; margin: 5px 0; border-radius: 4px; }
        .result-item.success { background: #d4edda; }
        .result-item.warning { background: #fff3cd; }
        .result-item.failure { background: #f8d7da; }
        pre { background: #2c3e50; color: #ecf0f1; padding: 20px; border-radius: 8px; overflow-x: auto; }
        .timestamp { color: #7f8c8d; font-size: 14px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔒 OPA Policy Validation Report</h1>
        <div class="timestamp">Generated: __TIMESTAMP__</div>

        <div class="summary">
            <div class="card success">
                <h3>Successes</h3>
                <div class="number">__TOTAL_SUCCESSES__</div>
            </div>
            <div class="card warning">
                <h3>Warnings</h3>
                <div class="number">__TOTAL_WARNINGS__</div>
            </div>
            <div class="card failure">
                <h3>Failures</h3>
                <div class="number">__TOTAL_FAILURES__</div>
            </div>
        </div>

        <div class="policy-section">
            <h2>📋 SBOM License Compliance</h2>
            <p><strong>File:</strong> demo-apps/java-spring/target/bom.json</p>
            <pre>__SBOM_RESULTS__</pre>
        </div>

        <div class="policy-section">
            <h2>🐳 Docker Image Security</h2>
            <p><strong>Image:</strong> java-spring-lab:test</p>
            <pre>__DOCKER_RESULTS__</pre>
        </div>
    </div>
</body>
</html>
EOF

    # Get results as text for HTML
    SBOM_TEXT=$(cat "$OUTPUT_DIR/sbom-results.summary" 2>/dev/null || echo "No results")
    DOCKER_TEXT=$(cat "$OUTPUT_DIR/docker-results.summary" 2>/dev/null || echo "No results")

    # Replace placeholders
    sed -i.bak "s|__TIMESTAMP__|$(date '+%Y-%m-%d %H:%M:%S')|g" "$OUTPUT_DIR/policy-report.html"
    sed -i.bak "s|__TOTAL_SUCCESSES__|$((SBOM_SUCCESSES + DOCKER_SUCCESSES))|g" "$OUTPUT_DIR/policy-report.html"
    sed -i.bak "s|__TOTAL_WARNINGS__|$TOTAL_WARNINGS|g" "$OUTPUT_DIR/policy-report.html"
    sed -i.bak "s|__TOTAL_FAILURES__|$TOTAL_FAILURES|g" "$OUTPUT_DIR/policy-report.html"
    sed -i.bak "s|__SBOM_RESULTS__|$(echo "$SBOM_TEXT" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')|g" "$OUTPUT_DIR/policy-report.html"
    sed -i.bak "s|__DOCKER_RESULTS__|$(echo "$DOCKER_TEXT" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')|g" "$OUTPUT_DIR/policy-report.html"

    rm "$OUTPUT_DIR/policy-report.html.bak"

    echo "✅ HTML report generated: $OUTPUT_DIR/policy-report.html"
    echo "   Open with: open $OUTPUT_DIR/policy-report.html"
fi
