from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from knowledge_core.dynamo import KnowledgeRepository
from knowledge_core.identity import (
    email_name_tokens,
    names_are_plausibly_compatible,
)
from knowledge_core.models import (
    ContributorCandidate,
    MembershipSource,
    NameMatchDecision,
    NotificationKind,
)
from knowledge_core.notifications import NotificationPublisher
from knowledge_core.openai_api import OpenAIService
from knowledge_core.secrets import SecretProvider
from knowledge_core.settings import MatchingSettings

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

_SETTINGS = MatchingSettings.from_env()
_REPOSITORY = KnowledgeRepository(
    _SETTINGS.table_name,
    region_name=_SETTINGS.aws_region,
)
_SECRETS = SecretProvider(region_name=_SETTINGS.aws_region)


def _openai() -> OpenAIService:
    return OpenAIService(
        api_key=_SECRETS.get(
            _SETTINGS.openai_secret_arn,
            "api_key",
            use_cache=False,
        ),
        embedding_model=_SETTINGS.embedding_model,
        embedding_dimensions=_SETTINGS.embedding_dimensions,
        matching_model=_SETTINGS.matching_model,
    )


def _notifications() -> NotificationPublisher:
    import boto3

    return NotificationPublisher(
        repository=_REPOSITORY,
        queue_url=_SETTINGS.notification_queue_url,
        sqs_client=boto3.client("sqs", region_name=_SETTINGS.aws_region),
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = str(record.get("messageId") or "unknown")
        try:
            _process(json.loads(record["body"]))
        except Exception:
            LOGGER.exception("Contributor matching failed for %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _process(message: dict[str, Any]) -> None:
    kind = str(message.get("kind") or "")
    if kind == "candidate_created":
        _match_new_evidence(dict(message["evidence"]))
        return
    if kind == "user_verified":
        _match_verified_user(str(message["email"]))
        return
    raise ValueError(f"Unsupported matching message kind: {kind!r}")


def _match_new_evidence(evidence: dict[str, Any]) -> None:
    candidate = _candidate(evidence)
    plausible_profiles = [
        profile
        for profile in _REPOSITORY.list_user_profiles()
        if names_are_plausibly_compatible(
            email=str(profile["email"]),
            contributor_name=candidate.display_name,
        )
    ]
    matches = _verified_matches(
        candidate,
        plausible_profiles,
        evidence=evidence,
    )
    if len(matches) != 1:
        return
    profile, confidence, rationale = matches[0]
    _invite(profile, evidence, confidence=confidence, rationale=rationale)


def _match_verified_user(email: str) -> None:
    profile = _REPOSITORY.get_user_profile(email)
    if profile is None:
        return
    tokens = email_name_tokens(email)
    if len(tokens) < 2:
        return
    evidence_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evidence in _REPOSITORY.list_author_evidence_by_surname(tokens[-1]):
        if names_are_plausibly_compatible(
            email=email,
            contributor_name=str(evidence["display_name"]),
        ):
            evidence_by_project[str(evidence["project_id"])].append(evidence)

    for evidence_items in evidence_by_project.values():
        candidate_matches: list[tuple[dict[str, Any], float, str]] = []
        for evidence in evidence_items:
            candidate = _candidate(evidence)
            matches = _verified_matches(
                candidate,
                [profile],
                evidence=evidence,
            )
            if matches:
                _matched_profile, confidence, rationale = matches[0]
                candidate_matches.append((evidence, confidence, rationale))
        unique_names = {
            str(evidence["normalized_name"])
            for evidence, _confidence, _rationale in candidate_matches
        }
        if len(unique_names) != 1 or not candidate_matches:
            continue
        best = max(candidate_matches, key=lambda item: item[1])
        _invite(profile, best[0], confidence=best[1], rationale=best[2])


def _verified_matches(
    candidate: ContributorCandidate,
    profiles: list[dict[str, Any]],
    *,
    evidence: dict[str, Any],
) -> list[tuple[dict[str, Any], float, str]]:
    if not profiles:
        return []
    service = _openai()
    nearby_candidate_names = sorted(
        {
            str(item["display_name"])
            for item in _REPOSITORY.list_author_evidence(
                str(evidence["project_id"])
            )
            if item.get("evidence_id") != evidence.get("evidence_id")
        }
    )[:20]
    matches: list[tuple[dict[str, Any], float, str]] = []
    for profile in profiles:
        result = service.match_contributor_name(
            user_email=str(profile["email"]),
            user_display_name=str(
                profile.get("display_name") or profile["email"]
            ),
            candidate=candidate,
            nearby_candidate_names=nearby_candidate_names,
        )
        _REPOSITORY.put_name_match_evaluation(
            evidence=evidence,
            user_profile=profile,
            result=result,
            matching_model=_SETTINGS.matching_model,
            evaluated_by="contributor-matching-lambda",
        )
        if (
            result.decision == NameMatchDecision.MATCH
            and result.confidence >= _SETTINGS.matching_threshold
        ):
            matches.append(
                (profile, result.confidence, result.rationale)
            )
    return matches


def _invite(
    profile: dict[str, Any],
    evidence: dict[str, Any],
    *,
    confidence: float,
    rationale: str,
) -> None:
    if not _SETTINGS.name_invitations_enabled:
        LOGGER.info(
            "Shadow match retained for %s in %s; invitations are disabled",
            profile["email"],
            evidence["project_id"],
        )
        return
    email = str(profile["email"])
    project_id = str(evidence["project_id"])
    if _REPOSITORY.is_project_member(
        project_id=project_id,
        email=email,
    ):
        return
    project = _REPOSITORY.require_project(project_id)
    invitation, created = _REPOSITORY.create_collaboration_invitation(
        project_id=project_id,
        email=email,
        source=MembershipSource.DOCUMENT_NAME_MATCH,
        invited_by="contributor-matching-lambda",
        evidence={
            "evidence_id": evidence["evidence_id"],
            "document_id": evidence["document_id"],
            "document_name": evidence["document_name"],
            "page_number": evidence.get("page_number"),
            "locator": evidence.get("locator"),
            "candidate_name": evidence["display_name"],
            "match_confidence": confidence,
            "match_rationale": rationale,
            "extraction_version": evidence["extraction_version"],
        },
    )
    if not created:
        return
    _notifications().publish(
        email=email,
        kind=NotificationKind.COLLABORATION_INVITATION,
        title=f"Were you a contributor to {project['name']}?",
        message=(
            "Project documentation identifies someone with your name as a "
            "possible delivery contributor. Accept only if you recognize "
            "the project and your involvement."
        ),
        project_id=project_id,
        action_url=_SETTINGS.application_base_url,
        send_email=True,
        data={
            "project_name": project["name"],
            "invitation_id": invitation["invitation_id"],
            "candidate_name": evidence["display_name"],
            "document_name": evidence["document_name"],
        },
        notification_id=f"name-match-{invitation['invitation_id']}",
    )


def _candidate(evidence: dict[str, Any]) -> ContributorCandidate:
    confidence = evidence.get("confidence", 0.0)
    return ContributorCandidate(
        display_name=str(evidence["display_name"]),
        relationship=str(evidence["relationship"]),
        confidence=float(confidence),
        evidence=str(evidence["evidence"]),
    )
