# Values Terraform prints after `apply`, and that other tools (or later phases) can read.

output "raw_bucket_name" {
  description = "Name of the raw-layer S3 bucket. Used as RAW_BUCKET by the ingestion code."
  value       = aws_s3_bucket.raw.bucket
}

output "raw_bucket_arn" {
  description = "ARN (AWS's unique resource identifier) of the raw bucket. Used later in IAM policies."
  value       = aws_s3_bucket.raw.arn
}
