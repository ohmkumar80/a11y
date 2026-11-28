#!/bin/sh
# Create the dev bucket once the S3 service answers. Idempotent.
for i in $(seq 1 30); do
  if aws --endpoint-url http://s3:9000 s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
    echo "bucket $S3_BUCKET ready"; exit 0
  fi
  aws --endpoint-url http://s3:9000 s3 mb "s3://$S3_BUCKET" 2>/dev/null && { echo "bucket $S3_BUCKET created"; exit 0; }
  sleep 2
done
echo "could not create bucket $S3_BUCKET" >&2
exit 1
