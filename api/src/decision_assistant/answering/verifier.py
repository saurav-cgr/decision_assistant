from collections.abc import Mapping
from uuid import UUID

from decision_assistant.answering.schemas import (
    AnswerState,
    EvidencePassage,
    GeneratedAnswer,
    VerificationError,
    VerificationResult,
)


class AnswerVerifier:
    def verify(
        self,
        answer: GeneratedAnswer,
        passages: Mapping[UUID, EvidencePassage],
    ) -> VerificationResult:
        errors: list[VerificationError] = []
        valid_cited_ids: set[UUID] = set()

        for citation in answer.citations:
            passage = passages.get(citation.passage_id)
            if passage is None:
                errors.append(
                    VerificationError(
                        code="citation_passage_not_found",
                        message="Citation passage does not exist in the evidence pack",
                        passage_id=citation.passage_id,
                    )
                )
                continue
            if not passage.active_version:
                errors.append(
                    VerificationError(
                        code="citation_inactive_version",
                        message="Citation passage is not from an active document version",
                        passage_id=citation.passage_id,
                    )
                )
                continue
            if citation.content_hash != passage.content_hash:
                errors.append(
                    VerificationError(
                        code="citation_hash_mismatch",
                        message="Citation content hash does not match stored evidence",
                        passage_id=citation.passage_id,
                    )
                )
                continue
            if (
                citation.end_offset > len(passage.content)
                or passage.content[citation.start_offset : citation.end_offset]
                != citation.quote
            ):
                errors.append(
                    VerificationError(
                        code="citation_offsets_mismatch",
                        message="Citation quote does not match the stored offset span",
                        passage_id=citation.passage_id,
                    )
                )
                continue
            valid_cited_ids.add(citation.passage_id)

        for claim in answer.claims:
            if claim.central and not claim.passage_ids:
                errors.append(
                    VerificationError(
                        code="central_claim_uncited",
                        message="Central claims require at least one citation",
                    )
                )
                continue
            missing = [
                passage_id
                for passage_id in claim.passage_ids
                if passage_id not in valid_cited_ids
            ]
            if missing:
                errors.append(
                    VerificationError(
                        code="claim_citation_invalid",
                        message="Claim references a citation that did not verify",
                        passage_id=missing[0],
                    )
                )
                continue
            self._verify_explicit_values(
                claim.explicit_entities + claim.explicit_dates,
                claim.passage_ids,
                passages,
                errors,
            )

        for conflict in answer.conflicts:
            missing = [
                passage_id
                for passage_id in conflict.passage_ids
                if passage_id not in passages
                or not passages[passage_id].active_version
            ]
            if missing:
                errors.append(
                    VerificationError(
                        code="conflict_citation_invalid",
                        message="Conflict references evidence not in the active evidence pack",
                        passage_id=missing[0],
                    )
                )

        has_supported_central_claim = any(
            claim.central
            and bool(claim.passage_ids)
            and all(
                passage_id in valid_cited_ids for passage_id in claim.passage_ids
            )
            for claim in answer.claims
        )
        state = self._state_for(
            errors=errors,
            has_supported_central_claim=has_supported_central_claim,
            has_conflicts=bool(answer.conflicts),
            has_unsupported_facets=bool(answer.unsupported_facets),
        )
        return VerificationResult(
            valid=not errors,
            state=state,
            errors=errors,
            conflicts=answer.conflicts,
            unsupported_facets=answer.unsupported_facets,
        )

    @staticmethod
    def _verify_explicit_values(
        values: list[str],
        passage_ids: list[UUID],
        passages: Mapping[UUID, EvidencePassage],
        errors: list[VerificationError],
    ) -> None:
        cited_content = "\n".join(
            passages[passage_id].content
            for passage_id in passage_ids
            if passage_id in passages
        ).casefold()
        for value in values:
            if value.casefold() not in cited_content:
                errors.append(
                    VerificationError(
                        code="explicit_value_not_in_evidence",
                        message=f"Claimed explicit value is absent from evidence: {value}",
                    )
                )

    @staticmethod
    def _state_for(
        *,
        errors: list[VerificationError],
        has_supported_central_claim: bool,
        has_conflicts: bool,
        has_unsupported_facets: bool,
    ) -> AnswerState:
        if errors or not has_supported_central_claim:
            return AnswerState.ABSTAINED
        if has_conflicts:
            return AnswerState.CONFLICTED
        if has_unsupported_facets:
            return AnswerState.PARTIAL
        return AnswerState.ANSWERED
