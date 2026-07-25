#!/usr/bin/env python3
from __future__ import annotations

import os

import aws_cdk as cdk

from infrastructure.knowledge_stack import KnowledgeStack


def main() -> None:
    app = cdk.App()
    region = (
        os.environ.get("CDK_DEFAULT_REGION")
        or app.node.try_get_context("region")
        or "us-east-1"
    )
    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=region,
    )
    KnowledgeStack(app, "BlendKnowledge", env=env)
    app.synth()


if __name__ == "__main__":
    main()
