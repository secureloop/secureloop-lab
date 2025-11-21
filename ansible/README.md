# Ansible GitLab Deployment for Secureloop

This Ansible playbook deploys GitLab on a Hetzner Cloud VM provisioned by Terraform.

## Playbooks

- **`playbook.yml`** - Deploy and configure GitLab server
- **`provision-gitlab.yml`** - Provision users and import projects ([detailed guide](PROVISIONING.md))

## Architecture

- **Terraform**: Provisions infrastructure (VM, SSH keys, network)
- **Cloud-init**: Installs Docker and basic system setup
- **Ansible**: Deploys and manages GitLab application

## Prerequisites

1. **Terraform has created the VM**
   ```bash
   cd .. && terraform apply
   ```

2. **Ansible is installed locally**
   ```bash
   # macOS
   brew install ansible

   # Or via pip
   pip3 install ansible
   ```

3. **Ansible Docker collection**
   ```bash
   ansible-galaxy collection install community.docker
   ```

## Quick Start

### 1. Get the server IP from Terraform

```bash
export SERVER_IP=$(cd .. && terraform output -raw server_ip)
echo $SERVER_IP
```

### 2. Configure variables

```bash
# Copy the example configuration
cp group_vars/all.yml.example group_vars/all.yml

# Edit group_vars/all.yml and update:
# - gitlab_letsencrypt_email (your email)
# - Any other settings you want to customize
```

### 3. Create inventory file

```bash
cp inventory/hosts.ini.example inventory/hosts.ini
# Edit hosts.ini and replace YOUR_SERVER_IP with actual IP
```

Or use the dynamic method:
```bash
# Deploy directly without inventory file
cd ansible
ansible-playbook -i "${SERVER_IP}," playbook.yml
```

### 4. Run the playbook

```bash
# Using inventory file
ansible-playbook playbook.yml

# Or using Terraform output command directly
cd .. && terraform output -raw ansible_deploy_command | sh
```

## Configuration

Edit `group_vars/all.yml` to customize:

```yaml
gitlab_version: "18.5.2-ee.0"             # GitLab version
gitlab_hostname: "gitlab.secureloop.de"   # Your domain
gitlab_ssh_port: 2222                     # GitLab SSH port (not 22!)
gitlab_enable_letsencrypt: true           # Enable for automatic SSL
gitlab_letsencrypt_email: "your@email"    # Required if letsencrypt enabled
```

**Important:**
- Health check endpoints use IP whitelisting (localhost is automatically allowed)
- Never commit the actual `group_vars/all.yml` with real secrets to git
- Use the `.example` file as a template

## Post-Deployment

### 1. Wait for GitLab to start (2-5 minutes)

```bash
ssh tonit@${SERVER_IP} 'docker logs -f gitlab'
```

### 2. Get the initial root password

```bash
ssh tonit@${SERVER_IP} 'sudo docker exec -it gitlab grep "Password:" /etc/gitlab/initial_root_password'
```

### 3. Configure DNS

Point `gitlab.secureloop.de` to your server IP:
- Create an A record: `gitlab.secureloop.de` → `YOUR_SERVER_IP`

### 4. Access GitLab

- **URL**: https://gitlab.secureloop.de (or http://YOUR_SERVER_IP)
- **Username**: `root`
- **Password**: (from step 2)

### 5. Configure GitLab SSH (optional)

For Git operations via SSH on port 2222:
```bash
# In your ~/.ssh/config
Host gitlab.secureloop.de
    Port 2222
    User git
```

Then you can clone with:
```bash
git clone git@gitlab.secureloop.de:user/repo.git
```

## SSL/HTTPS Setup

### Option 1: Let's Encrypt (Recommended)

Edit `group_vars/all.yml`:
```yaml
gitlab_enable_letsencrypt: true
gitlab_letsencrypt_email: "admin@secureloop.de"
```

Then re-run the playbook:
```bash
ansible-playbook playbook.yml
```

### Option 2: Manual Certificates

Place certificates in `/opt/gitlab/config/ssl/` on the server and configure in GitLab.

## Maintenance

### Update GitLab version

1. Edit `group_vars/all.yml` and change `gitlab_version`
2. Run the playbook: `ansible-playbook playbook.yml`
3. GitLab will restart with the new version

### Restart GitLab

```bash
ssh tonit@${SERVER_IP} 'cd /opt/gitlab && docker-compose restart'
```

### View GitLab logs

```bash
ssh tonit@${SERVER_IP} 'docker logs -f gitlab'
```

### Backup GitLab

```bash
ssh tonit@${SERVER_IP} 'docker exec -t gitlab gitlab-backup create'
```

Backups are stored in `/opt/gitlab/data/backups/`

## Troubleshooting

### GitLab not accessible

```bash
# Check if container is running
ssh tonit@${SERVER_IP} 'docker ps'

# Check GitLab health
ssh tonit@${SERVER_IP} 'docker exec gitlab gitlab-ctl status'

# View logs
ssh tonit@${SERVER_IP} 'docker logs gitlab'
```

### Port conflicts

- Server SSH: Port 22 (for system access)
- GitLab SSH: Port 2222 (for Git operations)
- GitLab HTTP: Port 80
- GitLab HTTPS: Port 443

### DNS not resolving

Verify DNS propagation:
```bash
dig gitlab.secureloop.de
nslookup gitlab.secureloop.de
```

## GitLab Provisioning (Users & Projects)

After deploying GitLab, you can automate user onboarding and project imports.

### Quick Start

```bash
# 1. Create provisioning config
cp group_vars/provisioning.yml.example group_vars/provisioning.yml

# 2. Get GitLab API token
ssh tonit@${SERVER_IP} 'sudo docker exec gitlab cat /etc/gitlab/initial_root_password'
# Login to GitLab and create an API token: User Settings -> Access Tokens

# 3. Edit provisioning.yml with your API token, users, and projects

# 4. Run provisioning
ansible-playbook -i inventory/hosts.ini provision-gitlab.yml
```

**See [PROVISIONING.md](PROVISIONING.md) for detailed documentation**, including:
- Creating users
- Importing projects from GitHub/GitLab/Bitbucket
- Authentication for private repositories
- Troubleshooting guide

## Project Structure

```
ansible/
├── ansible.cfg                          # Ansible configuration
├── playbook.yml                         # Main deployment playbook
├── provision-gitlab.yml                 # User/project provisioning
├── PROVISIONING.md                      # Provisioning documentation
├── inventory/
│   └── hosts.ini.example               # Inventory template
├── group_vars/
│   ├── all.yml                         # Deployment variables
│   └── provisioning.yml                # Provisioning variables
└── roles/
    └── gitlab/
        ├── tasks/main.yml              # Deployment tasks
        ├── templates/
        │   └── docker-compose.yml.j2   # GitLab compose template
        └── handlers/main.yml           # Service handlers
```

## Additional Resources

- [GitLab Docker Installation](https://docs.gitlab.com/ee/install/docker.html)
- [GitLab Configuration](https://docs.gitlab.com/omnibus/settings/)
- [Ansible Documentation](https://docs.ansible.com/)
