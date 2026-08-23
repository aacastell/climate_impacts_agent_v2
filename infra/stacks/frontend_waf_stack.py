from aws_cdk import (
    CfnOutput,
    Stack,
    aws_wafv2 as wafv2,
)
from constructs import Construct

# AWS Managed Rule Groups providing broad, low-maintenance coverage against
# common web exploits, known-bad request signatures, and IPs with poor
# reputation. See ADR-001's WAF open item.
_MANAGED_RULE_GROUPS = [
    "AWSManagedRulesCommonRuleSet",
    "AWSManagedRulesKnownBadInputsRuleSet",
    "AWSManagedRulesAmazonIpReputationList",
]

# Requests per 5-minute window, per client IP, before the rate rule counts
# a client. AWS WAF rate-based rules always evaluate over a fixed 5-minute
# window; that part isn't a knob we control. The threshold itself is ours
# to tune once real traffic gives us something to tune it against.
_RATE_LIMIT_PER_5_MIN = 2000


class FrontendWafStack(Stack):
    """WAF Web ACL for the frontend CloudFront distribution.

    Must be deployed to us-east-1 regardless of where the rest of the
    system lives: a WAFv2 web ACL scoped to CLOUDFRONT is only creatable
    from that region's API, since CloudFront itself is a global service
    addressed from us-east-1. FrontendHostingStack (deployed wherever the
    rest of this app deploys) takes this stack's web_acl_arn as a
    constructor argument and references it via CDK cross-region references
    — see app.py.

    Every rule starts in COUNT mode, not BLOCK: this is a first pass with
    no production traffic baseline to tune against. Counting first means
    CloudWatch metrics and sampled requests show what *would* have been
    blocked before anything actually is, so a legitimate user is never the
    one who discovers a false positive. Flipping a rule to Block (override
    action, for the managed groups; action, for the rate rule) once that's
    confirmed clean is a deliberate follow-up, not a TODO left in code.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        managed_rules = [
            wafv2.CfnWebACL.RuleProperty(
                name=name,
                priority=i,
                override_action=wafv2.CfnWebACL.OverrideActionProperty(count={}),
                statement=wafv2.CfnWebACL.StatementProperty(
                    managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                        vendor_name="AWS",
                        name=name,
                    )
                ),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    sampled_requests_enabled=True,
                    cloud_watch_metrics_enabled=True,
                    metric_name=name,
                ),
            )
            for i, name in enumerate(_MANAGED_RULE_GROUPS, start=1)
        ]

        rate_rule = wafv2.CfnWebACL.RuleProperty(
            name="RateLimitPerIp",
            priority=len(_MANAGED_RULE_GROUPS) + 1,
            action=wafv2.CfnWebACL.RuleActionProperty(count={}),
            statement=wafv2.CfnWebACL.StatementProperty(
                rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                    limit=_RATE_LIMIT_PER_5_MIN,
                    aggregate_key_type="IP",
                )
            ),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="RateLimitPerIp",
            ),
        )

        web_acl = wafv2.CfnWebACL(
            self,
            "FrontendWebAcl",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="FrontendWebAcl",
            ),
            rules=[*managed_rules, rate_rule],
        )

        self.web_acl_arn = web_acl.attr_arn

        CfnOutput(self, "WebAclArn", value=web_acl.attr_arn)
