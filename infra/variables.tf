# Inputs to the configuration. Defaults match our setup, so no extra values are needed to run it.

variable "aws_region" {
  description = "AWS region for all resources. Matches the Snowflake region to avoid data transfer costs."
  type        = string
  default     = "eu-west-1"
}

variable "aws_profile" {
  description = "AWS CLI profile (from `aws configure sso`) that Terraform authenticates with."
  type        = string
  default     = "transit"
}

variable "project" {
  description = "Project name, used for resource names and tags."
  type        = string
  default     = "lisbon-transit"
}
