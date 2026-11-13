output "address" {
  description = "Point your domain's A record at this."
  value       = aws_eip.server.public_ip
}

output "ssh" {
  description = "How to reach the server."
  value       = "ssh ubuntu@${aws_eip.server.public_ip}"
}
