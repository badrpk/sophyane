from sophyane.mobile_permission_center import PERMISSION_SUFFIX, permission_center_problem


REQUEST = "make a mobile sensor dashboard with app icon"
GOOD = """<!doctype html><html><body>
<section>Permission Center</section><button>Review & Request Access</button>
<select><option>This session</option><option>7 days</option><option>30 days</option><option>Until I revoke</option></select>
<button>Stop All Sensors</button>
<script>
const expiry=Date.now()+1000;localStorage.setItem('sensor-expiry',expiry);
navigator.permissions.query({name:'geolocation'}).then(x=>x.onchange=()=>{});
</script></body></html>"""


def test_prompt_explains_real_and_local_permission_lifetimes() -> None:
    lower = PERMISSION_SUFFIX.lower()
    assert "browser/android controls the actual permission lifetime" in lower
    assert "this session" in lower
    assert "7 days" in lower
    assert "until i revoke" in lower
    assert "never start sensitive sensors automatically" in lower


def test_complete_permission_center_passes() -> None:
    assert permission_center_problem(GOOD, REQUEST) == ""


def test_missing_user_approval_action_is_rejected() -> None:
    assert "approval" in permission_center_problem(GOOD.replace("Review & Request Access", "Status"), REQUEST)


def test_missing_expiry_policy_is_rejected() -> None:
    html = GOOD.replace("localStorage.setItem('sensor-expiry',expiry);", "")
    assert "expiring" in permission_center_problem(html, REQUEST)


def test_non_sensor_requests_are_unchanged() -> None:
    assert permission_center_problem("<html></html>", "make chess game") == ""
