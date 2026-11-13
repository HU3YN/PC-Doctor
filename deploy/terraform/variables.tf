variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-west-1"
}

variable "instance_type" {
  description = "Server size. t3.small (2 GB) is the least that runs k3s plus the app comfortably."
  type        = string
  default     = "t3.small"
}

variable "disk_gb" {
  description = "Disk size in GB: the system, the images, the database and the uploaded runs."
  type        = number
  default     = 30
}

variable "admin_cidr" {
  description = "The only address allowed to use SSH and the Kubernetes API: your own public IP, as x.x.x.x/32."
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "Give your own address as x.x.x.x/32. Opening SSH to the whole internet is refused."
  }
}

variable "ssh_public_key" {
  description = "Your SSH public key (the contents of the .pub file). The private key never leaves your computer."
  type        = string
}
