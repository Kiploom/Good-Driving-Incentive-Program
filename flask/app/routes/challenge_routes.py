from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, jsonify, request, session
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Driver, Sponsor, SponsorChallenge
from app.services.challenge_service import ChallengeService


bp = Blueprint("challenges", __name__)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise ValueError("Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS).") from exc


def _require_sponsor() -> Sponsor:
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if sponsor:
        return sponsor

    if session.get("admin_id"):
        sponsor_id = request.args.get("sponsor_id") or request.json.get("sponsor_id") if request.is_json else None
        if not sponsor_id:
            raise PermissionError("Admin must provide sponsor_id to manage challenges.")
        sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
        if not sponsor:
            raise PermissionError("Sponsor not found.")
        return sponsor

    raise PermissionError("Access denied: sponsor role required.")


def _require_driver() -> Driver:
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if driver:
        return driver
    raise PermissionError("Access denied: driver role required.")


def _format_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


@bp.route("/sponsor/challenge-templates", methods=["GET"])
@login_required
def list_challenge_templates():
    if not session.get("admin_id"):
        try:
            _require_sponsor()
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

    templates = ChallengeService.list_templates(active_only=True)
    return jsonify(
        [
            {
                "id": template.ChallengeTemplateID,
                "code": template.Code,
                "title": template.Title,
                "description": template.Description,
                "default_reward_points": template.DefaultRewardPoints,
            }
            for template in templates
        ]
    )


@bp.route("/sponsor/challenges", methods=["GET"])
@login_required
def list_sponsor_challenges():
    try:
        sponsor = _require_sponsor()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    dtos = ChallengeService.list_sponsor_challenges(sponsor)
    db.session.commit()
    status_filter = (request.args.get("status") or "").lower().strip()

    def include(dto):
        if not status_filter or status_filter == "all":
            return True
        return dto.availability == status_filter

    data = []
    for dto in dtos:
        if not include(dto):
            continue
        challenge = dto.challenge
        data.append(
            {
                "id": challenge.SponsorChallengeID,
                "template_id": challenge.ChallengeTemplateID,
                "title": challenge.Title,
                "description": challenge.Description,
                "reward_points": challenge.RewardPoints,
                "is_optional": challenge.IsOptional,
                "starts_at": _format_datetime(challenge.StartsAt),
                "expires_at": _format_datetime(challenge.ExpiresAt),
                "is_active": challenge.IsActive,
                "status": dto.availability,
                "created_at": _format_datetime(challenge.CreatedAt),
                "updated_at": _format_datetime(challenge.UpdatedAt),
            }
        )

    return jsonify({"challenges": data})


@bp.route("/sponsor/challenges", methods=["POST"])
@login_required
def create_sponsor_challenge():
    if not request.is_json:
        return jsonify({"error": "Expected JSON payload."}), 400

    try:
        sponsor = _require_sponsor()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    payload = request.get_json() or {}
    payload.pop("sponsor_id", None)
    try:
        payload["starts_at"] = _parse_datetime(payload.get("starts_at"))
        payload["expires_at"] = _parse_datetime(payload.get("expires_at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        challenge = ChallengeService.create_sponsor_challenge(sponsor, payload)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    return (
        jsonify({
            "id": challenge.SponsorChallengeID,
            "template_id": challenge.ChallengeTemplateID,
        }),
        201,
    )


@bp.route("/sponsor/challenges/<challenge_id>", methods=["PATCH"])
@login_required
def update_sponsor_challenge(challenge_id: str):
    if not request.is_json:
        return jsonify({"error": "Expected JSON payload."}), 400

    try:
        sponsor = _require_sponsor()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    challenge = ChallengeService.get_challenge_for_sponsor(sponsor, challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found."}), 404

    payload = request.get_json() or {}
    payload.pop("sponsor_id", None)
    try:
        if "starts_at" in payload:
            payload["starts_at"] = _parse_datetime(payload.get("starts_at"))
        if "expires_at" in payload:
            payload["expires_at"] = _parse_datetime(payload.get("expires_at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        ChallengeService.update_sponsor_challenge(challenge, payload)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    return jsonify({"success": True})


@bp.route("/sponsor/challenges/<challenge_id>/deactivate", methods=["PATCH"])
@login_required
def deactivate_sponsor_challenge(challenge_id: str):
    try:
        sponsor = _require_sponsor()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    challenge = ChallengeService.get_challenge_for_sponsor(sponsor, challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found."}), 404

    ChallengeService.deactivate_challenge(challenge)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/driver/challenges", methods=["GET"])
@login_required
def driver_list_challenges():
    try:
        driver = _require_driver()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    challenges = ChallengeService.get_driver_active_challenges(driver)
    db.session.commit()
    for item in challenges:
        item["starts_at"] = _format_datetime(item.get("starts_at"))
        item["expires_at"] = _format_datetime(item.get("expires_at"))
    return jsonify({"challenges": challenges})


@bp.route("/driver/challenges/<challenge_id>/subscribe", methods=["POST"])
@login_required
def driver_subscribe_challenge(challenge_id: str):
    try:
        driver = _require_driver()
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403

    challenge = SponsorChallenge.query.filter_by(SponsorChallengeID=challenge_id).first()
    if not challenge:
        return jsonify({"error": "Challenge not found."}), 404

    try:
        subscription = ChallengeService.subscribe_driver_to_challenge(driver, challenge)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "subscription_id": subscription.DriverChallengeSubscriptionID,
        "status": subscription.Status,
    })


