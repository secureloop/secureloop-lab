output "server_ip" {
  description = "Public IPv4 address of the server"
  value       = hcloud_server.lab.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6 address of the server"
  value       = hcloud_server.lab.ipv6_address
}

output "server_name" {
  description = "Server hostname"
  value       = hcloud_server.lab.name
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh root@${hcloud_server.lab.ipv4_address}"
}

output "nexus_url" {
  description = "Nexus Repository Manager URL"
  value       = "http://${hcloud_server.lab.ipv4_address}:8081"
}

output "grafana_url" {
  description = "Grafana Dashboard URL"
  value       = "http://${hcloud_server.lab.ipv4_address}:3000"
}

output "prometheus_url" {
  description = "Prometheus URL"
  value       = "http://${hcloud_server.lab.ipv4_address}:9090"
}
