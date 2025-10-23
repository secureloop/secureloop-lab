output "server_ip" {
  description = "Public IP address of the server"
  value       = hcloud_server.debian_vm.ipv4_address
}

output "server_name" {
  description = "Name of the server"
  value       = hcloud_server.debian_vm.name
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh tonit@${hcloud_server.debian_vm.ipv4_address}"
}
