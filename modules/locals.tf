locals {
  aws_region = aws_region.current.name
  account_id = aws_caller_identity.self.account_id
}
