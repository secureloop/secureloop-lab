terraform {
  required_version = ">= 1.0"
  
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

variable "hcloud_token" {
  description = "Hetzner Cloud API Token"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Your SSH public key"
  type        = string
}

variable "server_name" {
  description = "Server name"
  type        = string
  default     = "lab-supply-chain"
}

variable "server_type" {
  description = "Server type"
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Server location"
  type        = string
  default     = "fsn1"  # Falkenstein
}
