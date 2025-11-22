# OPA Policy Results Visualization Guide

This guide shows you various ways to visualize OPA/Conftest policy results for better understanding and reporting.

## Quick Start

```bash
# Run all visualizations
cd /Users/tonit/devel/rebaze/prison
./scripts/visualize-policies.sh summary
```

## Visualization Options

### 1. Terminal Summary (Best for Development)

**Quick, colorized overview in terminal**

```bash
./scripts/visualize-policies.sh summary
```

**Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 POLICY VALIDATION SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 SBOM License Compliance:
   ✓ Successes: 8
   ✓ Warnings:  0
   ✓ Failures:  0

🐳 Docker Image Security:
   ✓ Successes: 6
   ⚠ Warnings:  4
   ✓ Failures:  0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠ WARNINGS - 4 policy warnings found
```

**Pros:**
- ✅ Fast and lightweight
- ✅ Color-coded for easy scanning
- ✅ Perfect for daily development

---

### 2. Table Format (Best for CLI)

**Clean tabular output**

```bash
# SBOM
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  --output table \
  demo-apps/java-spring/target/bom.json

# Docker
docker inspect java-spring-lab:test > /tmp/docker.json
conftest test \
  --policy policies/docker/image.rego \
  --namespace docker \
  --output table \
  /tmp/docker.json
```

**Output:**
```
┌─────────┬──────────┬───────────┬─────────────────────────────┐
│ RESULT  │   FILE   │ NAMESPACE │          MESSAGE            │
├─────────┼──────────┼───────────┼─────────────────────────────┤
│ success │ bom.json │ sbom      │ SUCCESS                     │
│ warning │ bom.json │ sbom      │ Missing license: component  │
└─────────┴──────────┴───────────┴─────────────────────────────┘
```

**Pros:**
- ✅ Structured and scannable
- ✅ Works well in CI logs
- ✅ Easy to read

---

### 3. JSON Format (Best for Automation)

**Machine-readable structured output**

```bash
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  --output json \
  demo-apps/java-spring/target/bom.json | jq
```

**Output:**
```json
[
  {
    "filename": "demo-apps/java-spring/target/bom.json",
    "namespace": "sbom",
    "successes": 8,
    "warnings": [
      {
        "msg": "Component 'xyz' is missing license"
      }
    ],
    "failures": []
  }
]
```

**Pros:**
- ✅ Perfect for CI/CD pipelines
- ✅ Easy to parse with jq
- ✅ Can feed into dashboards

**Use Cases:**
```bash
# Count total warnings
conftest test --output json ... | jq '.[].warnings | length'

# Extract specific warnings
conftest test --output json ... | jq -r '.[].warnings[]?.msg'

# Get pass/fail status
conftest test --output json ... | jq -r 'if .[0].failures | length > 0 then "FAIL" else "PASS" end'
```

---

### 4. HTML Report (Best for Stakeholders)

**Visual web-based report**

```bash
./scripts/visualize-policies.sh html
open policy-results/policy-report.html
```

**Features:**
- 📊 Summary cards (successes, warnings, failures)
- 📋 Detailed policy results
- 🎨 Color-coded sections
- ⏱️ Timestamp and metadata

**Pros:**
- ✅ Professional looking
- ✅ Easy to share with stakeholders
- ✅ Self-contained (single HTML file)
- ✅ No server required

---

### 5. JUnit XML (Best for CI Integration)

**Standard test result format**

```bash
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  --output junit \
  demo-apps/java-spring/target/bom.json > sbom-junit.xml
```

**Output:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite tests="8" failures="0" errors="0" skipped="0">
    <testcase classname="sbom" name="success_0"/>
    <testcase classname="sbom" name="warning_0">
      <failure message="Component missing license"/>
    </testcase>
  </testsuite>
</testsuites>
```

**Pros:**
- ✅ Integrates with CI systems (Jenkins, GitLab, etc.)
- ✅ Shows in test reports tab
- ✅ Standard format

---

### 6. GitHub Actions Integration (Best for GitHub)

**Native GitHub Actions summary and annotations**

**Method A: GitHub Output Format**

```yaml
- name: Validate Policies
  run: |
    conftest test \
      --policy policies/sbom/ \
      --namespace sbom \
      --output github \
      demo-apps/java-spring/target/bom.json
```

Creates annotations directly in GitHub UI!

**Method B: Workflow Summary**

Add to your workflow:

```yaml
- name: Generate Policy Summary
  if: always()
  run: |
    # Save results as JSON
    conftest test \
      --policy policies/sbom/validation.rego \
      --namespace sbom \
      --output json \
      artifacts/bom.json > artifacts/sbom-results.json || true

    conftest test \
      --policy policies/docker/image.rego \
      --namespace docker \
      --output json \
      artifacts/docker-metadata.json > artifacts/docker-results.json || true

    # Generate GitHub summary
    ./scripts/github-policy-summary.sh artifacts/
```

