import json
import os
from threading import Timer
from unittest.mock import patch

import boto3
from moto import mock_codepipeline, mock_ec2, mock_ecs, mock_s3
from moto.ec2 import utils as ec2_utils
from mypy_boto3_ecs import ECSClient
from src import handler

fixtures_dir_path = os.path.join(os.path.dirname(__file__), "fixtures")

region_name = "us-east-1"
cluster_name = "app-cluster"
os.environ["AWS_REGION"] = region_name

EXAMPLE_AMI_ID = "ami-12c6146b"


def _setup_env() -> None:
    s3_resource = boto3.resource("s3", region_name=region_name)
    s3_resource.create_bucket(Bucket="deploy")

    s3_client = boto3.client("s3", region_name=region_name)
    s3_client.put_object(
        Bucket="deploy",
        Key="SourceArti/000000",
        Body=open(os.path.join(fixtures_dir_path, "artifact.zip"), "rb").read(),
    )

    ecs_client = boto3.client("ecs", region_name=region_name)
    _ = ecs_client.create_cluster(clusterName=cluster_name)
    # Need to register container instances in moto? even if we use FARGATE.
    ec2_resource = boto3.resource("ec2", region_name=region_name)
    test_instance = ec2_resource.create_instances(ImageId=EXAMPLE_AMI_ID, MinCount=1, MaxCount=1)[0]
    instance_id_document = json.dumps(ec2_utils.generate_instance_identity_document(test_instance))
    _ = ecs_client.register_container_instance(cluster=cluster_name, instanceIdentityDocument=instance_id_document)
    _ = ecs_client.register_task_definition(
        family="app-db-migration",
        requiresCompatibilities=["FARGATE"],
        containerDefinitions=[{"name": "hello_world", "image": "hello-world:latest", "cpu": 256, "memory": 400}],
    )


def _stop_tasks_later(ecs_client: ECSClient) -> None:
    list_tasks_response = ecs_client.list_tasks(cluster=cluster_name)
    for task_arn in list_tasks_response["taskArns"]:
        _ = ecs_client.stop_task(
            cluster=cluster_name,
            task=task_arn,
            reason="auto stop",
        )


def mock_codepipeline_response(self):
    return "200", {}, json.dumps({})


@mock_codepipeline
# `put_job_success_result` has not been implemented as of moto 3.1.16.
@patch(
    "moto.codepipeline.responses.CodePipelineResponse.put_job_success_result",
    new=mock_codepipeline_response,
    create=True,
)
# `put_job_failure_result` has not been implemented as of moto 3.1.16.
@patch(
    "moto.codepipeline.responses.CodePipelineResponse.put_job_failure_result",
    new=mock_codepipeline_response,
    create=True,
)
@mock_ecs
@mock_s3
@mock_ec2
def test_lambda_handler() -> None:
    _setup_env()

    ecs_client = boto3.client("ecs", region_name=region_name)
    Timer(3.0, _stop_tasks_later, [ecs_client]).start()

    event = json.loads(open(os.path.join(fixtures_dir_path, "event.json")).read())
    result = handler.lambda_handler(event, {})
    assert result == {"body": "\"OK!\"", "statusCode": 200}
