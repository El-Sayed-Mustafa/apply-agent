

def test_retired_aggregators_stay_out_of_the_cycle():
    """
    themuse و remotive طلّعوا صفر وظيفة مؤهلة من 60. التقاعد
    قرار تشغيلي — الدوال سايبة لو رجعنا نحتاجهم.
    """
    from src import aggregators
    for name in aggregators.RETIRED:
        assert name not in aggregators.AGGREGATORS
        assert hasattr(aggregators, f"fetch_{name}")
