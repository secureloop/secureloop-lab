# SSH Key Resource
resource "hcloud_ssh_key" "lab_key" {
  name       = "supply-chain-lab-key"
  public_key = var.ssh_public_key
}

# Main Server
resource "hcloud_server" "lab" {
  name        = var.server_name
  server_type = var.server_type
  image       = "ubuntu-24.04"
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.lab_key.id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    ssh_public_key = var.ssh_public_key
  })

  labels = {
    project     = "supply-chain-security-lab"
    environment = "demo"
    managed_by  = "terraform"
  }

  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}

# Firewall
resource "hcloud_firewall" "lab_firewall" {
  name = "supply-chain-lab-firewall"
  
  # SSH
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # HTTP
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # HTTPS
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # Nexus
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "8081"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # Grafana
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "3000"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # Prometheus
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "9090"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # Trivy
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "9000"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
  
  # Demo Apps (8080-8083)
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "8080-8083"
    source_ips = [
      "0.0.0.0/0",
      "::/0"
    ]
  }
}

# Attach Firewall to Server
resource "hcloud_firewall_attachment" "lab_firewall_attachment" {
  firewall_id = hcloud_firewall.lab_firewall.id
  server_ids  = [hcloud_server.lab.id]
}
