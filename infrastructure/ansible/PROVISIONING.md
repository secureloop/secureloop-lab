# GitLab Provisioning Guide

This guide explains how to automate GitLab user onboarding and project imports using Ansible.

## Overview

The `provision-gitlab.yml` playbook automates:
- **User creation** - Automatically onboard users to GitLab
- **Project creation** - Create new empty projects
- **Project imports** - Import existing Git repositories from external sources (GitHub, Bitbucket, etc.)

**Security:** Secrets (API tokens, passwords) are encrypted using Ansible Vault. See [VAULT.md](VAULT.md) for details.

## Prerequisites

1. **GitLab is deployed and running**
   ```bash
   # Deploy GitLab first if not already done
   ansible-playbook install-gitlab_servers.yml
   ```

2. **GitLab API access token**
   - You need an admin-level API token to create users and projects

## Getting the API Token

### Method 1: Use Root Password (Initial Setup)

```bash
# Get the initial root password
ssh tonit@YOUR_SERVER_IP 'sudo docker exec gitlab cat /etc/gitlab/initial_root_password'

# Login to GitLab as root with this password
# Then create an API token
```

### Method 2: Create API Token via GitLab UI

1. Login to GitLab: `https://gitlab.secureloop.de`
2. Go to **User Settings** → **Access Tokens**
3. Create a new token with scopes:
   - `api` - Full API access
   - `read_api` - Read API
   - `write_repository` - Write to repository
