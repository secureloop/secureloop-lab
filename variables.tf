variable "hcloud_token" {
  description = "Hetzner Cloud API Token"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Name of the server"
  type        = string
  default     = "debian-vm"
}

variable "server_type" {
  description = "Server type (cx11, cx21, etc.)"
  type        = string
  default     = "cx11"
}

variable "location" {
  description = "Server location (nbg1, fsn1, hel1, etc.)"
  type        = string
  default     = "nbg1"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key file"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}
