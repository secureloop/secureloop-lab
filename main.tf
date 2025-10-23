terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_ssh_key" "tonit" {
  name       = "secureloop-tonit-key"
  public_key = file(var.ssh_public_key_path)

  labels = {
    managed_by = "terraform"
  }
}

resource "hcloud_server" "debian_vm" {
  name        = var.server_name
  server_type = var.server_type
  location    = var.location
  image       = "debian-13"

  ssh_keys = [hcloud_ssh_key.tonit.id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    ssh_public_key = trimspace(file(var.ssh_public_key_path))
  })

  labels = {
    managed_by = "terraform"
  }
}
