resource "aws_cloudwatch_log_group" "run_task" {
  name = var.name
  retention_in_days = 30
}
