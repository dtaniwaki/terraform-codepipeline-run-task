locals {
  aws_region = data.aws_region.current.name
  account_id = data.aws_caller_identity.self.account_id
}
