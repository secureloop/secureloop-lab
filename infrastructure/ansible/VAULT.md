# Ansible Vault Guide

This guide explains how to use Ansible Vault to secure sensitive data like API tokens and passwords.

## Overview

We use Ansible Vault to encrypt secrets in a separate `vault.yml` file, keeping them separate from regular configuration.

## File Structure

- `group_vars/vault.yml` - **Encrypted** secrets (API tokens, passwords)
- `group_vars/provisioning.yml` - Regular config that references vault variables

## Initial Setup

### 1. Create the vault file

```bash
cd ansible
cp group_vars/vault.yml.example group_vars/vault.yml
```

### 2. Edit with your actual secrets

```bash
# Edit the file BEFORE encrypting
nano group_vars/vault.yml
```

Add your secrets:
```yaml
---
vault_gitlab_api_token: "glpat-your-actual-token-here"
```

### 3. Encrypt the vault file

```bash
ansible-vault encrypt group_vars/vault.yml
```

You'll be prompted to create a vault password. **Remember this password!**

Output:
```
New Vault password:
Confirm New Vault password:
Encryption successful
```

The file is now encrypted and safe to commit to git (though we've added it to `.gitignore`).

## Working with Encrypted Files

### View encrypted file content

```bash
ansible-vault view group_vars/vault.yml
```

### Edit encrypted file

```bash
ansible-vault edit group_vars/vault.yml
```

This opens the file in your default editor (decrypted temporarily).

### Decrypt file (not recommended)

```bash
ansible-vault decrypt group_vars/vault.yml
```

**Warning:** This removes encryption. Only do this if you want to remove vault encryption entirely.

### Re-encrypt after decrypting

```bash
ansible-vault encrypt group_vars/vault.yml
```

### Change vault password

```bash
ansible-vault rekey group_vars/vault.yml
```

## Running Playbooks with Vault

### Option 1: Interactive password prompt

```bash
ansible-playbook -i '188.245.182.211,' provision-gitlab.yml --ask-vault-pass
```

You'll be prompted for the vault password each time.

### Option 2: Password file (convenient but less secure)

Create a password file:
```bash
echo "your-vault-password" > .vault_pass
chmod 600 .vault_pass
```

Update `ansible.cfg`:
```ini
[defaults]
vault_password_file = ./.vault_pass
```

Then run without `--ask-vault-pass`:
```bash
ansible-playbook -i '188.245.182.211,' provision-gitlab.yml
```

**Note:** `.vault_pass` is in `.gitignore` to prevent committing it.

### Option 3: Environment variable

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass
ansible-playbook -i '188.245.182.211,' provision-gitlab.yml
```

## How It Works

### In provisioning.yml (unencrypted)

```yaml
---
# Reference the vault variable
gitlab_api_token: "{{ vault_gitlab_api_token }}"

gitlab_users:
  - username: "developer1"
    password: "{{ vault_user_passwords.developer1 }}"
```

### In vault.yml (encrypted)

```yaml
---
vault_gitlab_api_token: "glpat-secrettoken123"
vault_user_passwords:
  developer1: "SecurePass123!"
```

When the playbook runs, Ansible decrypts `vault.yml` in memory and substitutes the values.

## Best Practices

### 1. Naming Convention

Prefix vault variables with `vault_`:
- `vault_gitlab_api_token`
- `vault_db_password`
- `vault_ssh_key`

### 2. Separate Secrets from Config

**Good:**
```yaml
# provisioning.yml (unencrypted)
gitlab_hostname: "gitlab.secureloop.de"
gitlab_api_token: "{{ vault_gitlab_api_token }}"

# vault.yml (encrypted)
vault_gitlab_api_token: "glpat-secret"
```

**Bad:**
```yaml
# Everything in vault.yml (encrypted)
# Makes it hard to review config changes in git
vault_gitlab_hostname: "gitlab.secureloop.de"
vault_gitlab_api_token: "glpat-secret"
```

### 3. Don't Commit Vault Password

**Never** commit:
- `.vault_pass` (password file)
- Unencrypted `vault.yml`
- Passwords in documentation

### 4. Use Strong Vault Passwords

Generate a strong vault password:
```bash
openssl rand -base64 32
```

### 5. Rotate Secrets Regularly

1. Change the secret in GitLab/service
2. Edit vault file: `ansible-vault edit group_vars/vault.yml`
3. Update the secret value
4. Save and exit

## Multiple Vault Files

You can have multiple vault files for different environments:

```
group_vars/
├── vault_production.yml
├── vault_staging.yml
└── vault_development.yml
```

Load different files per environment:
```yaml
# provision-gitlab.yml
vars_files:
  - "group_vars/vault_{{ env }}.yml"
  - group_vars/provisioning.yml
```

Run with:
```bash
ansible-playbook provision-gitlab.yml -e "env=production" --ask-vault-pass
```

## Troubleshooting

### Error: Attempting to decrypt but no vault secrets found

**Problem:** The file isn't encrypted or the path is wrong.

**Solution:**
```bash
# Check if file is encrypted
head group_vars/vault.yml
# Should show: $ANSIBLE_VAULT;1.1;AES256

# Encrypt if needed
ansible-vault encrypt group_vars/vault.yml
```

### Error: Decryption failed

**Problem:** Wrong vault password.

**Solution:** Try the correct password or rekey the vault.

### ERROR! Unexpected Exception: vault_id must be a string

**Problem:** Old Ansible version.

**Solution:** Update Ansible:
```bash
brew upgrade ansible
# or
pip3 install --upgrade ansible
```

## CI/CD Integration

For automated deployments, store the vault password as a secret in your CI/CD system:

### GitHub Actions

```yaml
- name: Run Ansible playbook
  env:
    VAULT_PASSWORD: ${{ secrets.ANSIBLE_VAULT_PASSWORD }}
  run: |
    echo "$VAULT_PASSWORD" > .vault_pass
    ansible-playbook provision-gitlab.yml
```

### GitLab CI

```yaml
provision:
  script:
    - echo "$ANSIBLE_VAULT_PASSWORD" > .vault_pass
    - ansible-playbook provision-gitlab.yml
  variables:
    ANSIBLE_VAULT_PASSWORD: $VAULT_PASSWORD
```

## Quick Reference

```bash
# Encrypt
ansible-vault encrypt group_vars/vault.yml

# Decrypt (temporary)
ansible-vault decrypt group_vars/vault.yml

# View
ansible-vault view group_vars/vault.yml

# Edit
ansible-vault edit group_vars/vault.yml

# Change password
ansible-vault rekey group_vars/vault.yml

# Run playbook
ansible-playbook provision-gitlab.yml --ask-vault-pass

# With password file
ansible-playbook provision-gitlab.yml --vault-password-file .vault_pass
```

## Additional Resources

- [Ansible Vault Documentation](https://docs.ansible.com/ansible/latest/user_guide/vault.html)
- [Vault Best Practices](https://www.ansible.com/blog/2016/04/21/using-vault-in-playbooks)
