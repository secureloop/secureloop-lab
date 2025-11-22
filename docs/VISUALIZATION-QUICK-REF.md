# OPA Visualization Quick Reference

## 🎯 Best Methods

### 1. Table Format (Daily Development)

**Clean, readable tables in your terminal**

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

---

### 2. JSON + jq (For Statistics)

**Get summary statistics**

```bash
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  --output json \
  demo-apps/java-spring/target/bom.json | \
jq '{
  file: .[0].filename,
  successes: .[0].successes,
  warnings: (.[0].warnings | length),
  failures: (.[0].failures | length),
  status: (
    if (.[0].failures | length) > 0 then "FAILED"
    elif (.[0].warnings | length) > 0 then "WARNING"
    else "PASSED"
    end
  )
}'
```

**List all warnings**

```bash
conftest test --output json ... | jq -r '.[].warnings[]?.msg'
```

---

### 3. Colored Summary (Quick Check)

**Just the summary line**

```bash
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  demo-apps/java-spring/target/bom.json
```

Output: `8 tests, 8 passed, 0 warnings, 0 failures, 0 exceptions`

---

## 📊 Complete Test Script

Save this as `test-policies.sh`:

```bash
#!/bin/bash
set -euo pipefail

echo "🔍 Testing OPA Policies"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test SBOM
echo "📋 SBOM License Compliance:"
conftest test \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  --output table \
  demo-apps/java-spring/target/bom.json

echo ""

# Test Docker
echo "🐳 Docker Image Security:"
docker inspect java-spring-lab:test > /tmp/docker.json
conftest test \
  --policy policies/docker/image.rego \
  --namespace docker \
  --output table \
  /tmp/docker.json

echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Get stats
SBOM_STATS=$(conftest test --policy policies/sbom/validation.rego --namespace sbom --output json demo-apps/java-spring/target/bom.json)
DOCKER_STATS=$(conftest test --policy policies/docker/image.rego --namespace docker --output json /tmp/docker.json)

TOTAL_WARNINGS=$(($(echo "$SBOM_STATS" | jq '.[].warnings | length') + $(echo "$DOCKER_STATS" | jq '.[].warnings | length')))
TOTAL_FAILURES=$(($(echo "$SBOM_STATS" | jq '.[].failures | length') + $(echo "$DOCKER_STATS" | jq '.[].failures | length')))

if [ "$TOTAL_FAILURES" -gt 0 ]; then
    echo -e "Status: ${RED}❌ FAILED${NC} ($TOTAL_FAILURES failures)"
    exit 1
elif [ "$TOTAL_WARNINGS" -gt 0 ]; then
    echo -e "Status: ${YELLOW}⚠️  WARNING${NC} ($TOTAL_WARNINGS warnings)"
else
    echo -e "Status: ${GREEN}✅ PASSED${NC}"
fi
```

---

## 🚀 One-Liners

### Quick Status Check

```bash
conftest test --policy policies/sbom/validation.rego --namespace sbom demo-apps/java-spring/target/bom.json && echo "✅ SBOM PASSED" || echo "❌ SBOM FAILED"
```

### Count Warnings

```bash
conftest test --output json --policy policies/docker/image.rego --namespace docker /tmp/docker.json | jq '.[].warnings | length'
```

### List Failure Messages

```bash
conftest test --output json --policy policies/sbom/validation.rego --namespace sbom demo-apps/java-spring/target/bom.json | jq -r '.[].failures[]?.msg'
```

### Pretty Print All Results

```bash
conftest test --output json --policy policies/sbom/validation.rego --namespace sbom demo-apps/java-spring/target/bom.json | jq -C '.' | less -R
```

---

## 🎨 Format Comparison

| Format | Command Flag | Best For |
|--------|--------------|----------|
| Table | `--output table` | Terminal viewing |
| JSON | `--output json` | Automation, parsing |
| Stdout | (default) | Quick checks |
| JUnit | `--output junit` | CI integration |
| GitHub | `--output github` | GitHub Actions |

---

## 💡 Pro Tips

### 1. Alias for Quick Testing

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
alias test-sbom='conftest test --policy policies/sbom/validation.rego --namespace sbom --output table demo-apps/java-spring/target/bom.json'
alias test-docker='docker inspect java-spring-lab:test > /tmp/d.json && conftest test --policy policies/docker/image.rego --namespace docker --output table /tmp/d.json'
```

Usage:
```bash
test-sbom
test-docker
```

### 2. Watch Mode

Continuously test as you make changes:

```bash
watch -n 5 'conftest test --policy policies/sbom/validation.rego --namespace sbom demo-apps/java-spring/target/bom.json'
```

### 3. Save Results

```bash
conftest test \
  --output json \
  --policy policies/sbom/validation.rego \
  --namespace sbom \
  demo-apps/java-spring/target/bom.json \
  > results-$(date +%Y%m%d-%H%M%S).json
```

---

## 📈 Your Current Results

**SBOM:** ✅ 8 tests, 8 passed, 0 warnings, 0 failures
**Docker:** ⚠️  10 tests, 6 passed, 4 warnings, 0 failures

**Docker Warnings:**
1. Image must define a healthcheck
2. Image must run as non-root user
3. Image should explicitly EXPOSE ports
4. Image should have OCI labels defined
