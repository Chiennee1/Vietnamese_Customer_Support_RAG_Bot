from app.db.seed import build_synthetic_dataset


def test_full_synthetic_dataset_has_required_scale_and_is_reproducible() -> None:
    first = build_synthetic_dataset(seed=20260723)
    second = build_synthetic_dataset(seed=20260723)

    assert len(first.products) == 100
    assert len(first.variants) == 300
    assert len(first.users) == 500
    assert len(first.orders) == 1_000
    assert len(first.warranties) == 600
    assert len(first.tickets) == 200
    assert first.variants[0].sku == second.variants[0].sku
    assert first.orders[-1].order_code == second.orders[-1].order_code


def test_synthetic_dataset_covers_business_edge_cases() -> None:
    dataset = build_synthetic_dataset(seed=20260723)

    assert {order.status.value for order in dataset.orders} == {
        "pending",
        "confirmed",
        "packing",
        "shipping",
        "delivered",
        "cancelled",
    }
    assert {warranty.status.value for warranty in dataset.warranties} == {
        "active",
        "expired",
        "void",
        "pending_review",
    }
    assert {ticket.severity.value for ticket in dataset.tickets} == {
        "normal",
        "high",
        "critical",
    }
