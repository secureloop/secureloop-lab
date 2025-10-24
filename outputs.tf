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

output "ansible_inventory" {
  description = "Ansible inventory entry for this server"
  value       = "${hcloud_server.debian_vm.name} ansible_host=${hcloud_server.debian_vm.ipv4_address}"
}

output "ansible_deploy_command" {
  description = "Command to deploy GitLab with Ansible"
  value       = "cd ansible && ansible-playbook -i '${hcloud_server.debian_vm.ipv4_address},' playbook.yml"
}
