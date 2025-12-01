# SECURELOOP Lab - Claude Context

## Project Overview

**SECURELOOP Lab** is a production-ready demonstration of the SECURELOOP Framework for Software Supply Chain Security. This is a hands-on implementation for learning supply chain security through practical application.

### Key Objectives
- Demonstrate secure software supply chain practices
- Implement SBOM generation and vulnerability scanning
- Enforce security policies with OPA/Conftest
- Provide infrastructure-as-code examples
- Show end-to-end CI/CD pipeline security

### Tech Stack
- **Languages**: Java 21 (Spring Boot 4.0), Go, Node.js, Python (planned)
- **Build Tools**: Maven, Docker
- **Security Tools**: Trivy (vulnerability scanning), CycloneDX (SBOM), Cosign (signing)
- **Policy Enforcement**: OPA/Conftest
- **Infrastructure**: Terraform, Ansible, Docker Compose
- **CI/CD**: GitLab CI, GitHub Actions
- **Deployment**: Hetzner Cloud (CX41 server, ~€15.50/month)

## Repository Structure

```
secureloop-lab/
├── demo-apps/          # Demonstration applications with intentional vulnerabilities
│   └── java-spring/    # Spring Boot 4.0 demo app (Java 21)
│       ├── src/        # Application source code
│       ├── pom.xml     # Maven project configuration
│       ├── Dockerfile  # Container image definition
│       └── mvnw        # Maven wrapper
├── policies/           # OPA/Rego policy definitions
│   ├── sbom/          # SBOM validation policies (license compliance)
│   ├── docker/        # Docker image security policies
│   └── maven/         # Maven POM standards policies
├── infrastructure/     # Infrastructure-as-Code
│   ├── ansible/       # Ansible playbooks for provisioning
│   ├── terraform/     # Terraform configurations
│   └── terraform-gitlab/ # GitLab-specific Terraform setup
├── scripts/           # Automation and utility scripts
│   ├── github-policy-summary.sh   # Policy results summary
│   └── visualize-policies.sh      # Policy visualization
├── docs/              # Documentation
├── .gitlab-ci.yml     # GitLab CI/CD pipeline
└── .github/           # GitHub Actions workflows
```

## Key Components

### 1. Demo Applications

#### Java Spring Application
- **Location**: `demo-apps/java-spring/`
- **Framework**: Spring Boot 4.0
- **Java Version**: 21
- **Build Tool**: Maven (with wrapper)
- **Features**:
  - Spring Security enabled
  - Actuator endpoints for monitoring
  - Automatic SBOM generation (CycloneDX)
  - Docker containerization
  - Intentional vulnerabilities for testing

**Key Files**:
- `pom.xml` - Maven configuration with CycloneDX plugin
- `Dockerfile` - Multi-stage build for container image
- `src/main/java/de/secureloop/demo/SpringDemoApplication.java` - Main application

### 2. Policy Enforcement (OPA/Conftest)

