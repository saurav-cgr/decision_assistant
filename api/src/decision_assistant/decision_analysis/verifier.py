from decimal import Decimal

from decision_assistant.decision_analysis.schemas import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
    DecisionVerification,
)


class DecisionAnalysisVerifier:
    """Checks that a calculated response still matches its immutable request."""

    def verify(
        self,
        request: DecisionAnalysisRequest,
        response: DecisionAnalysisResponse,
    ) -> DecisionVerification:
        errors: list[str] = []
        expected_ids = {option.id for option in request.options}
        actual_ids = {option.option_id for option in response.ranked_options}
        if actual_ids != expected_ids:
            errors.append("ranked options do not match request options")
        if response.ranked_options:
            expected_ranks = list(range(1, len(response.ranked_options) + 1))
            if [option.rank for option in response.ranked_options] != expected_ranks:
                errors.append("ranked option positions must be consecutive")
        for option in response.ranked_options:
            contribution_total = sum(
                (item.weighted_contribution for item in option.contributions), Decimal()
            )
            if contribution_total != option.total_score:
                errors.append(f"total score mismatch for option {option.option_id}")
        return DecisionVerification(
            valid=not errors,
            errors=errors,
            warnings=response.verification.warnings,
        )
