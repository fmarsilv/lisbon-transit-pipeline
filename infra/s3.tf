# The raw-layer bucket: every API response lands here, untouched and gzipped (see docs/decisions.md, 009).

resource "aws_s3_bucket" "raw" {
  # Bucket names are globally unique across all of AWS; the account ID suffix guarantees ours is.
  bucket = "${var.project}-raw-${data.aws_caller_identity.current.account_id}"

  # Safety net: Terraform refuses to delete the bucket while it still contains files.
  force_destroy = false
}

# Block every form of public access. This data is public anyway, but a bucket should never
# be accidentally exposed; least privilege applies to storage too.
resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Encrypt every object at rest with S3-managed keys. AWS does this by default for new buckets;
# declaring it explicitly documents the decision and protects against the default ever changing.
resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
