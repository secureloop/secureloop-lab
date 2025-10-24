# Ansible GitLab Deployment for Secureloop

This Ansible playbook deploys GitLab CE on a Hetzner Cloud VM provisioned by Terraform.

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

### 2. Create inventory file

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

### 3. Run the playbook

```bash
# Using inventory file
ansible-playbook playbook.yml

# Or using Terraform output command directly
cd .. && terraform output -raw ansible_deploy_command | sh
```

## Configuration

Edit `group_vars/all.yml` to customize:

```yaml
gitlab_version: "18.3.5-ce.0"          # GitLab version
gitlab_hostname: "gitlab.secureloop.de"  # Your domain
gitlab_ssh_port: 2222                   # GitLab SSH port (not 22!)
gitlab_enable_letsencrypt: false        # Enable for automatic SSL
gitlab_letsencrypt_email: "your@email"  # Required if letsencrypt enabled
```

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

## Project Structure

```
ansible/
├── ansible.cfg                          # Ansible configuration
├── playbook.yml                         # Main playbook
├── inventory/
│   └── hosts.ini.example               # Inventory template
├── group_vars/
│   └── all.yml                         # Variables
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
