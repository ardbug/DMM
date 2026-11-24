from app.acquisition.scheduler import plan_rate
from app.domain.models import AcquisitionConfig


def test_nplc1_is_limited_to_20hz() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=1, rate=30, az=False))
    assert plan.effective == 20
    assert plan.batch_size == 1
    assert plan.period_ns == 50_000_000
    assert plan.limited is True
    assert plan.uniform is True


def test_nplc1_az_on_is_limited_to_16hz() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=1, rate=30, az=True))
    assert plan.effective == 16
    assert plan.batch_size == 1
    assert plan.period_ns == 62_500_000
    assert plan.limited is True


def test_nplc10_is_limited() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=10, rate=30, az=False))
    assert plan.effective == 1.8
    assert plan.batch_size == 1
    assert plan.period_ns == 555_555_555
    assert plan.limited is True


def test_10hz_is_not_limited() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=1, rate=10, az=False))
    assert plan.effective == 10
    assert plan.batch_size == 1
    assert plan.period_ns == 100_000_000
    assert plan.limited is False


def test_002_nplc_30hz_is_single_read() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=0.02, rate=30, az=False))
    assert plan.effective == 30
    assert plan.batch_size == 1
    assert plan.period_ns == 33_333_333
    assert plan.uniform is True
    assert plan.limited is False


def test_gpib_has_higher_capability_than_serial() -> None:
    plan = plan_rate(
        AcquisitionConfig(nplc=0.02, rate=1000, az=False),
        interface="gpib",
    )
    assert plan.capability == 1000
    assert plan.effective == 1000
    assert plan.batch_size == 50
    assert plan.period_ns == 50_000_000
    assert plan.limited is False


def test_02_nplc_30hz_is_single_read() -> None:
    plan = plan_rate(AcquisitionConfig(nplc=0.2, rate=30, az=False))
    assert plan.effective == 30
    assert plan.batch_size == 1
    assert plan.period_ns == 33_333_333
    assert plan.limited is False


def test_average_plan_divides_output_rate_by_n() -> None:
    plan = plan_rate(
        AcquisitionConfig(
            nplc=1,
            rate=10,
            az=False,
            average_enabled=True,
            average_count=10,
        )
    )
    # 输入仍按目标 10 次/秒读取，平均 10 次后输出 1 次/秒。
    assert plan.effective == 1
    assert plan.period_ns == 100_000_000
    assert plan.limited is False


def test_average_plan_respects_input_capability() -> None:
    plan = plan_rate(
        AcquisitionConfig(
            nplc=1,
            rate=30,
            az=False,
            average_enabled=True,
            average_count=10,
        )
    )
    # 输入上限 20 次/秒，平均 10 次后输出 2 次/秒。
    assert plan.effective == 2
    assert plan.period_ns == 50_000_000
    assert plan.limited is True
