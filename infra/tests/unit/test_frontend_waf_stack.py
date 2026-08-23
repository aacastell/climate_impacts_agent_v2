import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.frontend_waf_stack import FrontendWafStack


def _template() -> Template:
    app = cdk.App()
    stack = FrontendWafStack(app, "TestFrontendWafStack")
    return Template.from_stack(stack)


def test_web_acl_scoped_to_cloudfront_with_default_allow():
    _template().has_resource_properties(
        "AWS::WAFv2::WebACL",
        {
            "Scope": "CLOUDFRONT",
            "DefaultAction": {"Allow": {}},
        },
    )


def test_rules_start_in_count_mode_not_block():
    template = _template().to_json()
    [web_acl] = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::WAFv2::WebACL"
    ]
    rules = web_acl["Properties"]["Rules"]
    assert len(rules) == 4
    for rule in rules:
        action = rule.get("OverrideAction") or rule.get("Action")
        assert "Count" in action, f"{rule['Name']} is not in Count mode: {action}"
        assert "Block" not in action