All policies are currently in **warning mode** (violations don't fail builds).

#### SBOM Policy (`policies/sbom/validation.rego`)
Validates CycloneDX SBOM for:
- Valid CycloneDX format
- License compliance (no GPL, AGPL, SSPL)
- Component metadata completeness
- Known vulnerable versions (e.g., log4j)

#### Docker Image Policy (`policies/docker/image.rego`)
Validates Docker images for:
- Non-root user execution
- No 'latest' tags
- Health check definitions
- Required OCI labels
- Approved base images (eclipse-temurin)
- No secrets in environment variables

#### Maven POM Policy (`policies/maven/pom.rego`)
Validates Maven configurations for:
- Semantic versioning
- No SNAPSHOT on main/master branches
- Correct groupId (de.secureloop)
- Java 21 requirement
- Required plugins (spring-boot, cyclonedx)
- License information

### 3. CI/CD Pipelines

#### GitLab CI (`.gitlab-ci.yml`)
Three-stage pipeline for Java application:
1. **Test**: Run unit tests with JUnit reporting
2. **Build**: Create JAR artifacts (skip tests)
3. **Docker**: Build and push container images

**Key Features**:
- Maven dependency caching
- Docker-in-Docker service
- Multi-tag strategy (branch, commit SHA, latest)
- Runs on main, develop branches and manual triggers

#### GitHub Actions (`.github/workflows/build-java.yml`)
Includes additional policy validation steps using Conftest

### 4. Infrastructure

#### Terraform
- **Location**: `infrastructure/terraform/` and `infrastructure/terraform-gitlab/`
- **Target**: Hetzner Cloud
- **Resources**: VMs, networking, cloud-init configs

#### Ansible
- **Location**: `infrastructure/ansible/`
- **Playbooks**:
  - `deploy-lab.yml` - Deploy lab environment
  - `install-labdocker.yml` - Install Docker infrastructure
  - `install-gitlab.yml` - Install GitLab instance
  - `provision-gitlab.yml` - Configure GitLab

## Development Workflows

### Building Java Application

```bash
cd demo-apps/java-spring

# Run tests
./mvnw test

# Build JAR (generates SBOM)
./mvnw clean package

# Build Docker image
docker build -t secureloop-lab/java-spring:dev .

# Run locally
docker run -p 8080:8080 secureloop-lab/java-spring:dev
```

**Build Artifacts**:
- `target/spring-demo-0.0.1-SNAPSHOT.jar` - Application JAR
- `target/bom.json` - CycloneDX SBOM in JSON format

### Testing Policies Locally

```bash
# Test all policies
opa test policies/ -v

# Test specific policy
opa test policies/sbom/ -v

# Validate SBOM against policy
conftest test --policy policies/sbom/ demo-apps/java-spring/target/bom.json

# Validate Docker image
docker inspect <image:tag> > docker-metadata.json
conftest test --policy policies/docker/ docker-metadata.json
```

### Working with Scripts

```bash
# Visualize policy results
./scripts/visualize-policies.sh

# Generate policy summary for GitHub
./scripts/github-policy-summary.sh
```

## Security Scanning

### Trivy Integration
- Self-hosted Trivy server capability
- Documentation: `docs/README-trivy.md`
- Scans for vulnerabilities in:
  - Container images
  - Filesystem artifacts
  - SBOMs

## Common Tasks

### Adding New Demo Application
1. Create directory under `demo-apps/`
2. Add SBOM generation to build process
3. Create Dockerfile with security best practices
4. Add CI/CD pipeline stage
5. Create corresponding policy tests

### Adding New Policy
1. Create directory under `policies/`
2. Write Rego policy in `validation.rego`
3. Write tests in `validation_test.rego`
4. Test with `opa test policies/<policy-name>/ -v`
5. Add to CI/CD workflow
6. Document in `policies/README.md`

### Deploying Infrastructure
```bash
cd infrastructure/terraform
terraform init
terraform plan
terraform apply

cd ../ansible
ansible-playbook deploy-lab.yml
```

## Important Notes

### Policy Enforcement Status
- **Current**: All policies in WARNING mode
- **Violations**: Reported but don't fail builds
- **Transition**: Remove `continue-on-error: true` or change `warn[]` to `deny[]` in Rego files

### Git Workflow
- **Main Branch**: Production-ready code
- **Develop Branch**: Integration branch for features
- **CI Triggers**: main, develop branches + manual web triggers

### Development Branch
- Working on: `claude/update-claude-md-0186DEjVCnzbhxhLC8oXpaJf`
- All commits should go to this branch

## Dependencies and Versions

### Application Dependencies (Java)
- Spring Boot: 4.0.0
- Java: 21
- CycloneDX Maven Plugin: 2.8.2

### Infrastructure
- Docker: 29.0.2
- Trivy: 0.67.2
- Caddy: 2.10.2
- GitLab Runner: 18.6.1

### Policy Tools
- OPA: Latest
- Conftest: 0.49.1+

## Roadmap (TODO.md)

### Completed
- Infrastructure setup (Terraform, Ansible)
- Java Spring demo application
- CI/CD pipeline for Java
- Trivy integration
- Security scanning for Java

### In Progress / Planned
- Additional demo applications (Go, Node.js, Python)
- CI/CD pipelines for additional languages
- Policy enforcement for all languages
- Complete documentation
- OPA policy enforcement beyond warnings

## Resources

### Documentation Files
- `README.md` - Main project documentation
- `policies/README.md` - Policy validation guide
- `docs/POLICY-TESTING.md` - Policy testing procedures
- `docs/POLICY-VISUALIZATION.md` - Policy visualization
- `docs/WHY_NOW.md` - Context and rationale
- `infrastructure/terraform-gitlab/README-Gitlab.md` - GitLab setup
- `infrastructure/terraform-gitlab/VM.md` - VM configuration

### External References
- SECURELOOP Framework: https://github.com/secureloop-framework/secureloop
- OPA Documentation: https://www.openpolicyagent.org/docs/latest/
- Conftest: https://www.conftest.dev/
- CycloneDX: https://cyclonedx.org/
- Trivy: https://trivy.dev/

## Tips for Claude

### When Working with This Codebase
1. **Always check policies first** before making changes to build files
2. **Run OPA tests** after modifying policy files
3. **Generate SBOMs** after dependency changes
4. **Test Docker images** against policies before pushing
5. **Follow semantic versioning** for releases
6. **Don't commit to main directly** - use feature branches

### Common Pitfalls
- Don't use 'latest' Docker tags (fails policy)
- Ensure Docker images run as non-root (security policy)
- Always include license information in pom.xml
- Keep Java version at 21 (organizational standard)
- Include CycloneDX plugin in all Java projects

### File Patterns to Know
- `**/*.rego` - Policy definitions
- `**/*_test.rego` - Policy tests
- `**/pom.xml` - Maven configurations
- `**/Dockerfile` - Container definitions
- `**/*.yml` - CI/CD pipelines and Ansible playbooks