4. Copy the token (you won't see it again!)

### Method 3: Create via GitLab Rails Console

```bash
ssh tonit@YOUR_SERVER_IP
sudo docker exec -it gitlab gitlab-rails console

# In the Rails console:
user = User.find_by(username: 'root')
token = user.personal_access_tokens.create(scopes: ['api'], name: 'Ansible Automation', expires_at: 365.days.from_now)
token.set_token('your-custom-token-here')  # Optional: set custom token
token.save!
puts token.token
exit
```

## Configuration

### 1. Setup Ansible Vault (for secrets)

```bash
cd ansible

# The vault file is already created and encrypted
# To view/edit the encrypted secrets:
ansible-vault edit group_vars/vault.yml

# Or if you need to create it from scratch:
cp group_vars/vault.yml.example group_vars/vault.yml
ansible-vault encrypt group_vars/vault.yml
```

Add your API token to `vault.yml`:
```yaml
---
vault_gitlab_api_token: "glpat-your-actual-token-here"
```

**Note:** The vault password is stored in `.vault_pass` (not committed to git). See [VAULT.md](VAULT.md) for full vault documentation.

### 2. Create provisioning configuration

```bash
cp group_vars/provisioning.yml.example group_vars/provisioning.yml
```

### 3. Edit `group_vars/provisioning.yml`

```yaml
---
# GitLab API Token (references encrypted vault)
gitlab_api_token: "{{ vault_gitlab_api_token }}"

# Users to create
gitlab_users:
  - username: "developer1"
    email: "dev1@secureloop.de"
    name: "Developer One"
    password: "SecurePassword123!"
    admin: false

  - username: "admin1"
    email: "admin@secureloop.de"
    name: "Admin User"
    password: "AdminPassword456!"
    admin: true

# Projects to create or import
gitlab_projects:
  # New empty project
  - name: "infrastructure"
    description: "Infrastructure as Code"
    visibility: "private"
    initialize_with_readme: true

  # Import from GitHub
  - name: "backend-api"
    description: "Backend API Service"
    import_url: "https://github.com/your-org/backend-api.git"
    visibility: "private"

  # Import from private repository (with token)
  - name: "frontend"
    description: "Frontend Application"
    import_url: "https://oauth2:ghp_yourGitHubToken@github.com/your-org/frontend.git"
    visibility: "private"
```

### 3. Configure visibility options

Projects can have three visibility levels:
- `private` - Only project members can access
- `internal` - Logged-in users can access
- `public` - Anyone can access

## Running the Provisioning Playbook

### Basic Usage

```bash
cd ansible
ansible-playbook -i inventory/hosts.ini provision-gitlab_servers.yml
```

### Using dynamic inventory

```bash
export SERVER_IP=$(cd .. && terraform output -raw server_ip)
ansible-playbook -i "${SERVER_IP}," provision-gitlab_servers.yml
```

### Dry Run (Check Mode)

```bash
# Not supported - API calls can't be in check mode
# Instead, review the provisioning.yml file carefully before running
```

## Importing Projects

### Import from Public Repository

```yaml
gitlab_projects:
  - name: "open-source-project"
    import_url: "https://github.com/user/repo.git"
    visibility: "private"
```

### Import from Private GitHub Repository

Create a GitHub Personal Access Token first:
1. GitHub → Settings → Developer settings → Personal access tokens
2. Generate new token with `repo` scope
3. Use in import URL:

```yaml
gitlab_projects:
  - name: "private-repo"
    import_url: "https://oauth2:ghp_YOUR_TOKEN@github.com/user/private-repo.git"
    visibility: "private"
```

### Import from Private GitLab Repository

```yaml
gitlab_projects:
  - name: "gitlab-import"
    import_url: "https://oauth2:glpat-YOUR_TOKEN@gitlab.com/user/repo.git"
    visibility: "private"
```

### Import from Bitbucket

```yaml
gitlab_projects:
  - name: "bitbucket-import"
    import_url: "https://username:app-password@bitbucket.org/user/repo.git"
    visibility: "private"
```

## User Management

### Create Regular Users

```yaml
gitlab_users:
  - username: "john.doe"
    email: "john@example.com"
    name: "John Doe"
    password: "TempPassword123!"
    admin: false
```

### Create Admin Users

```yaml
gitlab_users:
  - username: "admin"
    email: "admin@example.com"
    name: "Administrator"
    password: "AdminPass456!"
    admin: true
```

### Password Requirements

Default GitLab password requirements:
- Minimum 8 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one number

**Security Note:** Users should change their password on first login. Consider using:
- Strong generated passwords
- Password management tools
- SSO/LDAP integration for production

## Advanced Usage

### Only Create Users (Skip Projects)

Remove or comment out `gitlab_projects` in `provisioning.yml`:

```yaml
# gitlab_projects: []  # No projects
```

### Only Import Projects (Skip Users)

Remove or comment out `gitlab_users` in `provisioning.yml`:

```yaml
# gitlab_users: []  # No users
```

### Import Multiple Projects from Same Source

```yaml
gitlab_projects:
  - name: "project-1"
    import_url: "https://github.com/org/project-1.git"
  - name: "project-2"
    import_url: "https://github.com/org/project-2.git"
  - name: "project-3"
    import_url: "https://github.com/org/project-3.git"
```

## Idempotency

The playbook is idempotent:
- **Users**: If a user already exists, it will be skipped (409 status)
- **Projects**: If a project already exists, it will be skipped (400 status)

You can safely run the playbook multiple times.

## Troubleshooting

### API Token Issues

```
Error: 401 Unauthorized
```

**Solution:**
- Verify your `gitlab_api_token` is correct
- Ensure the token has `api` scope
- Check if the token has expired

### User Already Exists

```
Status: 409 - User already exists
```

**Solution:** This is normal - the user was already created. The playbook skips existing users.

### Project Import Failed

```
Status: 400 - Bad Request
```

**Possible causes:**
- Project name already exists
- Invalid import URL
- Authentication required for private repository
- Repository doesn't exist

**Solution:**
- Check if project exists in GitLab
- Verify the import URL is correct
- Add authentication token to URL for private repos

### SSL Certificate Issues

```
Error: SSL verification failed
```

**Solution:** The playbook uses `validate_certs: false` for self-signed certificates. If you have a valid certificate and want to verify, edit `provision-gitlab.yml` and change to `validate_certs: true`.

## GitLab API Reference

- **API Documentation**: https://docs.gitlab.com/ee/api/
- **Users API**: https://docs.gitlab.com/ee/api/users.html
- **Projects API**: https://docs.gitlab.com/ee/api/projects.html
- **Import API**: https://docs.gitlab.com/ee/api/import.html

## Security Best Practices

1. **Protect API Token**
   - Never commit `provisioning.yml` with real token to git
   - Use environment variables in CI/CD
   - Rotate tokens regularly

2. **Use Strong Passwords**
   - Generate random passwords
   - Force users to change on first login
   - Consider SSO/LDAP for production

3. **Limit Token Scopes**
   - Only grant necessary API scopes
   - Use separate tokens for different automation tasks
   - Set expiration dates

4. **Audit Access**
   - Review created users regularly
   - Monitor API usage
   - Check project permissions

## Example Workflows

### Onboard New Team

```bash
# 1. Edit provisioning.yml with team members
# 2. Run provisioning
ansible-playbook -i inventory/hosts.ini provision-gitlab_servers.yml

# 3. Notify users of their accounts
# 4. Have them change passwords on first login
```

### Migrate from GitHub to GitLab

```bash
# 1. Create GitHub Personal Access Token
# 2. Add all repositories to provisioning.yml
# 3. Run import
ansible-playbook -i inventory/hosts.ini provision-gitlab_servers.yml

# 4. Verify all projects imported successfully
# 5. Update Git remotes in local repositories
```

## Next Steps

After provisioning:
1. Configure project permissions and access levels
2. Set up CI/CD pipelines
3. Configure branch protection rules
4. Set up GitLab runners
5. Configure webhooks and integrations
