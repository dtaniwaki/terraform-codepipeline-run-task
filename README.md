# terraform-codepipeline-run-task

## Usage

e.g.

```tf
resource "aws_ecs_cluster" "app" {
  ...
}

resource "aws_ecs_task_definition" "app_db_migration" {
  ...
}

module "run_task" {
  source = "codepipeline_run_task/modules"

  name                = "app-db-migration"
  task_definition_arn = aws_ecs_task_definition.app_db_migration.arn
}


resource "aws_codepipeline" "app_deploy" {
  name     = "app-deploy"

  ...

  stage {
    name = "deploy"

    action {
      name            = "db-migration"
      category        = "Invoke"
      owner           = "AWS"
      provider        = "Lambda"
      version         = "1"
      input_artifacts = ["SourceArtifact"]
      run_order       = 1

      configuration = {
        FunctionName = module.run_task.lambda_function_name
        UserParameters = jsonencode({
          cluster              = aws_ecs_cluster.app.name
          taskDefinitionFamily = aws_ecs_task_definition.app_db_migration.family
          containerName        = "app-db-migration"
          networkConfiguration = {
            "awsvpcConfiguration" : {
              "subnets" : var.private_subnet_ids,
              "securityGroups" : [aws_security_group.app.id],
              "assignPublicIp" : "DISABLED",
            }
          }
          overrides = {
          }
        })
      }
    }
  }
}
```
