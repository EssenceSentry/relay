from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aws_cdk import (
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Size,
    Stack,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_certificatemanager as acm,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_lambda_event_sources as lambda_event_sources,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_opensearchserverless as aoss,
)
from aws_cdk import (
    aws_route53 as route53,
)
from aws_cdk import (
    aws_route53_targets as route53_targets,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3deploy,
)
from aws_cdk import (
    aws_s3_notifications as s3_notifications,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_servicediscovery as servicediscovery,
)
from aws_cdk import (
    aws_ses as ses,
)
from aws_cdk import (
    aws_ses_actions as ses_actions,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from aws_cdk import (
    custom_resources as cr,
)
from constructs import Construct

_ROOT = Path(__file__).resolve().parents[1]
_BOOTSTRAP_PUBLIC_BASE_URL = "https://placeholder.invalid/"
_RUNTIME_ASSET_EXCLUDES = [
    ".git",
    ".git/**",
    ".venv",
    ".venv/**",
    "cdk.out",
    "cdk.out/**",
    "PIH - Dataset",
    "PIH - Dataset/**",
    "tests",
    "tests/**",
    "text_extraction",
    "text_extraction/**",
]


def _context_flag(name: str, raw_value: object | None) -> bool:
    if raw_value is None:
        return False
    if isinstance(raw_value, bool):
        return raw_value
    value = str(raw_value).strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false, not {raw_value!r}")


def _public_base_url(raw_value: object | None) -> str:
    if raw_value is None:
        return _BOOTSTRAP_PUBLIC_BASE_URL
    value = str(raw_value).strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "mcp_public_base_url must be an HTTPS origin without a path, "
            "query, credentials, or fragment"
        )
    return f"{value}/"


class KnowledgeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        retain_data = bool(self.node.try_get_context("retain_data") or False)
        removal_policy = (
            RemovalPolicy.RETAIN if retain_data else RemovalPolicy.DESTROY
        )
        embedding_dimensions = int(
            self.node.try_get_context("embedding_dimensions") or 1536
        )
        embedding_model = str(
            self.node.try_get_context("embedding_model")
            or "text-embedding-3-large"
        )
        review_model = str(
            self.node.try_get_context("review_model") or "gpt-5-mini"
        )
        document_processing_model = str(
            self.node.try_get_context("document_processing_model")
            or "gpt-5.4-mini"
        )
        public_base_url = _public_base_url(
            self.node.try_get_context("mcp_public_base_url")
        )
        raw_mcp_auth_enabled = self.node.try_get_context("mcp_auth_enabled")
        mcp_auth_enabled = (
            True
            if raw_mcp_auth_enabled is None
            else _context_flag("mcp_auth_enabled", raw_mcp_auth_enabled)
        )
        max_upload_bytes = (
            100 * 1024 * 1024 if mcp_auth_enabled else 25 * 1024 * 1024
        )
        microsoft_sso_enabled = _context_flag(
            "microsoft_sso",
            self.node.try_get_context("microsoft_sso"),
        )
        microsoft_sso_secret_name = str(
            self.node.try_get_context("microsoft_sso_secret_name")
            or "blend-knowledge/sso/microsoft"
        ).strip()
        if microsoft_sso_enabled and not microsoft_sso_secret_name:
            raise ValueError(
                "microsoft_sso_secret_name is required when "
                "microsoft_sso is true"
            )

        raw_email_domain = self.node.try_get_context("email_domain")
        email_domain = (
            str(raw_email_domain).strip().casefold().rstrip(".")
            if raw_email_domain
            else None
        )
        raw_public_domain = self.node.try_get_context("public_domain")
        public_domain = (
            str(raw_public_domain).strip().casefold().rstrip(".")
            if raw_public_domain
            else None
        )
        email_sender_local_part = (
            str(
                self.node.try_get_context("email_sender_local_part")
                or "questions"
            )
            .strip()
            .casefold()
        )
        if email_domain and not re.fullmatch(
            r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z]{2,63}",
            email_domain,
        ):
            raise ValueError(
                f"Invalid email_domain CDK context: {email_domain!r}"
            )
        if public_domain and not re.fullmatch(
            r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z]{2,63}",
            public_domain,
        ):
            raise ValueError(
                f"Invalid public_domain CDK context: {public_domain!r}"
            )
        if (
            public_domain is not None
            and email_domain is not None
            and public_domain != email_domain
        ):
            raise ValueError(
                "public_domain and email_domain must match in this deployment"
            )
        if not re.fullmatch(
            r"[a-z0-9][a-z0-9._+-]{0,62}", email_sender_local_part
        ):
            raise ValueError(
                "email_sender_local_part must be a valid mailbox local part"
            )

        document_bucket = s3.Bucket(
            self,
            "DocumentBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            removal_policy=removal_policy,
            auto_delete_objects=not retain_data,
            lifecycle_rules=[
                s3.LifecycleRule(
                    abort_incomplete_multipart_upload_after=Duration.days(1)
                )
            ],
        )
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=removal_policy,
            auto_delete_objects=not retain_data,
        )

        table = dynamodb.Table(
            self,
            "KnowledgeTable",
            partition_key=dynamodb.Attribute(
                name="PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="SK",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            point_in_time_recovery=retain_data,
            time_to_live_attribute="expires_at",
            removal_policy=removal_policy,
        )
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        openai_secret = secretsmanager.Secret(
            self,
            "OpenAISecret",
            description="OpenAI API key used for embeddings and answer review",
            secret_object_value={
                "api_key": SecretValue.unsafe_plain_text("replace-me"),
                "note": SecretValue.unsafe_plain_text(
                    "Run scripts/configure_openai.sh after deployment"
                ),
            },
            removal_policy=removal_policy,
        )
        user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_digits=True,
                require_lowercase=True,
                require_symbols=False,
                require_uppercase=True,
                temp_password_validity=Duration.days(7),
            ),
            removal_policy=removal_policy,
        )
        cognito.UserPoolGroup(
            self,
            "AdminGroup",
            user_pool=user_pool,
            group_name="admins",
            description="Can answer any knowledge-gap question",
        )
        domain_prefix = str(
            self.node.try_get_context("cognito_domain_prefix")
            or f"blend-knowledge-{self.node.addr[-10:].lower()}"
        )
        user_pool_domain = user_pool.add_domain(
            "HostedDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=domain_prefix,
            ),
        )
        identity_providers: list[cognito.IUserPoolIdentityProvider] = []
        supported_identity_providers = [
            cognito.UserPoolClientIdentityProvider.COGNITO
        ]
        if microsoft_sso_enabled:
            microsoft_secret = secretsmanager.Secret.from_secret_name_v2(
                self,
                "MicrosoftSsoSecret",
                microsoft_sso_secret_name,
            )
            microsoft_provider = cognito.UserPoolIdentityProviderOidc(
                self,
                "MicrosoftIdentityProvider",
                user_pool=user_pool,
                name="Microsoft",
                client_id=microsoft_secret.secret_value_from_json(
                    "client_id"
                ).unsafe_unwrap(),
                client_secret=microsoft_secret.secret_value_from_json(
                    "client_secret"
                ).unsafe_unwrap(),
                issuer_url=(
                    "https://login.microsoftonline.com/"
                    f"{microsoft_secret.secret_value_from_json('tenant_id').unsafe_unwrap()}"
                    "/v2.0"
                ),
                scopes=["openid", "email", "profile"],
                attribute_request_method=(
                    cognito.OidcAttributeRequestMethod.GET
                ),
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.other("preferred_username"),
                    fullname=cognito.ProviderAttribute.other("name"),
                ),
            )
            identity_providers.append(microsoft_provider)
            supported_identity_providers = [
                cognito.UserPoolClientIdentityProvider.custom("Microsoft")
            ]

        origin_access_identity = cloudfront.OriginAccessIdentity(
            self,
            "FrontendOAI",
        )
        frontend_bucket.grant_read(origin_access_identity)
        public_hosted_zone = None
        frontend_certificate = None
        if public_domain is not None:
            public_hosted_zone = route53.PublicHostedZone.from_lookup(
                self,
                "PublicHostedZone",
                domain_name=public_domain,
            )
            frontend_certificate = acm.Certificate(
                self,
                "FrontendCertificate",
                domain_name=public_domain,
                validation=acm.CertificateValidation.from_dns(
                    public_hosted_zone
                ),
            )
        spa_rewrite = cloudfront.Function(
            self,
            "SpaRewrite",
            code=cloudfront.FunctionCode.from_inline(
                """
function handler(event) {
    var request = event.request;
    var uri = request.uri;
    if (uri.endsWith("/") || !uri.split("/").pop().includes(".")) {
        request.uri = "/index.html";
    }
    return request;
}
""".strip()
            ),
        )
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    frontend_bucket,
                    origin_access_identity=origin_access_identity,
                ),
                viewer_protocol_policy=(
                    cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
                ),
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=(
                    cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS
                ),
                function_associations=[
                    cloudfront.FunctionAssociation(
                        event_type=(
                            cloudfront.FunctionEventType.VIEWER_REQUEST
                        ),
                        function=spa_rewrite,
                    )
                ],
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            certificate=frontend_certificate,
            domain_names=[public_domain] if public_domain else None,
        )
        if public_domain is not None and public_hosted_zone is not None:
            route53.ARecord(
                self,
                "FrontendAliasA",
                zone=public_hosted_zone,
                record_name=public_domain,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution)  # pyright: ignore[reportArgumentType]
                ),
            )
            route53.AaaaRecord(
                self,
                "FrontendAliasAAAA",
                zone=public_hosted_zone,
                record_name=public_domain,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution)  # pyright: ignore[reportArgumentType]
                ),
            )
        frontend_url = (
            f"https://{public_domain}/"
            if public_domain
            else f"https://{distribution.distribution_domain_name}/"
        )

        user_pool_client = user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=not microsoft_sso_enabled),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[public_base_url],
                logout_urls=[public_base_url],
            ),
            supported_identity_providers=supported_identity_providers,
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(7),
        )
        mcp_callback_url = f"{public_base_url}oauth/callback"
        mcp_identity_client = user_pool.add_client(
            "McpIdentityClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=not microsoft_sso_enabled),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[mcp_callback_url],
                logout_urls=[public_base_url],
            ),
            supported_identity_providers=supported_identity_providers,
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(7),
        )
        for identity_provider in identity_providers:
            user_pool_client.node.add_dependency(identity_provider)
            mcp_identity_client.node.add_dependency(identity_provider)

        document_bucket.add_cors_rule(
            allowed_methods=[s3.HttpMethods.POST],
            allowed_origins=[public_base_url.rstrip("/")],
            allowed_headers=["*"],
            exposed_headers=["ETag"],
            max_age=3600,
        )

        email_identity = None
        inbound_email_bucket = None
        receipt_rule_set = None
        ses_from_address = None
        email_environment = {"EMAIL_ENABLED": "false"}
        email_resource_prefix = (
            re.sub(
                r"[^a-z0-9-]+",
                "-",
                self.stack_name.casefold(),
            ).strip("-")[:40]
            or "blend-knowledge"
        )
        if email_domain is not None:
            hosted_zone = route53.PublicHostedZone.from_lookup(
                self,
                "EmailHostedZone",
                domain_name=email_domain,
            )
            ses_from_address = f"{email_sender_local_part}@{email_domain}"
            email_identity = ses.EmailIdentity(
                self,
                "EmailIdentity",
                identity=ses.Identity.public_hosted_zone(hosted_zone),
                mail_from_domain=f"mail.{email_domain}",
            )
            inbound_mx_record = route53.MxRecord(
                self,
                "InboundEmailMx",
                zone=hosted_zone,
                values=[
                    route53.MxRecordValue(
                        priority=10,
                        host_name=(
                            f"inbound-smtp.{self.region}.{Aws.URL_SUFFIX}"
                        ),
                    )
                ],
                ttl=Duration.minutes(5),
            )
            route53.TxtRecord(
                self,
                "DmarcRecord",
                zone=hosted_zone,
                record_name="_dmarc",
                values=["v=DMARC1; p=none; adkim=r; aspf=r"],
                ttl=Duration.minutes(5),
            )

            inbound_email_bucket = s3.Bucket(
                self,
                "InboundEmailBucket",
                encryption=s3.BucketEncryption.S3_MANAGED,
                enforce_ssl=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                removal_policy=removal_policy,
                auto_delete_objects=not retain_data,
                lifecycle_rules=[
                    s3.LifecycleRule(
                        expiration=Duration.days(30),
                        abort_incomplete_multipart_upload_after=Duration.days(
                            1
                        ),
                    )
                ],
            )
            inbound_email_function = lambda_.DockerImageFunction(
                self,
                "InboundEmailFunction",
                code=lambda_.DockerImageCode.from_image_asset(
                    directory=str(_ROOT),
                    file="services/inbound_email_lambda/Dockerfile",
                    platform=ecr_assets.Platform.LINUX_AMD64,
                    exclude=_RUNTIME_ASSET_EXCLUDES,
                ),
                architecture=lambda_.Architecture.X86_64,
                timeout=Duration.minutes(2),
                memory_size=512,
                reserved_concurrent_executions=2,
                environment={
                    "TABLE_NAME": table.table_name,
                    "INBOUND_EMAIL_BUCKET": inbound_email_bucket.bucket_name,
                    "INBOUND_EMAIL_PREFIX": "inbound/",
                    "SES_REPLY_DOMAIN": email_domain,
                    "MAX_EMAIL_ANSWER_CHARS": "20000",
                },
                log_retention=logs.RetentionDays.ONE_WEEK,
            )
            inbound_email_bucket.grant_read(inbound_email_function)
            table.grant_read_write_data(inbound_email_function)

            receipt_rule_set = ses.ReceiptRuleSet(
                self,
                "InboundReceiptRuleSet",
                receipt_rule_set_name=f"{email_resource_prefix}-inbound",
            )
            receipt_rule = receipt_rule_set.add_rule(
                "KnowledgeGapReplies",
                receipt_rule_name=f"{email_resource_prefix}-gap-replies",
                recipients=[email_domain],
                scan_enabled=True,
                actions=[  # pyright: ignore[reportArgumentType]
                    ses_actions.S3(
                        bucket=inbound_email_bucket,
                        object_key_prefix="inbound/",
                    ),
                    ses_actions.Lambda(
                        function=inbound_email_function,  # pyright: ignore[reportArgumentType]
                        invocation_type=ses_actions.LambdaInvocationType.EVENT,
                    ),
                ],
            )
            receipt_rule.node.add_dependency(email_identity)
            receipt_rule.node.add_dependency(inbound_mx_record)
            activate_call = cr.AwsSdkCall(
                service="SES",
                action="setActiveReceiptRuleSet",
                parameters={
                    "RuleSetName": receipt_rule_set.receipt_rule_set_name
                },
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"{email_resource_prefix}-active-receipt-rule-set"
                ),
            )
            activate_rule_set = cr.AwsCustomResource(
                self,
                "ActivateInboundReceiptRuleSet",
                on_create=activate_call,
                on_update=activate_call,
                on_delete=cr.AwsSdkCall(
                    service="SES",
                    action="setActiveReceiptRuleSet",
                    parameters={},
                ),
                policy=cr.AwsCustomResourcePolicy.from_statements(
                    [
                        iam.PolicyStatement(
                            actions=["ses:SetActiveReceiptRuleSet"],
                            resources=["*"],
                        )
                    ]
                ),
                install_latest_aws_sdk=False,
            )
            activate_rule_set.node.add_dependency(receipt_rule)
            email_environment = {
                "EMAIL_ENABLED": "true",
                "SES_FROM_ADDRESS": ses_from_address,
                "SES_REPLY_DOMAIN": email_domain,
                "APPLICATION_BASE_URL": public_base_url,
            }

        collection_name = "blend-knowledge"
        group_name = "blend-knowledge-group"
        index_name = "knowledge-documents-v1"

        encryption_policy = aoss.CfnSecurityPolicy(
            self,
            "OpenSearchEncryptionPolicy",
            name="blend-knowledge-encryption",
            type="encryption",
            policy=self.to_json_string(
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": [f"collection/{collection_name}"],
                        }
                    ],
                    "AWSOwnedKey": True,
                }
            ),
        )
        encryption_policy.apply_removal_policy(removal_policy)

        network_policy = aoss.CfnSecurityPolicy(
            self,
            "OpenSearchNetworkPolicy",
            name="blend-knowledge-network",
            type="network",
            policy=self.to_json_string(
                [
                    {
                        "Rules": [
                            {
                                "ResourceType": "collection",
                                "Resource": [f"collection/{collection_name}"],
                            }
                        ],
                        "AllowFromPublic": True,
                    }
                ]
            ),
        )
        network_policy.apply_removal_policy(removal_policy)

        collection_group = aoss.CfnCollectionGroup(
            self,
            "OpenSearchCollectionGroup",
            name=group_name,
            generation="NEXTGEN",
            standby_replicas="ENABLED",
            capacity_limits=(
                aoss.CfnCollectionGroup.CapacityLimitsProperty(
                    min_indexing_capacity_in_ocu=0,
                    min_search_capacity_in_ocu=0,
                    max_indexing_capacity_in_ocu=2,
                    max_search_capacity_in_ocu=2,
                )
            ),
            description="Scale-to-zero capacity group for the knowledge MVP",
        )
        collection_group.apply_removal_policy(removal_policy)

        collection = aoss.CfnCollection(
            self,
            "OpenSearchCollection",
            name=collection_name,
            type="VECTORSEARCH",
            standby_replicas="ENABLED",
            deletion_protection="ENABLED" if retain_data else "DISABLED",
            collection_group_name=group_name,
            description="Combined BM25 and vector retrieval index",
        )
        collection.apply_removal_policy(removal_policy)
        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)
        collection.add_dependency(collection_group)

        common_environment = {
            "TABLE_NAME": table.table_name,
            "DOCUMENT_BUCKET": document_bucket.bucket_name,
            "OPENSEARCH_ENDPOINT": collection.attr_collection_endpoint,
            "OPENSEARCH_INDEX": index_name,
            "OPENAI_SECRET_ARN": openai_secret.secret_arn,
            "EMBEDDING_MODEL": embedding_model,
            "EMBEDDING_DIMENSIONS": str(embedding_dimensions),
        }

        dead_letter_queue = sqs.Queue(
            self,
            "IngestionDLQ",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14),
        )
        ingestion_queue = sqs.Queue(
            self,
            "IngestionQueue",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            visibility_timeout=Duration.minutes(16),
            dead_letter_queue=sqs.DeadLetterQueue(
                queue=dead_letter_queue,
                max_receive_count=4,
            ),
        )
        document_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notifications.SqsDestination(ingestion_queue),  # pyright: ignore[reportArgumentType]
            s3.NotificationKeyFilter(prefix="uploads/"),
        )

        ingestion_function = lambda_.DockerImageFunction(
            self,
            "IngestionFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(_ROOT),
                file="services/ingestion_lambda/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
                exclude=_RUNTIME_ASSET_EXCLUDES,
            ),
            architecture=lambda_.Architecture.X86_64,
            timeout=Duration.minutes(15),
            memory_size=2048,
            ephemeral_storage_size=Size.gibibytes(2),
            reserved_concurrent_executions=2,
            environment={
                **common_environment,
                "DOCUMENT_PROCESSING_MODEL": document_processing_model,
                "INGESTION_QUEUE_URL": ingestion_queue.queue_url,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        ingestion_function.add_event_source(
            lambda_event_sources.SqsEventSource(
                ingestion_queue,
                batch_size=1,
                report_batch_item_failures=True,
            )
        )
        ingestion_queue.grant_send_messages(ingestion_function)

        review_function = lambda_.DockerImageFunction(
            self,
            "ReviewFunction",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(_ROOT),
                file="services/review_lambda/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
                exclude=_RUNTIME_ASSET_EXCLUDES,
            ),
            architecture=lambda_.Architecture.X86_64,
            timeout=Duration.minutes(5),
            memory_size=1024,
            reserved_concurrent_executions=2,
            environment={
                **common_environment,
                **email_environment,
                "REVIEW_MODEL": review_model,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        review_function.add_event_source(
            lambda_event_sources.DynamoEventSource(
                table,
                starting_position=lambda_.StartingPosition.LATEST,
                batch_size=10,
                bisect_batch_on_error=True,
                retry_attempts=5,
                report_batch_item_failures=True,
            )
        )

        for function in (ingestion_function, review_function):
            document_bucket.grant_read_write(function)
            table.grant_read_write_data(function)
            openai_secret.grant_read(function)

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)
        namespace = servicediscovery.PrivateDnsNamespace(
            self,
            "ServiceNamespace",
            name="knowledge.local",
            vpc=vpc,
        )
        task_role = iam.Role(
            self,
            "ApiTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),  # pyright: ignore[reportArgumentType]
        )
        task_definition = ecs.FargateTaskDefinition(
            self,
            "ApiTaskDefinition",
            cpu=512,
            memory_limit_mib=1024,
            task_role=task_role,  # pyright: ignore[reportArgumentType]
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        container = task_definition.add_container(
            "ApiContainer",
            image=ecs.ContainerImage.from_asset(
                directory=str(_ROOT),
                file="services/api/Dockerfile",
                platform=ecr_assets.Platform.LINUX_AMD64,
                exclude=_RUNTIME_ASSET_EXCLUDES,
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="api",
                log_group=api_log_group,
            ),
            environment={
                **common_environment,
                **email_environment,
                "USER_POOL_ID": user_pool.user_pool_id,
                "USER_POOL_CLIENT_ID": user_pool_client.user_pool_client_id,
                "MCP_AUTH_ENABLED": ("true" if mcp_auth_enabled else "false"),
                "MCP_COGNITO_CLIENT_ID": (
                    mcp_identity_client.user_pool_client_id
                ),
                "MCP_COGNITO_DOMAIN": user_pool_domain.base_url(),
                "MCP_PUBLIC_BASE_URL": public_base_url.rstrip("/"),
                "MAX_UPLOAD_BYTES": str(max_upload_bytes),
            },
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    (
                        'python -c "import urllib.request; '
                        "urllib.request.urlopen('http://127.0.0.1:8000/healthz', "
                        'timeout=3)"'
                    ),
                ],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(30),
            ),
        )
        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                protocol=ecs.Protocol.TCP,
                name="http",
            )
        )

        vpc_link_security_group = ec2.SecurityGroup(
            self,
            "VpcLinkSecurityGroup",
            vpc=vpc,
            allow_all_outbound=True,
            description="API Gateway VPC Link to ECS",
        )
        service_security_group = ec2.SecurityGroup(
            self,
            "ApiServiceSecurityGroup",
            vpc=vpc,
            allow_all_outbound=True,
            description="Only accepts API Gateway VPC Link traffic",
        )
        service_security_group.add_ingress_rule(
            vpc_link_security_group,
            ec2.Port.tcp(8000),
            "API Gateway private integration",
        )
        service = ecs.FargateService(
            self,
            "ApiService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[service_security_group],
            min_healthy_percent=0,
            max_healthy_percent=200,
            circuit_breaker=ecs.DeploymentCircuitBreaker(
                enable=True,
                rollback=True,
            ),
            cloud_map_options=ecs.CloudMapOptions(
                cloud_map_namespace=namespace,
                name="api",
                container=container,
                container_port=8000,
                dns_record_type=servicediscovery.DnsRecordType.SRV,
                dns_ttl=Duration.seconds(10),
            ),
        )

        document_bucket.grant_read_write(task_role)
        table.grant_read_write_data(task_role)
        openai_secret.grant_read(task_role)
        if email_identity is not None:
            email_identity.grant_send_email(task_role)
            email_identity.grant_send_email(review_function)

        ingestion_role = ingestion_function.role
        review_role = review_function.role
        if ingestion_role is None or review_role is None:
            raise RuntimeError("Lambda execution roles were not created")

        principals = [
            task_role.role_arn,
            ingestion_role.role_arn,
            review_role.role_arn,
        ]
        data_access_policy = aoss.CfnAccessPolicy(
            self,
            "OpenSearchDataAccessPolicy",
            name="blend-knowledge-access",
            type="data",
            policy=self.to_json_string(
                [
                    {
                        "Description": "Application access to the knowledge index",
                        "Principal": principals,
                        "Rules": [
                            {
                                "ResourceType": "collection",
                                "Resource": [f"collection/{collection_name}"],
                                "Permission": ["aoss:*"],
                            },
                            {
                                "ResourceType": "index",
                                "Resource": [f"index/{collection_name}/*"],
                                "Permission": ["aoss:*"],
                            },
                        ],
                    }
                ]
            ),
        )
        data_access_policy.apply_removal_policy(removal_policy)
        data_access_policy.add_dependency(collection)

        for role in (
            task_role,
            ingestion_role,
            review_role,
        ):
            role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["aoss:APIAccessAll"],
                    resources=[collection.attr_arn],
                )
            )
            role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["aoss:DashboardsAccessAll"],
                    resources=[
                        (
                            f"arn:{Aws.PARTITION}:aoss:{Aws.REGION}:"
                            f"{Aws.ACCOUNT_ID}:dashboards/default"
                        )
                    ],
                )
            )

        if service.cloud_map_service is None:
            raise RuntimeError("ECS Cloud Map service was not created")
        vpc_link = apigwv2.CfnVpcLink(
            self,
            "ApiVpcLink",
            name="blend-knowledge-vpc-link",
            subnet_ids=[subnet.subnet_id for subnet in vpc.public_subnets],
            security_group_ids=[vpc_link_security_group.security_group_id],
        )
        http_api = apigwv2.CfnApi(
            self,
            "HttpApi",
            name="blend-knowledge-api",
            protocol_type="HTTP",
            cors_configuration=apigwv2.CfnApi.CorsProperty(
                allow_origins=[public_base_url.rstrip("/")],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["Mcp-Session-Id"],
                max_age=3600,
            ),
        )
        integration = apigwv2.CfnIntegration(
            self,
            "PrivateIntegration",
            api_id=http_api.ref,
            integration_type="HTTP_PROXY",
            integration_method="ANY",
            integration_uri=service.cloud_map_service.service_arn,
            connection_type="VPC_LINK",
            connection_id=vpc_link.ref,
            payload_format_version="1.0",
            timeout_in_millis=30_000,
            request_parameters={"overwrite:path": "$request.path"},
        )
        route = apigwv2.CfnRoute(
            self,
            "DefaultRoute",
            api_id=http_api.ref,
            route_key="$default",
            target=f"integrations/{integration.ref}",
        )
        stage = apigwv2.CfnStage(
            self,
            "DefaultStage",
            api_id=http_api.ref,
            stage_name="$default",
            auto_deploy=True,
        )
        integration.add_dependency(vpc_link)
        route.add_dependency(integration)
        stage.add_dependency(route)
        api_endpoint = (
            f"https://{http_api.ref}.execute-api.{self.region}.{Aws.URL_SUFFIX}"
        )
        api_origin = origins.HttpOrigin(
            f"{http_api.ref}.execute-api.{self.region}.{Aws.URL_SUFFIX}",
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )
        for path_pattern in (
            "mcp",
            "mcp/*",
            ".well-known/*",
            "authorize",
            "token",
            "register",
            "oauth/*",
        ):
            distribution.add_behavior(
                path_pattern,
                api_origin,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=(
                    cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER
                ),
                viewer_protocol_policy=(
                    cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
                ),
                response_headers_policy=(
                    cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS
                ),
            )
        mcp_url = f"{frontend_url}mcp/"

        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            destination_bucket=frontend_bucket,
            sources=[
                s3deploy.Source.asset(str(_ROOT / "frontend")),
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "api_base_url": api_endpoint,
                        "cognito_domain": user_pool_domain.base_url(),
                        "client_id": user_pool_client.user_pool_client_id,
                        "redirect_uri": frontend_url,
                        "logout_uri": frontend_url,
                        "mcp_url": mcp_url,
                        "mcp_connect_url": f"{frontend_url}connect",
                        "mcp_auth_enabled": mcp_auth_enabled,
                        "max_upload_bytes": max_upload_bytes,
                    },
                ),
            ],
            distribution=distribution,
            distribution_paths=["/*"],
            cache_control=[s3deploy.CacheControl.no_cache()],
            prune=True,
        )

        CfnOutput(self, "FrontendUrl", value=frontend_url)
        if public_domain is not None:
            CfnOutput(self, "PublicDomain", value=public_domain)
        CfnOutput(self, "ApiUrl", value=api_endpoint)
        CfnOutput(self, "McpUrl", value=mcp_url)
        CfnOutput(
            self,
            "McpAuthEnabled",
            value="true" if mcp_auth_enabled else "false",
        )
        CfnOutput(
            self,
            "McpConnectUrl",
            value=f"{frontend_url}connect",
        )
        CfnOutput(
            self,
            "McpAuthorizationServerMetadataUrl",
            value=f"{frontend_url}.well-known/oauth-authorization-server",
        )
        CfnOutput(
            self,
            "McpProtectedResourceMetadataUrl",
            value=(f"{frontend_url}.well-known/oauth-protected-resource/mcp/"),
        )
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(
            self,
            "UserPoolClientId",
            value=user_pool_client.user_pool_client_id,
        )
        CfnOutput(
            self,
            "McpCognitoClientId",
            value=mcp_identity_client.user_pool_client_id,
        )
        CfnOutput(
            self,
            "CognitoDomain",
            value=user_pool_domain.base_url(),
        )
        CfnOutput(
            self,
            "MicrosoftSsoEnabled",
            value="true" if microsoft_sso_enabled else "false",
        )
        CfnOutput(
            self,
            "OpenAISecretArn",
            value=openai_secret.secret_arn,
        )
        CfnOutput(
            self,
            "DocumentBucketName",
            value=document_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "KnowledgeTableName",
            value=table.table_name,
        )
        CfnOutput(
            self,
            "OpenSearchEndpoint",
            value=collection.attr_collection_endpoint,
        )
        CfnOutput(
            self,
            "EmailEnabled",
            value="true" if email_domain else "false",
        )
        if email_domain is not None:
            assert ses_from_address is not None
            assert inbound_email_bucket is not None
            assert receipt_rule_set is not None
            CfnOutput(self, "EmailDomain", value=email_domain)
            CfnOutput(self, "SesFromAddress", value=ses_from_address)
            CfnOutput(
                self,
                "InboundEmailBucketName",
                value=inbound_email_bucket.bucket_name,
            )
            CfnOutput(
                self,
                "ReceiptRuleSetName",
                value=receipt_rule_set.receipt_rule_set_name,
            )
