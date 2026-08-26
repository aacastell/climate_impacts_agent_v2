"""EventBridge's real monthly trigger point — check_drift.py's own docstring already argues
against running this more than infrequently (repeated significance testing inflates the true
false-positive rate past the nominal alpha), so a monthly schedule is the actual cadence, not a
manual-only script nobody remembers to run. See infra/stacks/model_services_stack.py's
DriftCheckFunction + MonthlyDriftCheckSchedule for the real infra this runs on.

Lambda's execution model needs a handler(event, context) function, not argparse's CLI surface —
this is a thin adapter over check_drift.run_drift_check, not a second implementation of it.
"""

import os

from check_drift import DEFAULT_MODEL_ID, run_drift_check


def handler(event, context):
    result = run_drift_check(
        index_name=os.environ["LOCATION_INDEX_NAME"],
        bucket=os.environ["ISIMIP_BUCKET"],
        model_id=os.environ.get("UNDERSTANDING_MODEL_ID", DEFAULT_MODEL_ID),
    )

    if result is not None and result["drift_detected"]:
        # Raising, not just logging: this is what actually surfaces as a Lambda execution
        # failure other AWS services (a CloudWatch Alarm on Errors — not wired up yet, see
        # docs/roadmap.md) can act on, rather than a result sitting unread in a log group.
        raise RuntimeError(
            f"Drift detected: baseline={result['baseline_accuracy']:.1%} "
            f"current={result['current_accuracy']:.1%} delta={result['delta']:+.1%} p={result['p_value']:.4f}"
        )

    return result
