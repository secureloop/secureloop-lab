# Policy Validation with Open Policy Agent

This directory contains OPA/Rego policies for validating build artifacts, security posture, and compliance in the CI/CD pipeline.

## Overview

Policies are enforced using [Conftest](https://www.conftest.dev/), a tool built on Open Policy Agent (OPA) designed for testing configuration files.

## Current Policies

### 1. SBOM License Compliance (`sbom/validation.rego`)

**Purpose:** Validates CycloneDX SBOM for license compliance and completeness

**Checks:**
- ✓ SBOM is in valid CycloneDX format with spec version
- ✓ No prohibited licenses (GPL, AGPL, SSPL)
- ✓ All components have license information
- ✓ Components have minimum required metadata (name, version)
- ✓ SBOM is complete (contains at least 5 components)
- ✓ No vulnerable versions of known libraries (log4j)

**Mode:** Warning only (does not fail build)

### 2. Docker Image Security (`docker/image.rego`)

**Purpose:** Validates Docker images meet security and operational standards

**Checks:**
- ✓ Image runs as non-root user
- ✓ Image tag is not 'latest'
- ✓ Image defines healthcheck
- ✓ Required OCI labels present (version, source, revision)
- ✓ Base image is from approved source (eclipse-temurin)
- ✓ No secrets in environment variables
- ✓ Exposed ports are documented

**Mode:** Warning only (does not fail build)

### 3. Maven POM Standards (`maven/pom.rego`)

**Purpose:** Validates Maven pom.xml follows organizational build standards

**Checks:**
- ✓ Version follows semantic versioning (X.Y.Z or X.Y.Z-SNAPSHOT)
- ✓ No SNAPSHOT versions on main/master branch
- ✓ GroupId matches organization (de.secureloop)
- ✓ Java version is 21
- ✓ Required plugins are present (spring-boot, cyclonedx)
- ✓ Spring Boot version is current (3.x or 4.x)
- ✓ License information is present
- ✓ Project has description

**Mode:** Warning only (does not fail build)

## Testing Policies Locally

### Run All Tests

```bash
# From repository root
opa test policies/ -v
```

### Test Specific Policy

```bash
# Test SBOM policy
opa test policies/sbom/ -v

# Test Docker policy
opa test policies/docker/ -v

# Test Maven policy
opa test policies/maven/ -v
```

### Validate Against Real Artifacts

```bash
# Install Conftest
brew install conftest  # macOS
# OR
wget https://github.com/open-policy-agent/conftest/releases/download/v0.49.1/conftest_0.49.1_Linux_x86_64.tar.gz
tar xzf conftest_0.49.1_Linux_x86_64.tar.gz
sudo mv conftest /usr/local/bin/

# Test SBOM
conftest test --policy policies/sbom/ demo-apps/java-spring/target/bom.json

# Test Docker image (must export metadata first)
docker inspect <image:tag> > docker-metadata.json
conftest test --policy policies/docker/ docker-metadata.json

# Test Maven POM (must convert to JSON first)
yq eval -o=json demo-apps/java-spring/pom.xml > pom.json
echo '{"project": ... }' | conftest test --policy policies/maven/ -
```

## CI/CD Integration

Policies are automatically validated in the `policy` job of the GitHub Actions workflow (`.github/workflows/build-java.yml`).

**Current Behavior:**
- Policies run in **warning mode** (`--fail-on-warn=false`)
- Policy violations are reported but **do not fail the build**
- Results are uploaded as artifacts for review

**To View Policy Results:**
1. Go to GitHub Actions → Workflow run
2. Click on "policy" job
3. Review console output for warnings
4. Download "policy-validation-results" artifact for details

## Transitioning from Warnings to Enforcement

When ready to enforce policies (fail build on violations):

### Option 1: Enforce Specific Policies

Edit `.github/workflows/build-java.yml` and remove `continue-on-error: true` for specific policy steps:

```yaml
- name: Validate SBOM Policy
  # Remove: continue-on-error: true
  run: |
    conftest test \
      --policy policies/sbom/ \
      --namespace sbom \
      artifacts/bom.json  # Now fails on violations
```

### Option 2: Use deny[] Instead of warn[]

Change policy rules from `warn[msg]` to `deny[msg]` in Rego files:

```rego
# Before (warning)
warn[msg] {
    not input.Config.User
    msg := "Image must run as non-root user"
}

# After (blocking)
deny[msg] {
    not input.Config.User
    msg := "Image must run as non-root user"
}
```

### Option 3: Enable --fail-on-warn

Change Conftest flag to fail on warnings:

```bash
conftest test --policy policies/sbom/ --fail-on-warn=true artifacts/bom.json
```

## Policy Development

### Adding a New Policy

1. **Create policy file:**
   ```bash
   mkdir -p policies/mynewpolicy
   touch policies/mynewpolicy/validation.rego
   ```

2. **Write policy in Rego:**
   ```rego
   package mynewpolicy

   warn[msg] {
       # Your policy logic here
       msg := "Policy violation message"
   }
   ```

3. **Create test file:**
   ```bash
   touch policies/mynewpolicy/validation_test.rego
   ```

4. **Write tests:**
   ```rego
   package mynewpolicy_test

   import data.mynewpolicy
   import future.keywords.if

   test_valid_input if {
       input := { ... }
       count(mynewpolicy.warn) == 0
   }
   ```

5. **Test policy:**
   ```bash
   opa test policies/mynewpolicy/ -v
   ```

6. **Add to CI/CD workflow:**
   ```yaml
   - name: Validate My New Policy
     continue-on-error: true
     run: |
       conftest test \
         --policy policies/mynewpolicy/ \
         --namespace mynewpolicy \
         artifacts/mydata.json
   ```

## Resources

- **OPA Documentation:** https://www.openpolicyagent.org/docs/latest/
- **Rego Language Guide:** https://www.openpolicyagent.org/docs/latest/policy-language/
- **Conftest Documentation:** https://www.conftest.dev/
- **OPA Playground:** https://play.openpolicyagent.org/ (test Rego policies online)
- **Policy Examples:** https://github.com/open-policy-agent/conftest/tree/master/examples

## Policy Maintenance

### Regular Updates

- Review and update prohibited licenses list
- Update base image requirements as standards evolve
- Adjust vulnerability thresholds based on organizational risk tolerance
- Add new policies as compliance requirements change

### Policy Versioning

Policies are versioned with the repository. Use Git tags to mark policy releases:

```bash
git tag policy-v1.0.0
git push --tags
```

### Getting Help

- **Policy Questions:** Open an issue in the repository
- **OPA/Rego Help:** Join OPA Slack (https://slack.openpolicyagent.org/)
- **Conftest Issues:** https://github.com/open-policy-agent/conftest/issues

## Current Status

🟡 **Warning Mode** - Policies report violations but do not block builds

**Next Steps:**
1. Review policy violations in pipeline runs
2. Fix identified issues
3. Establish baseline compliance
4. Transition to enforcement mode (fail builds on violations)
