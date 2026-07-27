from types import SimpleNamespace

from app.api.ask_results import _resolution_metadata
from app.domain.enums import DecisionState


def test_resolution_metadata_only_maps_safe_computed_provenance() -> None:
    decision = SimpleNamespace(
        state=DecisionState.PROPOSED,
        provenance={
            "computed": {
                "basis": "majority",
                "value": "approve",
                "has_winner": True,
                "conflict": False,
                "eligible_count": 3,
                "substantive_count": 2,
                "quorum_met": True,
                "vote_counts": {"approve": 2},
                "private_detail": "do not expose",
            },
            "sensitive": {"actor": "hidden"},
        },
    )

    metadata = _resolution_metadata(decision)  # type: ignore[arg-type]

    assert metadata is not None
    assert metadata.model_dump(mode="json") == {
        "computed_winner": True,
        "computed_value": "approve",
        "computed_basis": "majority",
        "eligible_count": 3,
        "substantive_count": 2,
        "quorum_met": True,
        "conflict": False,
        "vote_counts": {"approve": 2},
        "proposal_state": "proposed",
    }