**Features:**
- 📝 Markdown summary in workflow run
- 📊 Collapsible sections for warnings/failures
- 🎨 Emoji and formatting
- 🔗 Links to artifacts

---

## Comparison Matrix

| Format      | Use Case             | Pros                          | Cons                     |
|-------------|----------------------|-------------------------------|--------------------------|
| **Summary** | Daily development    | Fast, colorized, easy to read | Limited detail           |
| **Table**   | CLI/Terminal         | Structured, clean             | Can be verbose           |
| **JSON**    | Automation/CI        | Machine-readable, flexible    | Hard to read manually    |
| **HTML**    | Reports/Stakeholders | Professional, shareable       | Requires browser         |
| **JUnit**   | CI integration       | Standard format, CI-friendly  | XML (verbose)            |
| **GitHub**  | GitHub Actions       | Native integration, pretty    | GitHub-specific          |

---

## Advanced Visualizations

### Custom jq Queries

**Get summary statistics:**
```bash
conftest test --output json ... | jq '{
  total_tests: .[0].successes,
  warnings: (.[0].warnings | length),
  failures: (.[0].failures | length),
  status: (if (.[0].failures | length) > 0 then "FAIL" else "PASS" end)
}'
```

**List all warning messages:**
```bash
conftest test --output json ... | jq -r '.[].warnings[]?.msg' | sort | uniq
```

**Group results by severity:**
```bash
conftest test --output json ... | jq '{
  critical: [.[].failures[]] | length,
  warnings: [.[].warnings[]] | length,
  passed: .[0].successes
}'
```

---

### Dashboard Integration

**Send to Grafana/Prometheus:**

```bash
# Convert to metrics format
conftest test --output json ... | jq -r '
  .[0] |
  "policy_successes " + (.successes | tostring) + "\n" +
  "policy_warnings " + (.warnings | length | tostring) + "\n" +
  "policy_failures " + (.failures | length | tostring)
' | curl -X POST http://pushgateway:9091/metrics/job/policy_check --data-binary @-
```

**Send to Slack:**

```bash
# Generate Slack message
WARNINGS=$(conftest test --output json ... | jq -r '.[].warnings | length')

if [ "$WARNINGS" -gt 0 ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\":warning: $WARNINGS policy warnings found\"}" \
        $SLACK_WEBHOOK_URL
fi
```

---

## Best Practices

### 1. Choose the Right Format for the Context

```bash
# Development (local)
./scripts/visualize-policies.sh summary

# CI/CD logs
conftest test --output table ...

# Automation
conftest test --output json ... | jq ...

# Reporting
./scripts/visualize-policies.sh html

# GitHub Actions
conftest test --output github ...
```

### 2. Archive Results

```bash
# Create timestamped archive
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
./scripts/visualize-policies.sh json
mv policy-results "policy-results-$TIMESTAMP"
```

### 3. Combine Formats

```bash
# Generate multiple formats
for format in table json html; do
    ./scripts/visualize-policies.sh $format
done
```

### 4. Filter Results

```bash
# Only show failures
conftest test --output json ... | jq '.[] | select(.failures | length > 0)'

# Only show warnings
conftest test --output json ... | jq '.[] | select(.warnings | length > 0)'
```

---

## Examples for Your Project

### Daily Development Workflow

```bash
# 1. Build and test
cd demo-apps/java-spring
./mvnw package
docker build -t java-spring-lab:test .

# 2. Run visualization
cd ../..
./scripts/visualize-policies.sh summary

# 3. Review results
cat policy-results/sbom-results.summary
cat policy-results/docker-results.summary
```

### Pre-Commit Check

```bash
# Quick validation before commit
./scripts/visualize-policies.sh table || {
    echo "❌ Policy violations found. Fix before committing."
    exit 1
}
```

### Weekly Report

```bash
# Generate HTML report for weekly review
./scripts/visualize-policies.sh html
open policy-results/policy-report.html

# Archive for history
mv policy-results policy-results-$(date +%Y-week-%U)
```

---

## Troubleshooting

### JSON Output Shows Empty Results

**Problem:** `jq` shows `null` or empty arrays
**Solution:** Check if tests ran with warnings suppressed:
```bash
conftest test --output json ... 2>&1 | tee results.json
```

### HTML Report Not Showing Results

**Problem:** Placeholders not replaced
**Solution:** Ensure summary format is run first:
```bash
./scripts/visualize-policies.sh summary
./scripts/visualize-policies.sh html
```

### GitHub Summary Not Appearing

**Problem:** `$GITHUB_STEP_SUMMARY` not set
**Solution:** Only works in GitHub Actions environment. Test locally:
```bash
export GITHUB_STEP_SUMMARY=/tmp/summary.md
./scripts/github-policy-summary.sh artifacts/
cat /tmp/summary.md
```

---

## Resources

- **Conftest Docs:** https://www.conftest.dev/
- **OPA Playground:** https://play.openpolicyagent.org/
- **jq Manual:** https://jqlang.github.io/jq/manual/
- **GitHub Actions Annotations:** https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions
